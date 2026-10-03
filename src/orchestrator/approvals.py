"""Human-in-the-Loop approvals: pending records (in-process + Redis, claimed exactly once) and the decision handler.

Mixed into ``Orchestrator`` (core.py); it expects ``self.pending_approvals``, ``self.redis_client``, ``self.settings`` and
``self.registry`` from there.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from src.shared import audit
from src.orchestrator.state import AgentState
from src.shared.auth import current_scope
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)


class ApprovalMixin:
    def _store_pending(self, action_id: str, state: AgentState, payload: dict[str, Any]) -> None:
        self._purge_expired_approvals()
        self.pending_approvals[action_id] = {"state": state, "payload": payload, "created_at": time.monotonic()}

    @staticmethod
    def _approval_key(action_id: str) -> str:
        return f"hitl:pending:{action_id}"

    async def _persist_pending(self, action_id: str) -> None:
        """Mirror a pending approval into Redis (TTL = the approval TTL). Only what approving needs is stored: the query
        and the payload, not the whole graph state (which can carry an uploaded file)."""
        client = getattr(self.redis_client, "client", None)
        record = self.pending_approvals.get(action_id)
        if record is not None:  # on the record from the moment it is asked for, whoever answers later
            asked = record["payload"]
            await audit.record("hitl.requested", action_id, "pending", {"agent": asked.get("agent"), "request": asked.get("payload")})
        if client is None or record is None:
            return
        state = record.get("state", {})
        shared = {"state": {k: state.get(k) for k in ("query", "session_id", "agent_mode", "target_agent")}, "payload": record["payload"]}
        try:
            await client.set(self._approval_key(action_id), json.dumps(shared, ensure_ascii=False, default=str), ex=int(self.settings.HITL_APPROVAL_TTL_SECONDS))
        except Exception as exc:  # noqa: BLE001 - the in-process copy still works on this instance
            logger.warning("Could not share pending approval %s through Redis: %s", action_id, exc or type(exc).__name__)

    async def _claim_pending(self, action_id: str, session_id: str) -> Optional[dict[str, Any]]:
        """The pending approval for this exact action and session, claimed so that only ONE caller (on any replica)
        can act on it; ``None`` when unknown, expired, already claimed or raised by another session."""
        self._purge_expired_approvals()
        record: Optional[dict[str, Any]] = self.pending_approvals.get(action_id)
        client = getattr(self.redis_client, "client", None)
        shared: Optional[dict[str, Any]] = None
        if client is not None:
            try:
                raw = await client.get(self._approval_key(action_id))
                shared = json.loads(raw) if raw else None
            except Exception as exc:  # noqa: BLE001 - fall back to this instance's own record
                logger.warning("Redis unavailable while looking up approval %s: %s", action_id, exc or type(exc).__name__)
                client = None
        record = record or shared
        if record and record.get("payload", {}).get("session_id") not in (None, session_id):
            return None  # bound to the session that raised it: a wrong session does not even consume it
        if record is None:
            return None
        if client is not None:
            try:
                if not await client.delete(self._approval_key(action_id)):  # somebody else claimed it first
                    self.pending_approvals.pop(action_id, None)
                    return None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not claim approval %s in Redis: %s", action_id, exc or type(exc).__name__)
        self.pending_approvals.pop(action_id, None)
        return record

    def _purge_expired_approvals(self) -> None:
        """Drop approvals nobody answered within HITL_APPROVAL_TTL_SECONDS (bounds memory, expires stale risk)."""
        ttl = float(self.settings.HITL_APPROVAL_TTL_SECONDS)
        now = time.monotonic()
        for act_id, rec in list(self.pending_approvals.items()):
            if now - rec.get("created_at", now) > ttl:
                self.pending_approvals.pop(act_id, None)

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

        decision = (decision or "").strip().lower()
        if decision not in ("approve", "reject"):
            return {
                "status": "error",
                "action_id": action_id,
                "message": msg("orch.invalid_decision", decision=decision),
            }

        # An approval is bound to the exact action AND the session that raised it:
        # no "closest match by session" fallback, no cross-session approval.
        record = await self._claim_pending(action_id, session_id)

        if not record:
            return {
                "status": "error",
                "action_id": action_id,
                "message": msg("orch.approval_missing", action_id=action_id),
            }

        saved_state: AgentState = record.get("state", {})
        payload: dict[str, Any] = record.get("payload", {})
        agent_name: str = payload.get("agent", "")

        if decision == "reject":
            reject_msg = msg("orch.rejected_by_admin", action_id=action_id, reason=feedback or msg("orch.cancelled_request"))
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
                "message": msg("orch.agent_missing", agent=agent_name),
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
                exec_summary = msg(
                    "orch.api_done", method=method, url=url, status=status_code,
                    data=json.dumps(data, ensure_ascii=False, indent=2),
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
                tenant_id, department_id = current_scope()  # the approver's own tenant/department
                secured_sql = inject_row_level_security(sql, tenant_id=tenant_id, department_id=department_id)
                mcp_res = await agent.mcp_client.execute_sql_query(
                    query_sql=secured_sql, session_id=session_id
                )
                try:
                    res_dict = json.loads(mcp_res)
                except Exception:
                    res_dict = {"status": "success", "data": mcp_res}

                data = res_dict.get("data", [])
                exec_summary = msg(
                    "orch.sql_done", sql=secured_sql, rows=len(data),
                    data=json.dumps(data, ensure_ascii=False, indent=2),
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
                "message": msg("orch.exec_failed", error=exec_err),
            }
