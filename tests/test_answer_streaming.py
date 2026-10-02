"""Answer tokens reach the SSE stream while the answer is written, as a preview that the verified final response replaces."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.agents.rag_agent.agent import RAGAgent
from src.orchestrator.core import Orchestrator
from src.shared import answer_stream
from src.shared.security import wrap_user_input

FINAL = {"answer": "Thời hạn là 2 năm [1].", "sources": [], "verification": {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": []}}


def chunks(*texts):
    return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t), finish_reason=None)]) for t in texts]


class StreamingLLM:
    """Streams the given pieces when called with stream=True, answers in one piece otherwise."""

    def __init__(self, *pieces, fail_at_start=False):
        self.pieces, self.fail_at_start, self.calls = pieces, fail_at_start, []

    async def chat_completion(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            if self.fail_at_start:
                raise RuntimeError("stream refused")

            async def gen():
                for c in chunks(*self.pieces):
                    yield c
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")])

            return gen()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="".join(self.pieces)), finish_reason="stop")])


def agent(llm):
    return RAGAgent(MagicMock(), llm)


def generate_with_sink(rag, queue):
    async def go():
        token = answer_stream.attach(answer_stream.AnswerStream(queue))
        try:
            return await rag._generate("Q?", "Q?", "ctx", "", "s")
        finally:
            answer_stream.detach(token)

    return asyncio.run(go())


def drained(queue):
    out = []
    while not queue.empty():
        kind, event = queue.get_nowait()
        assert kind == "answer"
        out.append((event["event"], json.loads(event["data"])))
    return out


def test_tokens_are_forwarded_as_they_arrive_and_the_full_answer_is_returned():
    queue = asyncio.Queue()
    answer, cut = generate_with_sink(agent(StreamingLLM("Thời hạn ", "là 2 ", "năm [1].")), queue)
    assert answer == "Thời hạn là 2 năm [1]." and cut is False
    events = drained(queue)
    assert [e for e, _ in events] == ["answer_delta"] * 3
    assert "".join(d["text"] for _, d in events) == answer


def test_a_not_found_refusal_is_held_back_and_never_shown():
    queue = asyncio.Queue()
    answer, _ = generate_with_sink(agent(StreamingLLM("NOT", "_FOU", "ND")), queue)
    assert answer == "NOT_FOUND" and drained(queue) == []


def test_text_that_only_starts_like_the_refusal_is_released_once_it_diverges():
    queue = asyncio.Queue()
    answer, _ = generate_with_sink(agent(StreamingLLM("NO", "TE: ", "xin chào")), queue)
    assert answer == "NOTE: xin chào"
    assert "".join(d["text"] for _, d in drained(queue)) == answer  # what was held back is sent too, in order


def test_a_retry_after_the_verifier_rejected_the_answer_resets_the_preview():
    queue = asyncio.Queue()
    rag = agent(StreamingLLM("Câu trả lời đầu."))

    async def twice():
        token = answer_stream.attach(answer_stream.AnswerStream(queue))
        try:
            await rag._generate("Q?", "Q?", "ctx", "", "s")
            await rag._generate("Q?", "Q?", "ctx", "lưu ý", "s")
        finally:
            answer_stream.detach(token)

    asyncio.run(twice())
    assert [e for e, _ in drained(queue)] == ["answer_delta", "answer_reset", "answer_delta"]


def test_without_a_stream_attached_nothing_streams_and_the_call_is_the_old_blocking_one():
    llm = StreamingLLM("Một câu trả lời.")
    answer, _ = asyncio.run(agent(llm)._generate("Q?", "Q?", "ctx", "", "s"))
    assert answer == "Một câu trả lời." and not llm.calls[0].get("stream")


def test_only_one_writer_at_a_time_so_parallel_answers_do_not_interleave():
    stream = answer_stream.AnswerStream(asyncio.Queue())
    assert stream.claim() and not stream.claim()
    stream.release()
    assert stream.claim()


def test_suspended_blocks_turn_streaming_off_for_their_duration():
    stream = answer_stream.AnswerStream(asyncio.Queue())
    token = answer_stream.attach(stream)
    try:
        assert answer_stream.current() is stream
        with answer_stream.suspended():
            assert answer_stream.current() is None
        assert answer_stream.current() is stream
    finally:
        answer_stream.detach(token)


def test_if_streaming_fails_before_the_first_token_the_answer_still_comes_blocking():
    queue = asyncio.Queue()
    answer, _ = generate_with_sink(agent(StreamingLLM("Vẫn trả lời được.", fail_at_start=True)), queue)
    assert answer == "Vẫn trả lời được." and drained(queue) == []


# ------------------------------------------------------------------ through the orchestrator
class RecordingAgent:
    """Writes its answer through the sink like the RAG agent does (when there is one) and remembers what it saw."""

    def __init__(self):
        self.saw_sink = []

    async def process_request(self, query, session_id):
        sink = answer_stream.current()
        self.saw_sink.append(sink is not None)
        if sink is not None and sink.claim():
            for piece in ("Thời hạn ", "là 2 năm [1]."):
                await sink.delta(piece)
                await asyncio.sleep(0)
            sink.release()
        return json.dumps(FINAL, ensure_ascii=False)


def orchestrator(target):
    registry = MagicMock()
    registry.lookup = MagicMock(return_value=target)
    settings = MagicMock(HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="fast", OPENROUTER_MODEL="m", HEAVY_LLM_MODEL="heavy")
    memory = MagicMock()
    memory.get_relevant_memories = MagicMock(return_value=[])
    memory.add_memory = MagicMock(return_value={})
    llm = MagicMock()
    llm.get_langfuse_callback = MagicMock(return_value=None)
    llm.flush_async = AsyncMock()
    return Orchestrator(registry=registry, settings=settings, llm_client=llm, memory_manager=memory)


def run_stream(orch):
    async def collect():
        return [e async for e in orch.handle_stream_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", agent_mode="rag_agent")]

    return asyncio.run(collect())


def test_the_sse_carries_the_tokens_before_the_verified_final_response():
    target = RecordingAgent()
    events = run_stream(orchestrator(target))
    names = [e["event"] for e in events]
    assert "error" not in names, [e["data"] for e in events if e["event"] == "error"]
    deltas = [i for i, n in enumerate(names) if n == "answer_delta"]
    assert "".join(json.loads(events[i]["data"])["text"] for i in deltas) == "Thời hạn là 2 năm [1]."
    assert names[-1] == "final_response" and deltas[-1] < len(names) - 1  # the preview comes first, the verified answer last
    assert json.loads(events[-1]["data"])["is_verified"] is True and target.saw_sink == [True]


def test_the_json_entry_point_never_streams():
    target = RecordingAgent()
    orch = orchestrator(target)
    out = asyncio.run(orch.handle_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", agent_mode="rag_agent"))
    assert json.loads(out)["answer"] == FINAL["answer"] and target.saw_sink == [False]


def test_the_stream_is_detached_after_the_request():
    run_stream(orchestrator(RecordingAgent()))
    assert answer_stream.current() is None


def test_an_agent_error_inside_the_graph_is_reported_not_hung():
    class Broken:
        async def process_request(self, query, session_id):
            raise RuntimeError("boom")

    events = run_stream(orchestrator(Broken()))
    assert events and events[-1]["event"] in ("final_response", "error")  # the consumer sees the failure or the graceful answer
