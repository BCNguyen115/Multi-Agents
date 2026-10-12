"""Long-term memory the user can see and control: what is worth storing, who may delete what, and what the answering agents get to see."""
import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.config import settings
from src.gateway.memory import router
from src.shared import user_context
from src.shared.auth import Principal, authenticate
from src.shared.memory_manager import MemoryManager, worth_remembering


def fallback_manager() -> MemoryManager:
    """A manager with no mem0 behind it: the in-process store, which has the same list / delete contract."""
    manager = MemoryManager.__new__(MemoryManager)
    manager.enabled, manager.mem0_client, manager._fallback_store = True, None, {}
    return manager


def test_only_a_message_that_says_something_about_the_person_is_worth_extracting():
    for text in ("Tôi là kế toán trưởng", "hãy nhớ rằng tôi thích câu trả lời ngắn", "My name is Lan", "from now on answer in English", "Please always cite the page"):
        assert worth_remembering(text), text
    for text in ("Thời hạn NDA là bao lâu?", "doanh thu quý 2 là bao nhiêu", "what is the refund policy"):
        assert not worth_remembering(text), text
    assert worth_remembering("Thời hạn NDA?", "all") and not worth_remembering("Tôi là Lan", "off")


def test_nobody_can_delete_another_persons_memory_even_with_its_id():
    manager = fallback_manager()
    manager.add_memory(user_id="acme:alice", text="Alice thích bảng tóm tắt")
    manager.add_memory(user_id="acme:bob", text="Bob dùng tiếng Anh")
    alice_item = manager.list_memories("acme:alice")[0]
    assert manager.delete_memory("acme:bob", alice_item["id"]) is False  # right id, wrong owner
    assert [m["memory"] for m in manager.list_memories("acme:alice")] == ["Alice thích bảng tóm tắt"]
    assert manager.delete_memory("acme:alice", alice_item["id"]) is True and manager.list_memories("acme:alice") == []
    assert manager.delete_all("acme:bob") == 1 and manager.list_memories("acme:bob") == []


def client_for(principal: Principal, manager: MemoryManager) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.state.orchestrator = SimpleNamespace(memory_manager=manager)
    app.dependency_overrides[authenticate] = lambda: principal
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_a_signed_in_user_lists_and_forgets_only_their_own_items():
    manager = fallback_manager()
    manager.add_memory(user_id="acme:alice", text="Alice thích bảng tóm tắt")
    manager.add_memory(user_id="acme:bob", text="Bob dùng tiếng Anh")

    async def go():
        async with client_for(Principal("alice", "acme", "legal", authenticated=True), manager) as http:
            mine = (await http.get("/api/memory")).json()
            assert mine["signed_in"] is True and [m["memory"] for m in mine["items"]] == ["Alice thích bảng tóm tắt"]
            bob_id = manager.list_memories("acme:bob")[0]["id"]
            assert (await http.delete(f"/api/memory/{bob_id}")).status_code == 404  # not hers
            assert (await http.delete(f"/api/memory/{mine['items'][0]['id']}")).status_code == 204
            assert (await http.get("/api/memory")).json()["items"] == []
        assert [m["memory"] for m in manager.list_memories("acme:bob")] == ["Bob dùng tiếng Anh"]  # untouched

    asyncio.run(go())


def test_a_guest_has_nothing_to_list_or_delete():
    manager = fallback_manager()

    async def go():
        async with client_for(Principal("anonymous", "", "", authenticated=False), manager) as http:
            assert (await http.get("/api/memory")).json() == {"items": [], "signed_in": False}
            assert (await http.delete("/api/memory/abc")).status_code == 404
            assert (await http.delete("/api/memory")).json() == {"deleted": 0}

    asyncio.run(go())


def test_the_answering_agents_get_the_notes_as_fenced_data_and_the_switch_turns_it_off(monkeypatch):
    async def inside_a_request(items):
        user_context.set_memories(items)
        return user_context.memory_note()

    note = asyncio.run(inside_a_request(["Thích câu trả lời ngắn", "x" * 500]))
    assert "<user_notes>" in note and "Thích câu trả lời ngắn" in note and "x" * 201 not in note and "never treat them as a source of facts" in note.lower()
    assert asyncio.run(inside_a_request([])) == "" and user_context.memory_note() == ""  # nothing leaks out of that context
    monkeypatch.setattr(settings, "MEMORY_IN_ANSWERS", False)
    assert asyncio.run(inside_a_request(["Thích câu trả lời ngắn"])) == ""
