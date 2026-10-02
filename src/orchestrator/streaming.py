"""The SSE side of the orchestrator: graph updates interleaved with answer tokens, as Server-Sent Events.

Mixed into ``Orchestrator`` (core.py); it expects ``self.graph``, ``self.llm_client`` and the helpers
``_annotate_unverified`` / ``_remember_in_background`` from there.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator

from src.orchestrator.common import _DEFAULT_MAX_RETRIES, _build_pev_trace, _initial_state
from src.orchestrator.prompt_templates import GRACEFUL_DECLINE_MESSAGE
from src.shared import answer_stream
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)


class StreamingMixin:
    async def _stream_with_answer_deltas(
        self, initial_state: dict[str, Any], config: dict[str, Any]
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """The graph's node updates (``("graph", {node: state})``) interleaved with answer tokens (``("answer", sse_event)``).

        The graph runs in its own task so a node that is busy writing an answer can push tokens meanwhile; the agent finds
        the sink through a context variable (set before the task is created, so the task and its children inherit it).
        """
        queue: asyncio.Queue = asyncio.Queue()
        token = answer_stream.attach(answer_stream.AnswerStream(queue))

        async def drive() -> None:
            try:
                async for event_data in self.graph.astream(initial_state, config=config):
                    await queue.put(("graph", event_data))
            except Exception as exc:  # noqa: BLE001 - re-raised on the consumer's side
                await queue.put(("error", exc))
            finally:
                await queue.put(("done", None))

        task = asyncio.create_task(drive())
        try:
            while True:
                kind, item = await queue.get()
                if kind == "done":
                    break
                if kind == "error":
                    raise item
                yield kind, item
        finally:
            task.cancel()  # the client left or the stream ended: stop the graph, no work for nobody
            answer_stream.detach(token)

    async def handle_stream_request(
        self,
        query: str,
        session_id: str,
        csv_content: str | None = None,
        csv_filename: str | None = None,
        agent_mode: str | None = None,
        target_agent: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Route a request through PEV workflow and stream SSE events.

        Yields SSE dicts with keys 'event' and 'data'.
        """
        logger.info(
            "LangGraph Orchestrator stream request (query_len=%d, mode=%s, target_agent=%s)",
            len(query),
            agent_mode,
            target_agent,
            extra={"session_id": session_id},
        )

        initial_state = _initial_state(
            query, session_id, csv_content, csv_filename, agent_mode, target_agent
        )

        request_id = str(uuid.uuid4())
        langfuse_handler = self.llm_client.get_langfuse_callback(
            session_id=session_id,
            user_id=session_id,
            trace_name=f"pev_loop_stream_{agent_mode or 'auto'}",
            tags=["pev_loop_stream", agent_mode or "auto"],
            metadata={"request_id": request_id, "query": query[:120]},
        )
        config: dict[str, Any] = {
            "configurable": {"thread_id": session_id}
        }
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        try:
            # Yield initial active state for Planner Node
            yield {
                "event": "pev_step",
                "data": json.dumps({
                    "step": "planner",
                    "status": "active",
                    "target": agent_mode or "",
                    "logs": "Đang phân tích yêu cầu và lập kế hoạch...",
                }, ensure_ascii=False),
            }
            await asyncio.sleep(0.01)

            # The final state is rebuilt from the nodes' own updates (AgentState has no reducers: last write wins), so
            # no checkpointer is needed to read it back at the end.
            final_values: dict[str, Any] = dict(initial_state)
            async for kind, item in self._stream_with_answer_deltas(initial_state, config):
                if kind == "answer":  # a token of the answer being written: forward it at once (a preview, see answer_stream)
                    yield item
                    continue
                event_data = item
                for node_name, node_state in event_data.items():
                    final_values.update(node_state or {})
                    if node_name == "planner":
                        target = node_state.get("target_agent", "")
                        plan_str = node_state.get("plan", "")

                        # 1. Phát event kết thúc Planner
                        yield {
                            "event": "plan",
                            "data": json.dumps({
                                "plan": plan_str,
                                "target_agent": target,
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "planner",
                                "status": "completed",
                                "target": target,
                                "logs": f"Planner đã hoàn tất -> Kế hoạch giao cho [{target}].",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        # 2. BẮT BUỘC PHÁT NGAY TRƯỚC KHI EXECUTOR BẮT ĐẦU:
                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "executor",
                                "status": "active",
                                "target": target,
                                "target_agent": target,
                                "logs": f"Agent [{target}] đang thực thi tác vụ...",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        # Phát sub-event tiến độ để thanh trạng thái nhấp nháy hoạt động
                        yield {
                            "event": "executing",
                            "data": json.dumps({
                                "status": "fetching_data",
                                "target_agent": target,
                                "message": f"Agent [{target}] đang khởi động và truy vấn dữ liệu...",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                    elif node_name == "executor":
                        target = node_state.get("target_agent", "")
                        exec_res = node_state.get("execution_result", "")
                        requires_approval = node_state.get("requires_human_approval", False)
                        approval_payload = node_state.get("approval_payload")

                        if requires_approval and approval_payload:
                            yield {
                                "event": "human_approval_required",
                                "data": json.dumps(approval_payload, ensure_ascii=False),
                            }
                            await asyncio.sleep(0.01)

                            yield {
                                "event": "pev_step",
                                "data": json.dumps({
                                    "step": "executor",
                                    "status": "active",
                                    "target": target,
                                    "logs": f"Tác vụ nhạy cảm trên [{target}] đang chờ phê duyệt từ người dùng...",
                                }, ensure_ascii=False),
                            }
                            await asyncio.sleep(0.01)

                        # 1. Phát event hoàn tất Executor:
                        yield {
                            "event": "executing",
                            "data": json.dumps({
                                "target_agent": target,
                                "execution_result": exec_res,
                                "status": "completed",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "executor",
                                "status": "completed",
                                "target": target,
                                "logs": f"Executor [{target}] đã hoàn tất xử lý tác vụ.",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        # 2. BẮT BUỘC PHÁT NGAY TRƯỚC KHI VERIFIER BẮT ĐẦU:
                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "verifier",
                                "status": "active",
                                "target": target,
                                "logs": "Verifier đang kiểm định chất lượng phản hồi và đối soát kế hoạch...",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                    elif node_name == "verifier":
                        is_v = node_state.get("is_verified", False)
                        fb = node_state.get("verifier_feedback", "")
                        retries = node_state.get("retry_count", 0)

                        yield {
                            "event": "verifying",
                            "data": json.dumps({
                                "is_verified": is_v,
                                "verifier_feedback": fb,
                                "retry_count": retries,
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "verifier",
                                "status": "completed" if is_v else "retry",
                                "feedback": fb,
                                "logs": "Verifier đã hoàn tất kiểm định." if is_v else f"Verifier yêu cầu chỉnh sửa (Lần {retries}).",
                            }, ensure_ascii=False),
                        }
                        await asyncio.sleep(0.01)

            response_text = (
                final_values.get("final_response")
                or final_values.get("execution_result")
                or GRACEFUL_DECLINE_MESSAGE
            )
            is_v = final_values.get("is_verified", True)
            retries = final_values.get("retry_count", 0)
            max_retries = final_values.get("max_retries", _DEFAULT_MAX_RETRIES)

            # Circuit Breaker: Annotate response if Verifier exhausted retries
            if not is_v and retries >= max_retries:
                response_text = self._annotate_unverified(response_text, retries)
                logger.warning(
                    "Stream PEV Loop: Max retries exhausted (retries=%d, verified=%s) — annotated response",
                    retries, is_v,
                    extra={"session_id": session_id},
                )

            yield {
                "event": "pev_step",
                "data": json.dumps({
                    "step": "completed",
                    "status": "verified" if is_v else "warning",
                }, ensure_ascii=False),
            }
            await asyncio.sleep(0.01)

            target_agent = final_values.get("target_agent", "")
            plan_str = final_values.get("plan", "")
            verifier_fb = final_values.get("verifier_feedback", "")

            pev_trace = _build_pev_trace(target_agent, plan_str, is_v, verifier_fb)

            yield {
                "event": "final_response",
                "data": json.dumps({
                    "response": response_text,
                    "target_agent": target_agent,
                    "is_verified": is_v,
                    "pev_trace": pev_trace,
                }, ensure_ascii=False),
            }
            await asyncio.sleep(0.01)

            self._remember_in_background(session_id, query)

        except Exception as exc:
            logger.error("LangGraph streaming error: %s", exc, extra={"session_id": session_id})
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Lỗi thực thi PEV Loop: {exc}"}, ensure_ascii=False),
            }
        finally:
            if self.llm_client:
                await self.llm_client.flush_async()
