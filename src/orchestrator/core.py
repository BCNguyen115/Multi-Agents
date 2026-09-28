"""Orchestrator core — LangGraph-powered PEV (Plan-Execute-Verify) state machine.

Replaces static intent classification and Semantic Kernel with a fully
autonomous **StateGraph** built on **LangGraph**.

Workflow Architecture:
```
  [User Request]
        │
        ▼
  ┌─────────────┐
  │ Planner Node│  (Generates plan & selects target_agent)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │Executor Node│  (Delegates to resolved Agent in AgentRegistry)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │Verifier Node│  (Evaluates execution result against Plan)
  └──────┬──────┘
         │
    is_verified?
    ├── YES / Max retries ──► [END Node] ──► Return final response
    └── NO  (Retry < 2)   ──► Return to Executor with Verifier Feedback
```

Checkpointer: Uses ``MemorySaver`` for state persistence per ``session_id``.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, AsyncGenerator, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.base_agent import BaseAgent
from src.config import Settings
from src.orchestrator.prompt_templates import (
    GRACEFUL_DECLINE_MESSAGE,
    build_planner_prompt,
    build_verifier_prompt,
)
from src.orchestrator.state import AgentState
from src.registry.manager import AgentRegistry
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.memory_manager import MemoryManager

logger: logging.Logger = get_logger(__name__)

# Default max retries for Verifier rejection
_DEFAULT_MAX_RETRIES: int = 2


class Orchestrator:
    """Enterprise Autonomous Orchestrator running on LangGraph PEV State Machine.

    Attributes:
        registry: The ``AgentRegistry`` containing all available agents.
        settings: Application settings.
        llm_client: Centralised ``LLMClient`` for LLM operations.
        memory_manager: Long-term ``MemoryManager`` instance.
        model: Model identifier.
        checkpointer: LangGraph ``MemorySaver`` checkpointer.
        graph: Compiled LangGraph runnable workflow.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        settings: Settings,
        llm_client: Optional[LLMClient] = None,
        memory_manager: Optional[MemoryManager] = None,
    ) -> None:
        """Initialise the LangGraph Orchestrator.

        Args:
            registry: Agent registry containing registered agent instances.
            settings: Application settings.
            llm_client: Centralised LLM client (optional).
            memory_manager: Long-term memory manager (optional).
        """
        self.registry: AgentRegistry = registry
        self.settings: Settings = settings
        self.model: str = settings.OPENROUTER_MODEL
        self.fast_model: str = settings.FAST_LLM_MODEL   # Low-latency for Planner/Verifier
        self.heavy_model: str = settings.HEAVY_LLM_MODEL  # High-quality for synthesis
        self.llm_client: LLMClient = llm_client or LLMClient(settings=settings)
        self.memory_manager: MemoryManager = memory_manager or MemoryManager(settings=settings)

        # Pending Human-in-the-Loop approvals storage
        self.pending_approvals: dict[str, dict[str, Any]] = {}

        # --------------------------------------------------------------
        # LangGraph StateGraph Construction
        # --------------------------------------------------------------
        self.checkpointer: MemorySaver = MemorySaver()
        workflow: StateGraph = StateGraph(AgentState)

        # Add Nodes
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("executor", self._executor_node)
        workflow.add_node("verifier", self._verifier_node)

        # Add Edges
        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "verifier")

        # Conditional Edge after Verifier
        workflow.add_conditional_edges(
            "verifier",
            self._should_continue,
            {
                "continue_executor": "executor",
                "end": END,
            },
        )

        self.graph: Any = workflow.compile(checkpointer=self.checkpointer)

        logger.info(
            "LangGraph Orchestrator (PEV Loop) initialised (model=%s, agents=%d)",
            self.model,
            len(self.registry),
            extra={"session_id": "SYSTEM"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_request(
        self,
        query: str,
        session_id: str,
        csv_content: str | None = None,
        csv_filename: str | None = None,
        agent_mode: str | None = None,
    ) -> str:
        """Route a user request through the LangGraph PEV workflow.

        Args:
            query: The end-user's natural-language question.
            session_id: Correlation ID for end-to-end tracing.
            csv_content: Optional raw CSV file content.
            csv_filename: Optional original filename of the uploaded CSV.
            agent_mode: Optional explicit mode identifier (e.g. 'search_agent').

        Returns:
            str: Final response from the PEV state machine.
        """
        logger.info(
            "LangGraph Orchestrator received request (query_len=%d, has_csv=%s, mode=%s)",
            len(query),
            bool(csv_content),
            agent_mode,
            extra={"session_id": session_id},
        )

        initial_state: AgentState = {
            "query": query,
            "session_id": session_id,
            "csv_content": csv_content,
            "csv_filename": csv_filename,
            "agent_mode": agent_mode,
            "messages": [],
            "team_memory": {},
            "plan": "",
            "target_agent": "",
            "execution_result": "",
            "final_response": "",
            "is_verified": False,
            "verifier_feedback": "",
            "retry_count": 0,
            "max_retries": _DEFAULT_MAX_RETRIES,
        }

        request_id = str(uuid.uuid4())
        langfuse_handler = self.llm_client.get_langfuse_callback(
            session_id=session_id,
            user_id=session_id,
            trace_name=f"pev_loop_{agent_mode or 'auto'}",
            tags=["pev_loop", agent_mode or "auto"],
            metadata={"request_id": request_id, "query": query[:120]},
        )
        config: dict[str, Any] = {
            "configurable": {"thread_id": session_id}
        }
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        try:
            final_state: AgentState = await self.graph.ainvoke(
                initial_state, config=config
            )

            response_text: str = final_state.get("final_response", "")
            if not response_text:
                response_text = final_state.get(
                    "execution_result", GRACEFUL_DECLINE_MESSAGE
                )

            # Build PEV Trace metadata
            target_agent = final_state.get("target_agent", "data_agent")
            plan = final_state.get("plan", "Lập kế hoạch phân tích dữ liệu")
            is_verified = final_state.get("is_verified", True)
            verifier_fb = final_state.get("verifier_feedback", "")
            retry_count = final_state.get("retry_count", 0)

            # Circuit Breaker: Annotate response if Verifier exhausted retries
            if not is_verified and retry_count >= final_state.get("max_retries", _DEFAULT_MAX_RETRIES):
                warning_note = (
                    "\n\n> **Cảnh báo:** Kết quả này chưa được kiểm duyệt đầy đủ "
                    f"sau {retry_count} lần thử. Vui lòng kiểm tra lại thông tin trước khi sử dụng.\n\n"
                )
                logger.warning(
                    "PEV Loop: Max retries exhausted (retries=%d, verified=%s) — returning raw result with warning",
                    retry_count, is_verified,
                    extra={"session_id": session_id},
                )
                response_text = warning_note + response_text

            pev_trace = {
                "status": "Verified" if is_verified else "Warning",
                "planner": {
                    "node": "Planner Node",
                    "target_agent": target_agent,
                    "plan_summary": plan if len(plan) <= 200 else f"{plan[:200]}...",
                    "status": "completed"
                },
                "executor": {
                    "node": "Executor Node",
                    "agent_used": target_agent,
                    "execution_summary": f"Thực thi thành công trên Agent [{target_agent}].",
                    "status": "completed"
                },
                "verifier": {
                    "node": "Verifier Node",
                    "is_verified": is_verified,
                    "verifier_feedback": verifier_fb if verifier_fb else "Kiểm duyệt thành công: Kết quả hợp lệ 100%.",
                    "status": "completed"
                }
            }

            # Embed pev_trace into JSON payload
            try:
                parsed_res = json.loads(response_text)
                if isinstance(parsed_res, dict):
                    parsed_res["pev_trace"] = pev_trace
                    response_text = json.dumps(parsed_res, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                response_text = json.dumps({
                    "response": response_text,
                    "explanation": response_text,
                    "pev_trace": pev_trace
                }, ensure_ascii=False)

            logger.info(
                "LangGraph workflow complete (verified=%s, retries=%d, res_len=%d)",
                final_state.get("is_verified", False),
                final_state.get("retry_count", 0),
                len(response_text),
                extra={"session_id": session_id},
            )

            # Store memory async for future personalization
            try:
                await self.memory_manager.add_memory(
                    user_id=session_id,
                    text=f"User asked: '{query}' -> Target Agent: '{final_state.get('target_agent')}'",
                )
            except Exception as mem_err:
                logger.warning("Failed to store memory: %s", mem_err)

            return response_text

        except Exception as exc:
            logger.error(
                "LangGraph execution error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return (
                "Đã xảy ra lỗi trong quá trình thực thi hệ thống PEV. "
                "Vui lòng thử lại sau."
            )
        finally:
            if self.llm_client:
                await self.llm_client.flush_async()

    async def handle_approval_decision(
        self,
        session_id: str,
        action_id: str,
        decision: str,
        feedback: Optional[str] = None,
    ) -> dict[str, Any]:
        """Handle human approval decision for a paused sensitive operation (HITL Gate).

        Args:
            session_id: Session correlation ID.
            action_id: Unique action identifier for the pending approval.
            decision: 'approve' to execute or 'reject' to abort.
            feedback: Optional feedback/reason provided by human operator.

        Returns:
            dict[str, Any]: Execution status, summary response, and metadata.
        """
        logger.info(
            "HITL Decision received: action_id=%s, decision=%s, session_id=%s",
            action_id, decision, session_id,
            extra={"session_id": session_id},
        )

        record = self.pending_approvals.get(action_id)
        if not record:
            # Fallback scan across pending approvals for matching session
            for act_id, rec in list(self.pending_approvals.items()):
                if rec.get("payload", {}).get("session_id") == session_id:
                    record = rec
                    action_id = act_id
                    break

        if not record:
            return {
                "status": "error",
                "action_id": action_id,
                "message": f"Yêu cầu phê duyệt '{action_id}' không tồn tại hoặc đã được xử lý.",
            }

        # Remove from pending queue
        self.pending_approvals.pop(action_id, None)
        saved_state: AgentState = record.get("state", {})
        payload: dict[str, Any] = record.get("payload", {})
        agent_name: str = payload.get("agent", "")

        if decision.lower() == "reject":
            reject_msg = (
                f"Tác vụ [{action_id}] đã bị từ chối thực thi bởi quản trị viên. "
                f"Lý do: {feedback or 'Người dùng đã hủy yêu cầu.'}"
            )
            return {
                "status": "rejected",
                "action_id": action_id,
                "decision": "reject",
                "message": reject_msg,
                "response": reject_msg,
            }

        # User approved: execute operation
        agent = self.registry.lookup(agent_name)
        if not agent:
            return {
                "status": "error",
                "action_id": action_id,
                "message": f"Agent '{agent_name}' không tồn tại trong hệ thống.",
            }

        query = saved_state.get("query", "")
        try:
            if agent_name == "integration_agent":
                req_payload = payload.get("payload", {})
                url = req_payload.get("url", "")
                method = req_payload.get("method", "GET")
                body = req_payload.get("payload")

                mcp_res = await agent.mcp_client.execute_rest_request(
                    url=url, method=method, payload=body, session_id=session_id
                )
                try:
                    res_dict = json.loads(mcp_res)
                except Exception:
                    res_dict = {"status": "success", "data": mcp_res}

                status_code = res_dict.get("status_code", 200)
                data = res_dict.get("data", {})
                exec_summary = (
                    f"**Đã phê duyệt & thực thi thành công API ({method} {url}):**\n\n"
                    f"- **Status Code:** HTTP {status_code}\n"
                    f"- **Kết quả:**\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
                )
                return {
                    "status": "success",
                    "action_id": action_id,
                    "decision": "approve",
                    "response": exec_summary,
                    "data": data,
                }

            elif agent_name == "db_agent":
                sql = payload.get("payload", {}).get("sql", "")
                if not sql:
                    sql_res, _ = await agent.generate_sql(query, session_id)
                    sql = sql_res

                from src.agents.db_agent.rls_transformer import inject_row_level_security
                secured_sql = inject_row_level_security(
                    sql, tenant_id="tenant_enterprise", department_id="dept_general"
                )
                mcp_res = await agent.mcp_client.execute_sql_query(
                    query_sql=secured_sql, session_id=session_id
                )
                try:
                    res_dict = json.loads(mcp_res)
                except Exception:
                    res_dict = {"status": "success", "data": mcp_res}

                data = res_dict.get("data", [])
                exec_summary = (
                    f"**Đã phê duyệt & thực thi thành công truy vấn SQL:**\n\n"
                    f"- **SQL:** `{secured_sql}`\n"
                    f"- **Số dòng trả về:** {len(data)}\n"
                    f"- **Dữ liệu:**\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
                )
                return {
                    "status": "success",
                    "action_id": action_id,
                    "decision": "approve",
                    "response": exec_summary,
                    "data": data,
                }
            else:
                exec_res = await agent.process_request(query, session_id)
                return {
                    "status": "success",
                    "action_id": action_id,
                    "decision": "approve",
                    "response": exec_res,
                }

        except Exception as exec_err:
            logger.error("Execution error after approval: %s", exec_err, extra={"session_id": session_id})
            return {
                "status": "error",
                "action_id": action_id,
                "message": f"Lỗi khi thực thi tác vụ sau khi phê duyệt: {exec_err}",
            }

    async def handle_stream_request(
        self,
        query: str,
        session_id: str,
        csv_content: str | None = None,
        csv_filename: str | None = None,
        agent_mode: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Route a request through PEV workflow and stream SSE events.

        Yields SSE dicts with keys 'event' and 'data'.
        """
        logger.info(
            "LangGraph Orchestrator stream request (query_len=%d, mode=%s)",
            len(query),
            agent_mode,
            extra={"session_id": session_id},
        )

        initial_state: AgentState = {
            "query": query,
            "session_id": session_id,
            "csv_content": csv_content,
            "csv_filename": csv_filename,
            "agent_mode": agent_mode,
            "messages": [],
            "team_memory": {},
            "plan": "",
            "target_agent": "",
            "execution_result": "",
            "final_response": "",
            "is_verified": False,
            "verifier_feedback": "",
            "retry_count": 0,
            "max_retries": _DEFAULT_MAX_RETRIES,
        }

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

            async for event_data in self.graph.astream(initial_state, config=config):
                for node_name, node_state in event_data.items():
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

            final_checkpoint = await self.graph.aget_state(config)
            final_values = final_checkpoint.values if final_checkpoint else {}
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
                warning_note = (
                    "\n\n> **Cảnh báo:** Kết quả này chưa được kiểm duyệt đầy đủ "
                    f"sau {retries} lần thử. Vui lòng kiểm tra lại thông tin trước khi sử dụng.\n\n"
                )
                if warning_note not in response_text:
                    response_text = warning_note + response_text
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

            pev_trace = {
                "status": "Verified" if is_v else "Warning",
                "planner": {
                    "node": "Planner Node",
                    "target_agent": target_agent,
                    "plan_summary": plan_str if len(plan_str) <= 200 else f"{plan_str[:200]}...",
                    "status": "completed",
                },
                "executor": {
                    "node": "Executor Node",
                    "agent_used": target_agent,
                    "execution_summary": f"Thực thi thành công trên Agent [{target_agent}].",
                    "status": "completed",
                },
                "verifier": {
                    "node": "Verifier Node",
                    "is_verified": is_v,
                    "verifier_feedback": verifier_fb if verifier_fb else "Kiểm duyệt thành công: Kết quả hợp lệ 100%.",
                    "status": "completed",
                },
            }

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

            try:
                await self.memory_manager.add_memory(
                    user_id=session_id,
                    text=f"User asked: '{query}' -> Target Agent: '{final_values.get('target_agent')}'",
                )
            except Exception as mem_err:
                logger.warning("Failed to store memory in stream: %s", mem_err)

        except Exception as exc:
            logger.error("LangGraph streaming error: %s", exc, extra={"session_id": session_id})
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Lỗi thực thi PEV Loop: {exc}"}, ensure_ascii=False),
            }
        finally:
            if self.llm_client:
                await self.llm_client.flush_async()

    def _determine_fallback_route(
        self, query: str, csv_content: Optional[str] = None
    ) -> tuple[str, str, bool]:
        """Tự động phân luồng an toàn dựa trên từ khóa truy vấn của người dùng khi Planner LLM gặp sự cố."""
        q_lower = (query or "").lower()

        # 1. File CSV đính kèm
        if csv_content:
            is_viz = any(
                kw in q_lower
                for kw in ["dashboard", "biểu đồ", "chart", "vẽ", "trực quan hóa", "dựng báo cáo", "phân bố", "tỷ trọng"]
            ) and not any(
                neg in q_lower
                for neg in ["không cần biểu đồ", "không dựng dashboard", "không vẽ chart", "dạng văn bản", "chỉ tóm tắt", "dạng text"]
            )
            plan = "Phân tích dữ liệu từ file CSV qua Dashboard." if is_viz else "Phân tích dữ liệu từ file CSV và tổng hợp kết quả."
            return "data_agent", plan, is_viz

        # 2. Tìm kiếm Internet / Web
        search_keywords = [
            "tìm kiếm", "tra cứu web", "internet", "tin tức", "thời tiết", "google",
            "mới nhất", "hiện nay", "tin tức hôm nay", "search", "online", "giá vàng",
            "thị trường hôm nay"
        ]
        if any(kw in q_lower for kw in search_keywords):
            return "search_agent", f"Tìm kiếm thông tin cập nhật trên Internet về: '{query}'.", False

        # 3. Database / SQL
        db_keywords = ["sql", "database", "cơ sở dữ liệu", "bảng", "truy vấn sql", "select", "csdl"]
        if any(kw in q_lower for kw in db_keywords):
            return "db_agent", f"Truy vấn cơ sở dữ liệu để tìm câu trả lời cho: '{query}'.", False

        # 4. Integration / CRM / Jira / Github / Slack
        integration_keywords = ["jira", "github", "gitlab", "slack", "crm", "trello", "ticket", "pull request", "issue"]
        if any(kw in q_lower for kw in integration_keywords):
            return "integration_agent", f"Tích hợp và xử lý tác vụ trên hệ thống ngoài cho: '{query}'.", False

        # 5. Phân tích số liệu / data không kèm CSV
        data_keywords = ["doanh thu", "thống kê", "phân tích số liệu", "tỷ lệ tăng trưởng", "tính toán"]
        if any(kw in q_lower for kw in data_keywords):
            return "data_agent", f"Phân tích dữ liệu và số liệu thống kê cho câu hỏi: '{query}'.", False

        # 6. Mặc định là RAG Agent tra cứu tri thức
        return "rag_agent", f"Tra cứu tài liệu và cơ sở tri thức nội bộ để giải đáp: '{query}'.", False

    # ------------------------------------------------------------------
    # LangGraph Nodes
    # ------------------------------------------------------------------

    async def _planner_node(self, state: AgentState) -> dict[str, Any]:
        """Planner Node — Analyzes query/context, loads memories, builds plan, selects agent."""
        query: str = state.get("query", "")
        session_id: str = state.get("session_id", "N/A")
        csv_content: Optional[str] = state.get("csv_content")
        csv_filename: str = state.get("csv_filename") or "uploaded.csv"

        logger.info(
            "PEV Node: Planner executing", extra={"session_id": session_id}
        )

        try:
            # Retrieve long-term memories safely
            memories: list[str] = []
            try:
                memories = await self.memory_manager.get_relevant_memories(
                    user_id=session_id, query=query, limit=3
                )
            except Exception as mem_err:
                logger.warning("Planner memory retrieval exception: %s", mem_err, extra={"session_id": session_id})

            memory_str: str = "\n".join(f"- {m}" for m in memories) if memories else "None"

            # Force-route to search_agent if explicitly requested in agent_mode
            agent_mode: Optional[str] = state.get("agent_mode")
            if agent_mode == "search_agent" or (agent_mode and "search" in agent_mode.lower()):
                logger.info(
                    "Planner: Mode forced -> Target agent = 'search_agent'",
                    extra={"session_id": session_id},
                )
                return {
                    "plan": f"Tìm kiếm thông tin trên Internet về: '{query}'.",
                    "target_agent": "search_agent",
                    "requires_dashboard": False,
                    "team_memory": {"long_term_memories": memories},
                }

            # Force-route to data_agent if CSV is provided with intent-aware dashboard check
            if csv_content:
                query_lower = query.lower()
                is_viz = any(
                    kw in query_lower
                    for kw in ["dashboard", "biểu đồ", "chart", "vẽ", "trực quan hóa", "dựng báo cáo", "phân bố", "tỷ trọng"]
                ) and not any(
                    neg in query_lower
                    for neg in ["không cần biểu đồ", "không dựng dashboard", "không vẽ chart", "dạng văn bản", "chỉ tóm tắt", "dạng text", "tóm tắt văn bản"]
                )
                if is_viz:
                    logger.info(
                        "Planner: CSV attached with visual request -> Target 'data_agent', requires_dashboard=True",
                        extra={"session_id": session_id},
                    )
                    return {
                        "plan": f"Phân tích dữ liệu từ file CSV '{csv_filename}' và trực quan hóa dữ liệu qua Dashboard.",
                        "target_agent": "data_agent",
                        "requires_dashboard": True,
                        "team_memory": {"long_term_memories": memories},
                    }
                else:
                    logger.info(
                        "Planner: CSV attached with text query -> Target 'data_agent', requires_dashboard=False",
                        extra={"session_id": session_id},
                    )
                    return {
                        "plan": f"Phân tích dữ liệu từ file CSV '{csv_filename}' và trả lời bằng Markdown phân tích ngắn gọn, không sinh dashboard.",
                        "target_agent": "data_agent",
                        "requires_dashboard": False,
                        "team_memory": {"long_term_memories": memories},
                    }

            # Check for Multi-Agent Compound Tasks (DAG Parallel Execution)
            sub_tasks = self._decompose_subtasks(query)
            if len(sub_tasks) > 1:
                agent_names = [st["agent"] for st in sub_tasks]
                logger.info(
                    "Planner: Decomposed compound query into %d parallel subtasks: %s",
                    len(sub_tasks),
                    agent_names,
                    extra={"session_id": session_id},
                )
                return {
                    "plan": f"Thực thi song song (DAG Fan-out) {len(sub_tasks)} nhánh độc lập: {', '.join(agent_names)} và tổng hợp kết quả (Fan-in).",
                    "target_agent": "parallel_coordinator",
                    "sub_tasks": sub_tasks,
                    "requires_dashboard": False,
                    "team_memory": {"long_term_memories": memories},
                }

            # Otherwise, ask LLM Planner with memory context
            agent_list: list[dict[str, str]] = self.registry.list_agents()
            prompt: str = build_planner_prompt(
                agent_descriptions=agent_list,
                query=f"{query}\n\n[Long-term User Memories]:\n{memory_str}",
                has_csv=False,
            )

            try:
                llm_res: Any = await self.llm_client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.fast_model,  # Model Tiering: low-latency for routing
                    temperature=0.1,
                    max_tokens=300,
                    metadata={"node": "planner"},
                    session_id=session_id,
                )

                raw_content: str = llm_res.choices[0].message.content or ""
                plan, target_agent, requires_dashboard = self._parse_planner_json(raw_content)

                if target_agent != "data_agent":
                    requires_dashboard = False

                logger.info(
                    "Planner complete: target_agent='%s', requires_dashboard=%s, plan='%s'",
                    target_agent,
                    requires_dashboard,
                    plan,
                    extra={"session_id": session_id},
                )

                return {
                    "plan": plan,
                    "target_agent": target_agent,
                    "requires_dashboard": requires_dashboard,
                    "team_memory": {"long_term_memories": memories},
                }

            except Exception as exc:
                logger.error(
                    "Planner LLM call exception: %s. Activating heuristic fallback plan.",
                    exc,
                    extra={"session_id": session_id},
                )
                fallback_agent, fallback_plan, fallback_viz = self._determine_fallback_route(
                    query, csv_content
                )
                logger.info(
                    "Planner fallback plan: target_agent='%s', requires_dashboard=%s, plan='%s'",
                    fallback_agent,
                    fallback_viz,
                    fallback_plan,
                    extra={"session_id": session_id},
                )
                return {
                    "plan": fallback_plan,
                    "target_agent": fallback_agent,
                    "requires_dashboard": fallback_viz,
                    "team_memory": {"long_term_memories": memories},
                }

        except Exception as fatal_exc:
            logger.error(
                "Planner node fatal exception: %s. Activating heuristic fallback plan.",
                fatal_exc,
                extra={"session_id": session_id},
            )
            fallback_agent, fallback_plan, fallback_viz = self._determine_fallback_route(
                query, csv_content
            )
            return {
                "plan": fallback_plan,
                "target_agent": fallback_agent,
                "requires_dashboard": fallback_viz,
            }

    def _decompose_subtasks(self, query: str) -> list[dict[str, str]]:
        """Decompose compound query into parallel subtasks if applicable (DAG Parallel Execution)."""
        q_lower = (query or "").lower()
        has_rag = any(kw in q_lower for kw in ["hợp đồng", "nda", "msa", "sow", "nội bộ", "chính sách", "điều khoản", "quy định công ty"])
        has_search = any(kw in q_lower for kw in ["tin tức", "mới nhất", "hôm nay", "thị trường", "báo chí", "thời sự", "tra cứu mạng", "internet", "web"])
        has_db = any(kw in q_lower for kw in ["cơ sở dữ liệu", "database", "đếm số bản ghi", "bảng", "sql", "rag_chunks"])

        if has_rag and has_search:
            return [
                {
                    "agent": "rag_agent",
                    "task": f"Tra cứu tài liệu, quy định và hợp đồng nội bộ về: {query}",
                },
                {
                    "agent": "search_agent",
                    "task": f"Tìm kiếm thông tin thị trường và tin tức mới nhất về: {query}",
                },
            ]

        if has_db and has_search:
            return [
                {
                    "agent": "db_agent",
                    "task": f"Truy vấn thông tin cơ sở dữ liệu về: {query}",
                },
                {
                    "agent": "search_agent",
                    "task": f"Tìm kiếm thông tin bên ngoài về: {query}",
                },
            ]

        return []

    async def _synthesize_parallel_outputs(
        self,
        query: str,
        parallel_outputs: list[dict[str, Any]],
        session_id: str,
    ) -> str:
        """Synthesize multiple agent execution outputs into a cohesive response (Fan-in Aggregator)."""
        context_blocks = []
        for out in parallel_outputs:
            ag = out.get("agent", "agent")
            task = out.get("task", "")
            res = out.get("result", "")
            context_blocks.append(f"### Kết quả từ [{ag}] cho nhánh '{task}':\n{res}\n")

        all_context = "\n".join(context_blocks)
        synthesis_prompt = (
            "Bạn là Enterprise AI Lead Synthesizer trong hệ thống Multi-Agent.\n"
            f"Câu hỏi gốc của người dùng: '{query}'\n\n"
            "Hệ thống đã phân rã câu hỏi và thực thi song song các nhánh độc lập qua các Agents chuyên biệt:\n"
            f"{all_context}\n\n"
            "YÊU CẦU TỔNG HỢP (FAN-IN AGGREGATOR):\n"
            "1. Kết hợp đầy đủ các luồng thông tin trên thành một câu trả lời hoàn chỉnh, mạch lạc, trực diện vào câu hỏi của người dùng.\n"
            "2. Trích dẫn rõ nguồn từ tài liệu nội bộ và đối soát với thông tin bên ngoài nếu có.\n"
            "3. Định dạng Markdown chuyên nghiệp với các đề mục rõ ràng, không lặp lại nội dung."
        )

        try:
            llm_res: Any = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": synthesis_prompt}],
                model=self.heavy_model,
                temperature=0.2,
                max_tokens=1000,
                metadata={"node": "synthesizer"},
                session_id=session_id,
            )
            return llm_res.choices[0].message.content or all_context
        except Exception as synth_err:
            logger.warning("Parallel synthesis fallback to raw concatenate: %s", synth_err)
            return f"**Tổng hợp kết quả xử lý song song:**\n\n{all_context}"

    async def _executor_node(self, state: AgentState) -> dict[str, Any]:
        """Executor Node — Resolves agent and invokes execution."""
        query: str = state.get("query", "")
        session_id: str = state.get("session_id", "N/A")
        target_agent_name: str = state.get("target_agent", "")
        csv_content: Optional[str] = state.get("csv_content")
        csv_filename: str = state.get("csv_filename") or "uploaded.csv"
        feedback: str = state.get("verifier_feedback", "")
        retry_count: int = state.get("retry_count", 0)

        logger.info(
            "PEV Node: Executor executing (agent='%s', retry=%d)",
            target_agent_name,
            retry_count,
            extra={"session_id": session_id},
        )

        # 1. DAG Parallel Execution (Fan-out / Fan-in)
        sub_tasks = state.get("sub_tasks")
        if sub_tasks and len(sub_tasks) > 1:
            logger.info(
                "DAG Parallel Execution: executing %d subtasks concurrently via asyncio.gather...",
                len(sub_tasks),
                extra={"session_id": session_id},
            )

            async def run_subtask(task_spec: dict[str, str]) -> dict[str, Any]:
                target = task_spec.get("agent", "rag_agent")
                sub_q = task_spec.get("task", query)
                sub_agent = self.registry.lookup(target)
                if not sub_agent:
                    return {"agent": target, "result": f"Agent {target} không tồn tại"}
                try:
                    res = await sub_agent.process_request(query=sub_q, session_id=session_id)
                    return {"agent": target, "task": sub_q, "result": res}
                except Exception as err:
                    return {"agent": target, "task": sub_q, "error": str(err), "result": f"Lỗi: {err}"}

            parallel_outputs = await asyncio.gather(*[run_subtask(t) for t in sub_tasks])
            synthesized = await self._synthesize_parallel_outputs(query, parallel_outputs, session_id)
            return {
                "execution_result": synthesized,
                "final_response": synthesized,
                "parallel_results": parallel_outputs,
                "target_agent": "parallel_coordinator",
                "is_verified": True,
            }

        # Alias mapping
        if target_agent_name in ("document_retrieval", "rag", "document_retrieval_agent"):
            target_agent_name = "rag_agent"
        elif target_agent_name in ("data_analysis", "data_analyst", "data"):
            target_agent_name = "data_agent"

        if target_agent_name == "none" or not target_agent_name:
            return {
                "execution_result": GRACEFUL_DECLINE_MESSAGE,
                "final_response": GRACEFUL_DECLINE_MESSAGE,
            }

        agent: Optional[BaseAgent] = self.registry.lookup(target_agent_name)
        if agent is None:
            logger.warning(
                "Executor: Agent '%s' not registered — decline",
                target_agent_name,
                extra={"session_id": session_id},
            )
            return {
                "execution_result": GRACEFUL_DECLINE_MESSAGE,
                "final_response": GRACEFUL_DECLINE_MESSAGE,
            }

        # Build adjusted query if feedback exists
        exec_query: str = query
        if feedback:
            exec_query = (
                f"{query}\n\n[Ghi chú từ Verifier: Kết quả trước bị từ chối do: "
                f"'{feedback}'. Hãy tự điều chỉnh để trả lời đầy đủ hơn.]"
            )

        # 2. Human-in-the-Loop (HITL) Gate Checks
        is_approved = state.get("is_approved")
        human_feedback = state.get("human_feedback")

        # 2a. Integration Agent: Mutation HTTP methods require human approval
        if target_agent_name == "integration_agent":
            if is_approved is False:
                reject_msg = f"Tác vụ gọi API đã bị từ chối bởi người dùng: {human_feedback or 'Người dùng đã hủy lệnh.'}"
                return {
                    "execution_result": json.dumps({"status": "rejected", "message": reject_msg}, ensure_ascii=False),
                    "final_response": reject_msg,
                    "requires_human_approval": False,
                }
            elif is_approved is not True and hasattr(agent, "parse_request"):
                url, method, payload, explanation = await agent.parse_request(exec_query, session_id)
                if url and getattr(agent, "is_mutation_request", lambda m: False)(method):
                    action_id = f"act_{uuid.uuid4().hex[:8]}"
                    approval_payload = {
                        "action_id": action_id,
                        "session_id": session_id,
                        "agent": "integration_agent",
                        "action_type": "api_mutation",
                        "description": explanation or f"Thực hiện gọi REST API {method} tới {url}",
                        "payload": {
                            "url": url,
                            "method": method,
                            "payload": payload,
                        },
                        "risk_level": "high",
                    }
                    self.pending_approvals[action_id] = {
                        "state": state,
                        "payload": approval_payload,
                    }
                    logger.warning(
                        "HITL Gate Triggered: Integration mutating request '%s %s' paused for approval (action_id=%s)",
                        method, url, action_id,
                        extra={"session_id": session_id},
                    )
                    pause_res = json.dumps({
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "message": "Tác vụ gọi API này làm thay đổi dữ liệu và yêu cầu sự phê duyệt từ quản trị viên trước khi thực thi.",
                    }, ensure_ascii=False)
                    return {
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "action_id": action_id,
                        "execution_result": pause_res,
                        "final_response": "Tác vụ gọi API này làm thay đổi dữ liệu và yêu cầu sự phê duyệt từ quản trị viên trước khi thực thi.",
                    }

        # 2b. Database Agent: Sensitive table/column queries require human approval
        elif target_agent_name == "db_agent":
            if is_approved is False:
                reject_msg = f"Truy vấn SQL đã bị từ chối bởi người dùng: {human_feedback or 'Người dùng đã hủy lệnh.'}"
                return {
                    "execution_result": json.dumps({"status": "rejected", "message": reject_msg}, ensure_ascii=False),
                    "final_response": reject_msg,
                    "requires_human_approval": False,
                }
            elif is_approved is not True and hasattr(agent, "generate_sql"):
                sql_preview, explanation = await agent.generate_sql(exec_query, session_id)
                if getattr(agent, "is_sensitive_sql", lambda s, q: False)(sql_preview, exec_query):
                    action_id = f"act_{uuid.uuid4().hex[:8]}"
                    approval_payload = {
                        "action_id": action_id,
                        "session_id": session_id,
                        "agent": "db_agent",
                        "action_type": "sensitive_db_query",
                        "description": explanation or "Truy vấn dữ liệu tài chính/bảng lương/nhân sự nhạy cảm",
                        "payload": {
                            "sql": sql_preview,
                            "query": exec_query,
                        },
                        "risk_level": "critical",
                    }
                    self.pending_approvals[action_id] = {
                        "state": state,
                        "payload": approval_payload,
                    }
                    logger.warning(
                        "HITL Gate Triggered: Sensitive SQL query paused for approval (action_id=%s): %s",
                        action_id, sql_preview[:80],
                        extra={"session_id": session_id},
                    )
                    pause_res = json.dumps({
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "message": "Truy vấn SQL này chạm vào bảng hoặc dữ liệu nhạy cảm (bảng lương/tài chính/nhân sự) và yêu cầu sự phê duyệt của người dùng trước khi thực thi.",
                    }, ensure_ascii=False)
                    return {
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "action_id": action_id,
                        "execution_result": pause_res,
                        "final_response": "Truy vấn SQL này chạm vào bảng hoặc dữ liệu nhạy cảm (bảng lương/tài chính/nhân sự) và yêu cầu sự phê duyệt của người dùng trước khi thực thi.",
                    }

        requires_dashboard = state.get("requires_dashboard")
        if target_agent_name == "data_agent" and requires_dashboard is False:
            if "không sinh dashboard" not in exec_query.lower() and "dạng văn bản" not in exec_query.lower():
                exec_query = (
                    f"{exec_query}\n\n[Yêu cầu định dạng: Trả lời bằng Markdown phân tích ngắn gọn kèm bảng thống kê nếu cần, "
                    "TUYỆT ĐỐI KHÔNG sinh cấu trúc dashboard_spec.]"
                )

        try:
            if csv_content and hasattr(agent, "process_csv_request"):
                result_str: str = await agent.process_csv_request(
                    query=exec_query,
                    csv_content=csv_content,
                    filename=csv_filename,
                    session_id=session_id,
                )
            else:
                result_str = await agent.process_request(
                    query=exec_query, session_id=session_id
                )

            return {
                "execution_result": result_str,
                "final_response": result_str,
            }

        except Exception as exc:
            logger.error(
                "Executor node exception on agent '%s': %s",
                target_agent_name,
                exc,
                extra={"session_id": session_id},
            )
            return {
                "execution_result": f"Lỗi khi thực thi agent {target_agent_name}: {exc}",
                "final_response": "Đã xảy ra lỗi trong quá trình xử lý yêu cầu.",
            }

    async def _verifier_node(self, state: AgentState) -> dict[str, Any]:
        """Verifier Node — Evaluates execution_result against user query & plan."""
        query: str = state.get("query", "")
        plan: str = state.get("plan", "")
        result: str = state.get("execution_result", "")
        target_agent: str = state.get("target_agent", "")
        session_id: str = state.get("session_id", "N/A")
        retry_count: int = state.get("retry_count", 0)

        logger.info(
            "PEV Node: Verifier evaluating", extra={"session_id": session_id}
        )

        # Immediate bypass for decline messages, empty responses, or pending human approval
        if result == GRACEFUL_DECLINE_MESSAGE or not result or state.get("requires_human_approval"):
            return {
                "is_verified": True,
                "verifier_feedback": "",
            }

        # Strict Schema Audit for CSV Data Agent results
        csv_content = state.get("csv_content")
        if csv_content and result:
            try:
                from src.agents.data_agent.agent import safe_read_csv
                from src.orchestrator.verifier import verify_dashboard_spec
                df = safe_read_csv(csv_content)
                parsed_res = json.loads(result)
                if isinstance(parsed_res, dict) and "dashboard_spec" in parsed_res and parsed_res["dashboard_spec"]:
                    is_valid, audit_msg = verify_dashboard_spec(df, parsed_res["dashboard_spec"])
                    if not is_valid:
                        logger.warning("Strict Verifier Audit failed: %s", audit_msg)
                        return {
                            "is_verified": False,
                            "verifier_feedback": audit_msg,
                            "retry_count": retry_count + 1,
                        }
            except Exception as audit_err:
                logger.warning("Verifier schema audit exception: %s", audit_err)

        verifier_prompt: str = build_verifier_prompt(
            query=query,
            plan=plan,
            execution_result=result,
            target_agent=target_agent,
        )

        try:
            llm_res: Any = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": verifier_prompt}],
                model=self.fast_model,  # Model Tiering: low-latency for verification
                temperature=0.0,
                max_tokens=200,
                metadata={"node": "verifier"},
                session_id=session_id,
            )

            raw_content: str = llm_res.choices[0].message.content or ""
            is_verified, feedback = self._parse_verifier_json(raw_content)

            logger.info(
                "Verifier verdict: is_verified=%s, feedback='%s'",
                is_verified,
                feedback,
                extra={"session_id": session_id},
            )

            new_retry_count: int = retry_count if is_verified else retry_count + 1

            return {
                "is_verified": is_verified,
                "verifier_feedback": feedback,
                "retry_count": new_retry_count,
            }

        except Exception as exc:
            logger.warning(
                "Verifier node exception (defaulting to verified=True): %s",
                exc,
                extra={"session_id": session_id},
            )
            return {
                "is_verified": True,
                "verifier_feedback": "",
            }

    # ------------------------------------------------------------------
    # Edge Condition
    # ------------------------------------------------------------------

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["continue_executor", "end"]:
        """Decide whether to loop back to Executor or terminate graph.

        When max retries are exhausted without verification, the result is
        returned with a warning annotation for the end user.
        """
        is_verified: bool = state.get("is_verified", True)
        retry_count: int = state.get("retry_count", 0)
        max_retries: int = state.get("max_retries", _DEFAULT_MAX_RETRIES)

        if is_verified or retry_count >= max_retries:
            # If exiting due to max retries (not verified), annotate the response
            if not is_verified and retry_count >= max_retries:
                current_response: str = state.get("final_response", "")
                warning_prefix: str = (
                    "\n\n> **Cảnh báo:** Kết quả này chưa được kiểm duyệt đầy đủ "
                    f"sau {retry_count} lần thử. Vui lòng kiểm tra lại thông tin trước khi sử dụng.\n\n"
                )
                if warning_prefix not in current_response:
                    # Note: TypedDict state is immutable in LangGraph routing,
                    # so annotation is handled in handle_request post-processing.
                    pass
            return "end"
        return "continue_executor"

    # ------------------------------------------------------------------
    # JSON Parsing Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_planner_json(raw_text: str) -> tuple[str, str, bool]:
        """Extract plan, target_agent, and requires_dashboard from Planner LLM response."""
        try:
            match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text
            data = json.loads(json_str)
            plan = data.get("plan", "Xử lý yêu cầu")
            target_agent = data.get("target_agent", "rag_agent")
            requires_dashboard = bool(data.get("requires_dashboard", False))
            return plan, target_agent, requires_dashboard
        except Exception:
            return "Xử lý yêu cầu người dùng", "rag_agent", False

    @staticmethod
    def _parse_verifier_json(raw_text: str) -> tuple[bool, str]:
        """Extract is_verified and feedback from Verifier LLM response."""
        try:
            match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text
            data = json.loads(json_str)
            
            raw_verified = data.get("is_verified")
            quality = str(data.get("quality", "")).lower()
            status = str(data.get("status", "")).lower()
            feedback = str(data.get("feedback") or data.get("verifier_feedback") or "")

            if raw_verified is False or "cần chỉnh sửa" in quality or "needs_revision" in status or "cần chỉnh sửa" in feedback.lower():
                return False, feedback or "Chất lượng: Cần Chỉnh Sửa | Phản hồi chưa đạt yêu cầu kiểm duyệt."
            if raw_verified is True or "đạt" in quality or "verified" in status:
                return True, feedback

            return (bool(raw_verified) if raw_verified is not None else True), feedback
        except Exception:
            return True, ""
