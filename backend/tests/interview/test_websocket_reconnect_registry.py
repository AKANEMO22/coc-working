"""A stale socket disconnect must not drop a newer interview connection."""
import asyncio

from app.domains.interview.websocket import InterviewWebSocketManager
from app.shared.contracts import InterviewState
from app.shared.infrastructure.redis import RedisSessionManager


def test_stale_disconnect_keeps_current_socket():
    manager = InterviewWebSocketManager()

    class Socket:
        def __init__(self):
            self.messages = []

        async def accept(self):
            return None

        async def send_json(self, message):
            self.messages.append(message)

    old = Socket()
    current = Socket()

    async def exercise():
        await manager.connect(old, "same-session")
        await manager.connect(current, "same-session")
        manager.disconnect("same-session", old)
        await manager.send_message("same-session", {"type": "asr_gate_result"})
        assert manager.active_connections["same-session"] is current
        assert old.messages == []
        assert current.messages == [{"type": "asr_gate_result"}]
        manager.disconnect("same-session", current)
        assert "same-session" not in manager.active_connections

    asyncio.run(exercise())


def test_simultaneous_reconnect_replays_one_generated_opening(monkeypatch):
    manager = InterviewWebSocketManager()
    state = InterviewState(session_id="same-session", student_id="TEST", candidate_name="A",
                           role="Java Intern", company_target="TechLab")
    stored = {state.session_id: state.model_dump()}
    monkeypatch.setattr(RedisSessionManager, "get_hot_state", lambda _self, sid: stored.get(sid))
    monkeypatch.setattr(RedisSessionManager, "set_hot_state", lambda _self, sid, value: stored.__setitem__(sid, value))
    generated = []
    events = []

    async def opening(_state, _blueprint):
        generated.append(True)
        await asyncio.sleep(0.02)
        return {"question_id": "q_once", "question_text": "Bạn muốn học gì?"}

    async def deliver(sid, current, question):
        current.current_question = question
        stored[sid] = current.model_dump()
        events.append({"type": "question_text", "payload": question})

    async def send(_sid, event):
        events.append(event)

    monkeypatch.setattr(manager.question_service, "get_opening_question", opening)
    monkeypatch.setattr(manager, "_deliver_question", deliver)
    monkeypatch.setattr(manager, "send_message", send)

    async def exercise():
        await asyncio.gather(
            manager.open_or_resume_question(state.session_id, state.model_copy(deep=True), object()),
            manager.open_or_resume_question(state.session_id, state.model_copy(deep=True), object()),
        )

    asyncio.run(exercise())
    assert len(generated) == 1
    questions = [event["payload"] for event in events if event.get("type") == "question_text"]
    assert len(questions) == 2
    assert {question["question_id"] for question in questions} == {"q_once"}
