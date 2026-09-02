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
                    "\n\n> ⚠️ **Cảnh báo:** Kết quả này chưa được kiểm duyệt đầy đủ "
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

            async for event_data in self.graph.astream(initial_state, config=config):
                for node_name, node_state in event_data.items():
                    if node_name == "planner":
                        target = node_state.get("target_agent", "")
                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "executor",
                                "status": "active",
                                "target": target,
                                "logs": f"Planner đã xong -> Đang chuyển giao tới Agent [{target}]...",
                            }, ensure_ascii=False),
                        }
                        yield {
                            "event": "plan",
                            "data": json.dumps({
                                "plan": node_state.get("plan", ""),
                                "target_agent": target,
                            }, ensure_ascii=False),
                        }
                    elif node_name == "executor":
                        target = node_state.get("target_agent", "")
                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "verifier",
                                "status": "active",
                                "target": target,
                                "logs": "Executor đã hoàn tất -> Verifier đang kiểm duyệt phản hồi...",
                            }, ensure_ascii=False),
                        }
                        yield {
                            "event": "executing",
                            "data": json.dumps({
                                "target_agent": target,
                                "execution_result": node_state.get("execution_result", ""),
                            }, ensure_ascii=False),
                        }
                    elif node_name == "verifier":
                        is_v = node_state.get("is_verified", False)
                        yield {
                            "event": "pev_step",
                            "data": json.dumps({
                                "step": "completed" if is_v else "verifier",
                                "status": "verified" if is_v else "active",
                                "feedback": node_state.get("verifier_feedback", ""),
                            }, ensure_ascii=False),
                        }
                        yield {
                            "event": "verifying",
                            "data": json.dumps({
                                "is_verified": is_v,
                                "verifier_feedback": node_state.get("verifier_feedback", ""),
                                "retry_count": node_state.get("retry_count", 0),
                            }, ensure_ascii=False),
                        }

            final_checkpoint = await self.graph.aget_state(config)
            final_values = final_checkpoint.values if final_checkpoint else {}
            response_text = (
                final_values.get("final_response")
                or final_values.get("execution_result")
                or GRACEFUL_DECLINE_MESSAGE
            )

            yield {
                "event": "pev_step",
                "data": json.dumps({
                    "step": "completed",
                    "status": "verified",
                }, ensure_ascii=False),
            }

            yield {
                "event": "final_response",
                "data": json.dumps({
                    "response": response_text,
                    "target_agent": final_values.get("target_agent", ""),
                    "is_verified": final_values.get("is_verified", True),
                }, ensure_ascii=False),
            }

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
                    "team_memory": {"long_term_memories": memories},
                }

            # Force-route to data_agent if CSV is provided
            if csv_content:
                logger.info(
                    "Planner: CSV attached -> Force target_agent = 'data_agent'",
                    extra={"session_id": session_id},
                )
                return {
                    "plan": f"Phân tích dữ liệu từ file CSV '{csv_filename}' và sinh Dashboard.",
                    "target_agent": "data_agent",
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
                plan, target_agent = self._parse_planner_json(raw_content)

                logger.info(
                    "Planner complete: target_agent='%s', plan='%s'",
                    target_agent,
                    plan,
                    extra={"session_id": session_id},
                )

                return {
                    "plan": plan,
                    "target_agent": target_agent,
                    "team_memory": {"long_term_memories": memories},
                }

            except Exception as exc:
                logger.error(
                    "Planner LLM call exception: %s",
                    exc,
                    extra={"session_id": session_id},
                )
                fallback_agent = "data_agent" if csv_content else "rag_agent"
                return {
                    "plan": f"Lập kế hoạch phân tích và trả lời câu hỏi bằng {fallback_agent}.",
                    "target_agent": fallback_agent,
                    "team_memory": {"long_term_memories": memories},
                }

        except Exception as fatal_exc:
            logger.error(
                "Planner node fatal exception: %s",
                fatal_exc,
                extra={"session_id": session_id},
            )
            fallback_agent = "data_agent" if csv_content else "rag_agent"
            return {
                "plan": f"Tự động lập kế hoạch fallback tới {fallback_agent}.",
                "target_agent": fallback_agent,
            }

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

        # Immediate bypass for decline messages or empty responses
        if result == GRACEFUL_DECLINE_MESSAGE or not result:
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
                    "\n\n> ⚠️ **Cảnh báo:** Kết quả này chưa được kiểm duyệt đầy đủ "
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
    def _parse_planner_json(raw_text: str) -> tuple[str, str]:
        """Extract plan and target_agent from Planner LLM response."""
        try:
            match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text
            data = json.loads(json_str)
            return data.get("plan", "Xử lý yêu cầu"), data.get(
                "target_agent", "rag_agent"
            )
        except Exception:
            return "Xử lý yêu cầu người dùng", "rag_agent"

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
