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

No checkpointer: every request builds its whole state from scratch and nothing reads a saved one back, while ``MemorySaver``
kept every checkpoint (CSV contents included) of every session in RAM forever. Conversation context lives in Redis history.
"""

import asyncio
import inspect
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncGenerator, Literal, Optional

from langgraph.graph import END, StateGraph

from src.agents.base_agent import BaseAgent
from src.config import Settings
from src.orchestrator.prompt_templates import (
    GRACEFUL_DECLINE_MESSAGE,
    build_planner_prompt,
    build_verifier_prompt,
)
from src.orchestrator.approvals import ApprovalMixin
from src.orchestrator.common import _DEFAULT_MAX_RETRIES, _build_pev_trace, _initial_state  # noqa: F401  (re-exported: tests and callers import them from here)
from src.orchestrator.state import AgentState
from src.orchestrator.streaming import StreamingMixin
from src.registry.manager import AgentRegistry
from src.shared import answer_stream
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.intents import is_dashboard_request as _is_dashboard_request
from src.shared.memory_manager import MemoryManager
from src.shared.auth import current_scope, memory_user_id
from src.shared.security import unwrap_user_input

logger: logging.Logger = get_logger(__name__)

# Default max retries for Verifier rejection

# mem0 does an LLM/embedding round trip per call
_MEMORY_WRITE_TIMEOUT: float = 30.0
_MEMORY_READ_TIMEOUT: float = 5.0  # the planner waits for this one, so keep it short

_AUTO_MODES: tuple[str, ...] = ("auto", "all agents", "all_agents", "none", "")
# UI mode string -> agent, first substring match wins
_FORCED_ROUTES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("rag",), "rag_agent"),
    (("search",), "search_agent"),
    (("data",), "data_agent"),
    (("db", "database", "sql"), "db_agent"),
    (("integration", "api"), "integration_agent"),
)
_FORCED_PLANS: dict[str, str] = {
    "rag_agent": "Tra cứu và trích xuất tài liệu nội bộ để trả lời câu hỏi: '{query}'.",
    "search_agent": "Tìm kiếm thông tin trên Internet thời gian thực về: '{query}'.",
    "db_agent": "Truy vấn cơ sở dữ liệu quan hệ PostgreSQL để trả lời: '{query}'.",
    "integration_agent": "Kết nối và gọi API dịch vụ ngoài để xử lý: '{query}'.",
}




class Orchestrator(ApprovalMixin, StreamingMixin):
    """Enterprise Autonomous Orchestrator running on LangGraph PEV State Machine.

    Attributes:
        registry: The ``AgentRegistry`` containing all available agents.
        settings: Application settings.
        llm_client: Centralised ``LLMClient`` for LLM operations.
        memory_manager: Long-term ``MemoryManager`` instance.
        model: Model identifier.
        graph: Compiled LangGraph runnable workflow.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        settings: Settings,
        llm_client: Optional[LLMClient] = None,
        memory_manager: Optional[MemoryManager] = None,
        redis_client: Optional[Any] = None,
    ) -> None:
        """Initialise the LangGraph Orchestrator.

        Args:
            registry: Agent registry containing registered agent instances.
            settings: Application settings.
            llm_client: Centralised LLM client (optional).
            memory_manager: Long-term memory manager (optional).
            redis_client: When given, pending Human-in-the-Loop approvals are also kept in Redis, so they survive a
                restart and can be approved on any replica (the in-process dict stays as the fast path / fallback).
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
        self.redis_client: Optional[Any] = redis_client
        self._background_tasks: set[asyncio.Task[None]] = set()  # strong refs: the loop only keeps weak ones

        # --------------------------------------------------------------
        # LangGraph StateGraph Construction
        # --------------------------------------------------------------
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

        self.graph: Any = workflow.compile()

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
        target_agent: str | None = None,
    ) -> str:
        """Route a user request through the LangGraph PEV workflow.

        Args:
            query: The end-user's natural-language question.
            session_id: Correlation ID for end-to-end tracing.
            csv_content: Optional raw CSV file content.
            csv_filename: Optional original filename of the uploaded CSV.
            agent_mode: Optional explicit mode identifier (e.g. 'search_agent').
            target_agent: Optional explicit target agent (e.g. 'rag_agent').

        Returns:
            str: Final response from the PEV state machine.
        """
        logger.info(
            "LangGraph Orchestrator received request (query_len=%d, has_csv=%s, mode=%s, target_agent=%s)",
            len(query),
            bool(csv_content),
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
                logger.warning(
                    "PEV Loop: Max retries exhausted (retries=%d, verified=%s) — returning raw result with warning",
                    retry_count, is_verified,
                    extra={"session_id": session_id},
                )
                response_text = self._annotate_unverified(response_text, retry_count)

            pev_trace = _build_pev_trace(target_agent, plan, is_verified, verifier_fb)

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

            self._remember_in_background(session_id, query)
            return response_text

        except Exception as exc:
            logger.error(
                "LangGraph execution error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return msg("orch.pev_error")
        finally:
            if self.llm_client:
                await self.llm_client.flush_async()

    async def _memory_call(self, fn: Any, *args: Any, timeout: float, **kwargs: Any) -> Any:
        """Run a ``MemoryManager`` call in a worker thread. mem0 is synchronous (each call makes LLM/embedding requests
        that take seconds): run inline it freezes the whole event loop, and ``wait_for`` cannot interrupt it."""
        result = await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout)
        if inspect.isawaitable(result) and not isinstance(result, (list, dict)):  # async fakes; the real Dual* types are plain containers
            result = await result
        return result

    def _remember_in_background(self, session_id: str, query: str) -> None:
        """Long-term memory extraction calls an LLM; the user must never wait for it (or for its retries).

        The text is what the user actually wrote (the gateway's nonce wrapper removed): mem0 extracts facts and
        preferences from it, and extracts nothing from routing logs.
        """
        text: str = unwrap_user_input(query)[0]
        owner: str = memory_user_id(session_id)  # resolved now, in the request's context

        async def store() -> None:
            try:
                await self._memory_call(self.memory_manager.add_memory, user_id=owner, text=text, timeout=_MEMORY_WRITE_TIMEOUT)
            except Exception as mem_err:  # noqa: BLE001 - personalisation is best effort
                logger.warning("Failed to store memory: %s", mem_err or type(mem_err).__name__, extra={"session_id": session_id})

        task = asyncio.get_running_loop().create_task(store())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _determine_fallback_route(
        self, query: str, csv_content: Optional[str] = None
    ) -> tuple[str, str, bool]:
        """Tự động phân luồng an toàn dựa trên từ khóa truy vấn của người dùng khi Planner LLM gặp sự cố."""
        q_lower = (query or "").lower()

        # 1. File CSV đính kèm
        if csv_content:
            is_viz = _is_dashboard_request(query)
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
                memories = await self._memory_call(
                    self.memory_manager.get_relevant_memories,
                    user_id=memory_user_id(session_id), query=unwrap_user_input(query)[0], limit=3, timeout=_MEMORY_READ_TIMEOUT,
                )
            except Exception as mem_err:
                logger.warning("Planner memory retrieval exception: %s", mem_err, extra={"session_id": session_id})

            memory_str: str = "\n".join(f"- {m}" for m in memories) if memories else "None"

            # Forced agent (UI mode) has absolute priority over LLM routing
            forced_agent: Optional[str] = (
                state.get("forced_target_agent")
                or state.get("target_agent")
                or state.get("agent_mode")
            )
            fa_norm = (forced_agent or "").strip().lower()
            if fa_norm not in _AUTO_MODES:
                chosen_agent = next(
                    (agent for keys, agent in _FORCED_ROUTES if any(k in fa_norm for k in keys)),
                    forced_agent,
                )
                logger.info(
                    "Planner: Mode forced by user -> Target agent = '%s' (bypassing LLM classification)",
                    chosen_agent,
                    extra={"session_id": session_id},
                )
                is_viz = chosen_agent == "data_agent" and _is_dashboard_request(query)
                if chosen_agent == "data_agent":
                    plan = f"Phân tích dữ liệu tệp CSV và {'trực quan hóa qua Dashboard' if is_viz else 'tóm tắt kết quả'}."
                else:
                    plan = _FORCED_PLANS.get(chosen_agent, "Thực thi yêu cầu với {agent}: '{query}'.").format(
                        agent=chosen_agent, query=query
                    )
                return {
                    "plan": plan,
                    "target_agent": chosen_agent,
                    "requires_dashboard": is_viz,
                    "team_memory": {"long_term_memories": memories},
                }

            # Force-route to data_agent if CSV is provided with intent-aware dashboard check
            if csv_content:
                query_lower = query.lower()
                is_viz = _is_dashboard_request(query)
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

            with answer_stream.suspended():  # sub-answers are merged by the synthesis below: none of them is "the answer" to preview
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
                reject_msg = msg("orch.api_rejected", reason=human_feedback or msg("orch.cancelled_command"))
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
                        "description": explanation or msg("orch.api_desc", method=method, url=url),
                        "payload": {
                            "url": url,
                            "method": method,
                            "payload": payload,
                        },
                        "risk_level": "high",
                    }
                    self._store_pending(action_id, state, approval_payload)
                    await self._persist_pending(action_id)
                    logger.warning(
                        "HITL Gate Triggered: Integration mutating request '%s %s' paused for approval (action_id=%s)",
                        method, url, action_id,
                        extra={"session_id": session_id},
                    )
                    pause_res = json.dumps({
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "message": msg("orch.api_needs_approval"),
                    }, ensure_ascii=False)
                    return {
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "action_id": action_id,
                        "execution_result": pause_res,
                        "final_response": msg("orch.api_needs_approval"),
                    }

        # 2b. Database Agent: Sensitive table/column queries require human approval
        elif target_agent_name == "db_agent":
            if is_approved is False:
                reject_msg = msg("orch.sql_rejected", reason=human_feedback or msg("orch.cancelled_command"))
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
                        "description": explanation or msg("orch.sql_desc"),
                        "payload": {
                            "sql": sql_preview,
                            "query": exec_query,
                        },
                        "risk_level": "critical",
                    }
                    self._store_pending(action_id, state, approval_payload)
                    await self._persist_pending(action_id)
                    logger.warning(
                        "HITL Gate Triggered: Sensitive SQL query paused for approval (action_id=%s): %s",
                        action_id, sql_preview[:80],
                        extra={"session_id": session_id},
                    )
                    pause_res = json.dumps({
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "message": msg("orch.sql_needs_approval"),
                    }, ensure_ascii=False)
                    return {
                        "requires_human_approval": True,
                        "approval_payload": approval_payload,
                        "action_id": action_id,
                        "execution_result": pause_res,
                        "final_response": msg("orch.sql_needs_approval"),
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

    @staticmethod
    def _rag_verdict(verification: dict[str, Any], retry_count: int, require_quotes: bool = False) -> dict[str, Any]:
        """Verdict on a RAG answer from the agent's own checks: it must cite sources and use only numbers that
        appear in them. "Nothing found" is a valid answer; a retrieval error is worth one more try."""
        status = verification.get("status")
        if status == "not_found":
            return {"is_verified": True, "verifier_feedback": ""}
        problems: list[str] = []
        if status == "error":
            problems.append("không truy xuất được tài liệu")
        else:
            if not verification.get("grounded"):
                problems.append("câu trả lời chưa trích dẫn nguồn dạng [n]")
            if verification.get("unsupported_numbers"):
                problems.append("các con số " + ", ".join(map(str, verification["unsupported_numbers"])) + " không có trong nguồn")
            if require_quotes and verification.get("unquoted_citations"):
                problems.append("các trích dẫn " + ", ".join(f"[{n}]" for n in verification["unquoted_citations"]) + " chưa kèm đoạn trích nguyên văn đúng trong nguồn")
        if not problems:
            return {"is_verified": True, "verifier_feedback": ""}
        feedback = "; ".join(problems) + ". Chỉ dùng thông tin và con số có trong nguồn và luôn trích dẫn [n]."
        return {"is_verified": False, "verifier_feedback": feedback, "retry_count": retry_count + 1}

    @staticmethod
    def _db_verdict(parsed: dict[str, Any], retry_count: int) -> dict[str, Any]:
        """Deterministic check on a db_agent answer: every number in its prose must come from the rows it returned,
        the row count or the SQL itself (``LIMIT 5``, ``2024``). The LLM judge still runs after it (does the SQL
        answer the question?); this only stops invented figures. Nothing to check when no rows came back."""
        from src.agents.data_agent.grounding import _walk, extract_numbers, numbers_grounded

        rows = parsed.get("data")
        if not isinstance(rows, list) or not rows:
            return {"is_verified": True, "verifier_feedback": ""}
        sql = str(parsed.get("sql") or "")
        prose = str(parsed.get("answer") or "").replace(f"`{sql}`", " ")
        numbers: list[float] = [float(parsed["row_count"])] if isinstance(parsed.get("row_count"), (int, float)) else []
        strings: list[str] = []
        _walk(rows, numbers, strings)
        numbers += [value for value, _, _ in extract_numbers(sql)]
        ok, unmatched = numbers_grounded(prose, [], extra_numbers=numbers, extra_strings=strings, literals=())
        if ok:
            return {"is_verified": True, "verifier_feedback": ""}
        feedback = "các con số " + ", ".join(unmatched) + " không có trong kết quả truy vấn. Chỉ nêu số có trong dữ liệu trả về."
        return {"is_verified": False, "verifier_feedback": feedback, "retry_count": retry_count + 1}

    @staticmethod
    def _annotate_unverified(response_text: str, retries: int) -> str:
        """Warn that a result never passed verification without breaking JSON payloads (answer + sources,
        dashboard spec): the note goes into the human-readable field, plain text just gets it prepended."""
        marker = "chưa được kiểm duyệt đầy đủ"
        note = f"> **Cảnh báo:** Kết quả này {marker} sau {retries} lần thử. Vui lòng kiểm tra lại thông tin trước khi sử dụng."
        if marker in response_text:
            return response_text
        try:
            parsed = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            return f"\n\n{note}\n\n{response_text}"
        if isinstance(parsed, dict):
            for key in ("answer", "explanation", "content"):
                if isinstance(parsed.get(key), str):
                    parsed[key] = f"{note}\n\n{parsed[key]}"
                    break
            else:
                parsed["warning"] = note
            parsed["unverified"] = True
            return json.dumps(parsed, ensure_ascii=False)
        return f"\n\n{note}\n\n{response_text}"

    @staticmethod
    def _audit_dashboard(csv_content: Optional[str], parsed: dict[str, Any], retry_count: int) -> Optional[dict[str, Any]]:
        """Recompute the dashboard from the uploaded file (never from rows the agent shipped: a spec cannot
        vouch for its own data). Returns a verifier-node update, or ``None`` when there is nothing to audit
        against."""
        from src.agents.data_agent.ingest import safe_read_csv
        from src.orchestrator.verifier import auto_remediate_chart_specs, verify_dashboard_spec

        spec = parsed["dashboard_spec"]
        if not csv_content:  # follow-up restored from the session cache: the agent's inline verification is the evidence
            trace = parsed.get("pev_trace") or {}
            verified = bool(trace.get("is_verified", True))
            return {"is_verified": verified, "verifier_feedback": "" if verified else "; ".join(trace.get("error_feedback", []))}
        df = safe_read_csv(csv_content)
        if df.empty:
            return None
        is_valid, audit_msg = verify_dashboard_spec(df, spec)
        if is_valid:
            return {"is_verified": True, "verifier_feedback": ""}
        if retry_count >= 1:  # deterministic repair before giving up (avoids tripping the circuit breaker)
            repaired = auto_remediate_chart_specs(df, spec)
            if verify_dashboard_spec(df, repaired)[0]:
                parsed["dashboard_spec"] = repaired
                new_result = json.dumps(parsed, ensure_ascii=False)
                return {"execution_result": new_result, "final_response": new_result, "is_verified": True, "verifier_feedback": "", "retry_count": retry_count}
        logger.warning("Strict Verifier Audit failed: %s", audit_msg)
        return {"is_verified": False, "verifier_feedback": audit_msg, "retry_count": retry_count + 1}

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

        # Strict schema audit for data-agent results: deterministic, so no LLM judge is needed once it passes.
        csv_content = state.get("csv_content")
        try:
            parsed_res = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            parsed_res = None
        if isinstance(parsed_res, dict) and parsed_res.get("type") == "error":
            return {"is_verified": True, "verifier_feedback": ""}  # a clear user-facing error is the correct answer
        if isinstance(parsed_res, dict) and isinstance(parsed_res.get("verification"), dict):
            return self._rag_verdict(parsed_res["verification"], retry_count, bool(getattr(self.settings, "RAG_REQUIRE_QUOTES", False)))  # deterministic: no LLM judge
        if isinstance(parsed_res, dict) and "sql" in parsed_res and isinstance(parsed_res.get("data"), list):  # db_agent
            db_verdict = self._db_verdict(parsed_res, retry_count)
            if not db_verdict["is_verified"]:  # invented figures: no point asking the judge, retry with the feedback
                return db_verdict
        if isinstance(parsed_res, dict) and parsed_res.get("dashboard_spec"):
            try:
                verdict = await asyncio.to_thread(self._audit_dashboard, csv_content, parsed_res, retry_count)
            except Exception as audit_err:  # noqa: BLE001 - an audit crash must not block the answer
                logger.warning("Verifier schema audit exception: %s", audit_err, extra={"session_id": session_id})
                verdict = None
            if verdict is not None:
                logger.info("Strict audit verdict: is_verified=%s", verdict.get("is_verified"), extra={"session_id": session_id})
                return verdict

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

        # Warning annotation on exhausted retries is applied in handle_request / handle_stream_request
        # (routing functions cannot mutate LangGraph state).
        return "end" if is_verified or retry_count >= max_retries else "continue_executor"

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
