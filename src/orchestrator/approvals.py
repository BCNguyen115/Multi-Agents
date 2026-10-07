"""Human-in-the-Loop approvals: pending records (in-process + Redis, claimed exactly once) and the decision handler.

Mixed into ``Orchestrator`` (core.py); it expects ``self.pending_approvals``, ``self.redis_client``, ``self.settings`` and
``self.registry`` from there.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import nullcontext
from typing import Any, Optional

from src.shared import audit
from src.orchestrator.state import AgentState
from src.config import settings as global_settings
from src.shared.auth import Principal, acting_as, current_principal, current_scope
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)


class ApprovalMixin:
    def _store_pending(self, action_id: str, state: AgentState, payload: dict[str, Any]) -> None:
        self._purge_expired_approvals()
        who = current_principal()
        if who is not None and who.authenticated:  # who asked: a second approver needs it, and the result goes back to them
            payload = {**payload, "requester": {"user": who.user_id, "tenant": who.tenant_id, "department": who.department_id}}
        self.pending_approvals[action_id] = {"state": state, "payload": payload, "created_at": time.monotonic(), "created_wall": time.time()}

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
        shared = {
            "state": {k: state.get(k) for k in ("query", "session_id", "agent_mode", "target_agent")},
            "payload": record["payload"],
            "created_wall": record.get("created_wall"),
        }
        try:
            await client.set(self._approval_key(action_id), json.dumps(shared, ensure_ascii=False, default=str), ex=int(self.settings.HITL_APPROVAL_TTL_SECONDS))
        except Exception as exc:  # noqa: BLE001 - the in-process copy still works on this instance
            logger.warning("Could not share pending approval %s through Redis: %s", action_id, exc or type(exc).__name__)

    async def _claim_pending(self, action_id: str, session_id: str, ignore_session: bool = False) -> Optional[dict[str, Any]]:
        """The pending approval for this exact action and session, claimed so that only ONE caller (on any replica)
        can act on it; ``None`` when unknown, expired, already claimed or raised by another session.
        ``ignore_session``: a second approver (two-person approval) acts on somebody else's request; the caller has checked who."""
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
        if not ignore_session and record and record.get("payload", {}).get("session_id") not in (None, session_id):
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

    async def _peek_pending(self, action_id: str) -> Optional[dict[str, Any]]:
        """The pending record WITHOUT claiming it (in-process first, then Redis); ``None`` when unknown."""
        record = self.pending_approvals.get(action_id)
        if record is not None:
            return record
        client = getattr(self.redis_client, "client", None)
        if client is None:
            return None
        try:
            raw = await client.get(self._approval_key(action_id))
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis unavailable while reading approval %s: %s", action_id, exc or type(exc).__name__)
            return None

    async def list_pending_approvals(self, principal: Principal) -> list[dict[str, Any]]:
        """What this approver may decide: other people's pending requests in their tenant (two-person approval only).
        Request details are shown (that is what is being approved); no result of any earlier action is."""
        if not global_settings.HITL_REQUIRE_OTHER_APPROVER or not principal.can_approve:
            return []
        self._purge_expired_approvals()
        ttl = float(self.settings.HITL_APPROVAL_TTL_SECONDS)
        found: dict[str, tuple[dict[str, Any], float]] = {}
        client = getattr(self.redis_client, "client", None)
        if client is not None:
            try:
                async for key in client.scan_iter(match="hitl:pending:*", count=100):
                    action_id = str(key).split(":", 2)[-1]
                    raw = await client.get(key)
                    if raw:
                        found[action_id] = (json.loads(raw), max(float(await client.ttl(key)), 0.0))
                    if len(found) >= 100:
                        break
            except Exception as exc:  # noqa: BLE001 - the in-process records below still answer for this replica
                logger.warning("Could not list pending approvals in Redis: %s", exc or type(exc).__name__)
        now = time.monotonic()
        for action_id, record in self.pending_approvals.items():
            found.setdefault(action_id, (record, max(ttl - (now - record.get("created_at", now)), 0.0)))
        items: list[dict[str, Any]] = []
        for action_id, (record, left) in found.items():
            payload = record.get("payload") or {}
            requester = payload.get("requester") or {}
            if requester.get("tenant") != principal.tenant_id or requester.get("user") == principal.user_id:
                continue
            items.append({
                "action_id": action_id, "agent": payload.get("agent"), "action_type": payload.get("action_type"),
                "description": payload.get("description"), "risk_level": payload.get("risk_level"),
                "request": payload.get("payload"), "requested_by": requester.get("user"), "expires_in": int(left),
            })
        return sorted(items, key=lambda i: i["expires_in"])

    @staticmethod
    def _result_key(action_id: str) -> str:
        return f"hitl:result:{action_id}"

    async def _store_result(self, action_id: str, requester: dict[str, str], result: dict[str, Any]) -> None:
        """Keep the outcome of an action somebody else approved, for the requester to collect (TTL = the approval TTL)."""
        record = {"requester": requester, "result": result, "at": time.time()}
        self.__dict__.setdefault("approval_results", {})[action_id] = {**record, "mono": time.monotonic()}
        client = getattr(self.redis_client, "client", None)
        if client is None:
            return
        try:
            await client.set(self._result_key(action_id), json.dumps(record, ensure_ascii=False, default=str), ex=int(self.settings.HITL_APPROVAL_TTL_SECONDS))
        except Exception as exc:  # noqa: BLE001 - the in-process copy still serves this replica
            logger.warning("Could not store the approval result %s: %s", action_id, exc or type(exc).__name__)

    async def approval_result(self, action_id: str, principal: Principal) -> Optional[dict[str, Any]]:
        """For the REQUESTER only: ``{"state": "done", "result": ...}``, ``{"state": "pending"}`` while nobody has decided, ``None`` when it
        is unknown, expired or somebody else's (indistinguishable on purpose)."""
        def mine(requester: dict[str, Any]) -> bool:
            return requester.get("user") == principal.user_id and requester.get("tenant") == principal.tenant_id

        ttl = float(self.settings.HITL_APPROVAL_TTL_SECONDS)
        local = self.__dict__.get("approval_results", {}).get(action_id)
        if local is not None and time.monotonic() - local["mono"] <= ttl:
            return {"state": "done", "result": local["result"]} if mine(local["requester"]) else None
        client = getattr(self.redis_client, "client", None)
        if client is not None:
            try:
                raw = await client.get(self._result_key(action_id))
                if raw:
                    record = json.loads(raw)
                    return {"state": "done", "result": record["result"]} if mine(record["requester"]) else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read the approval result %s: %s", action_id, exc or type(exc).__name__)
        pending = await self._peek_pending(action_id)
        if pending is not None and mine((pending.get("payload") or {}).get("requester") or {}):
            return {"state": "pending"}
        return None

    async def handle_approval_decision(
        self,
        session_id: str,
        action_id: str,
        decision: str,
        feedback: Optional[str] = None,
        approver: Optional[Principal] = None,
    ) -> dict[str, Any]:
        """Decide a pending action. With ``HITL_REQUIRE_OTHER_APPROVER`` the approver must be someone other than the requester
        (same tenant); the action then runs in the REQUESTER's scope and its result is stored for the requester, not returned."""
        record = await self._peek_pending(action_id)
        requester: Optional[dict[str, str]] = ((record or {}).get("payload") or {}).get("requester")
        cross = False
        if global_settings.HITL_REQUIRE_OTHER_APPROVER and approver is not None and approver.authenticated and requester:
            if requester.get("user") == approver.user_id:
                return {"status": "error", "code": "self_approval", "action_id": action_id, "message": msg("forbidden.self_approval")}
            if requester.get("tenant") != approver.tenant_id:  # another tenant's request: indistinguishable from an unknown one
                return {"status": "error", "action_id": action_id, "message": msg("orch.approval_missing", action_id=action_id)}
            cross = True
        claimed = {"value": False}
        scope = Principal(requester["user"], requester["tenant"], requester["department"], frozenset(), authenticated=True) if cross and requester else None
        with acting_as(scope) if scope is not None else nullcontext():
            result = await self._decide(session_id, action_id, decision, feedback, requester if cross else None, cross, claimed)
        if claimed["value"]:
            await audit.record(
                "hitl.outcome", action_id, str(result.get("status", "")),
                {"requester": (requester or {}).get("user"), "cross_approval": cross},
            )
        if cross and claimed["value"] and requester:
            await self._store_result(action_id, requester, result)
            return {"status": "delivered", "action_id": action_id, "decision": (decision or "").strip().lower(), "message": msg("orch.delivered_to_requester")}
        return result

    async def _decide(
        self,
        session_id: str,
        action_id: str,
        decision: str,
        feedback: Optional[str],
        requester: Optional[dict[str, str]],
        cross: bool,
        claimed: dict[str, bool],
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
        record = await self._claim_pending(action_id, session_id, ignore_session=cross)

        if not record:
            return {
                "status": "error",
                "action_id": action_id,
                "message": msg("orch.approval_missing", action_id=action_id),
            }

        claimed["value"] = True
        saved_state: AgentState = record.get("state", {})
        payload: dict[str, Any] = record.get("payload", {})
        session_id = payload.get("session_id") or session_id  # the REQUESTER's session (the same one, unless somebody else approves)
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
                tenant_id, department_id = (requester["tenant"], requester["department"]) if requester else current_scope()  # whose data this is
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
