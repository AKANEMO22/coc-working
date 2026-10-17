"""Two-run live interview benchmark. Safe by default: requires --live to spend API quota.

It runs full synthetic sessions (the configured answer budget) through the actual
FastAPI HTTP/WebSocket routes, Gemini, VieNeu and Qwen3-ASR. Test data and session state
are temporary; the JSON audit report contains no credentials or audio payloads.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import unicodedata

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

SOURCE_FILES = sorted({str(path.relative_to(ROOT)).replace("\\", "/")
                       for root, patterns in ((ROOT / "backend" / "app", ("*.py",)),
                                              (ROOT / "frontend" / "src", ("*.ts", "*.tsx")))
                       for pattern in patterns for path in root.rglob(pattern)}
                      | {"tools/benchmark_interview_local_two_runs.py"})


def source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}

from app.shared.config import get_settings  # noqa: E402

SYNTHETIC_ANSWERS = [
    "Em đang định hướng Java Backend. Em chọn thực tập để rèn luyện xây REST API và học quy trình review code trong nhóm.",
    "Trong TaskFlow, em dùng Java và Spring Boot cho REST API. Em tách phần nhận request với phần xử lý nghiệp vụ để dễ kiểm thử.",
    "Với REST API, em kiểm tra dữ liệu đầu vào, trả status code phù hợp và viết test cho cả trường hợp thành công lẫn lỗi.",
    "TaskFlow dùng PostgreSQL lưu dữ liệu chính. Em dùng transaction khi cập nhật nhiều bước và chỉ thêm index sau khi kiểm tra truy vấn.",
    "Em dùng Redis cache các truy vấn đọc lặp lại với TTL. Khi dữ liệu thay đổi, em xóa cache liên quan để hạn chế dữ liệu cũ.",
    "Em viết unit test cho service bằng JUnit và kiểm tra endpoint bằng integration test, gồm cả dữ liệu không hợp lệ.",
    "Nếu API chậm, em tái hiện request, xem log và đo từng bước, rồi kiểm tra truy vấn trước khi đề xuất tối ưu.",
    "Trong TaskFlow, em phối hợp review code và kiểm tra lại thay đổi bằng test. Em muốn học thêm cách làm việc nhóm trong dự án thực tế.",
    "Với cache stampede, em sẽ dùng single-flight hoặc khóa theo cache key để chỉ một request đọc DB, các request khác chờ; TTL có thể thêm jitter.",
    "Spring thường dùng singleton bean chung cho nhiều request. Em sẽ giữ service stateless, dùng biến cục bộ và không để trạng thái từng request trong instance field.",
    "CV của em chưa nêu chi tiết isolation level. Với cập nhật nhiều bước, em sẽ đặt transaction ngắn ở service boundary và viết test cho concurrent update.",
    "PostgreSQL mặc định Read Committed nên không đọc dữ liệu chưa commit, nhưng vẫn có thể gặp non-repeatable read. Khi cần cùng một snapshot trong transaction, em cân nhắc Repeatable Read và test concurrent update.",
    "Với hai request cùng sửa task, em ưu tiên optimistic locking bằng trường version vì xung đột ít và không giữ khóa lâu. Nếu phát hiện version cũ, API báo conflict và client tải lại dữ liệu; khi xung đột dày đặc mới cân nhắc pessimistic locking.",
    "Em tạo dữ liệu test riêng cho từng test case, reset PostgreSQL bằng transaction rollback hoặc database container, rồi xóa Redis key theo namespace test. Các bài kiểm thử không chia sẻ state và em chạy thử song song để bắt lỗi rò rỉ.",
    "Em ghi thay đổi task và một bản ghi outbox trong cùng transaction PostgreSQL. Worker công bố message có idempotency key, retry khi broker lỗi; sau commit mới invalidate Redis. Em dùng TTL để giới hạn thời gian dữ liệu cũ còn tồn tại.",
    "Em chỉ xóa cache sau khi transaction DB commit thành công, ví dụ qua transactional event AFTER_COMMIT. Nếu xóa Redis lỗi, em retry qua outbox hoặc queue và đặt TTL; không xóa cache trước commit vì rollback sẽ khiến trạng thái lệch khó kiểm soát.",
    "Em muốn hỏi đội backend ở đây thường review code và hướng dẫn thực tập sinh ra sao, và trong kỳ thực tập em sẽ được tham gia phần nào của dự án thực tế ạ?",
    "Nếu luồng đọc cũ ghi lại cache sau lúc xóa, dữ liệu stale có thể tái xuất hiện. Em dùng version hoặc thời điểm cập nhật trong cache key, TTL ngắn, và xem xét delayed double delete sau commit; với dữ liệu quan trọng em kiểm tra version trước khi ghi cache.",
    "Trong TaskFlow, em tách controller để nhận request và validate DTO, service xử lý nghiệp vụ, repository truy cập PostgreSQL. Em giữ logic chính ở service để unit test và tránh controller quá lớn.",
]


def say(message: str) -> None:
    print(message, flush=True)


def read_logs_by_stage(logs: list[dict[str, Any]], stage: str, turn_id: str | None = None,
                       question_id: str | None = None) -> dict[str, Any]:
    """Safe post-run timing collector; never assumes a stage exists."""
    matched = []
    for item in logs:
        if item.get("stage") != stage:
            continue
        if turn_id and item.get("turn_id") != turn_id:
            continue
        details = item.get("details") or {}
        if question_id and details.get("question_id") != question_id:
            continue
        matched.append(item)
    if not matched:
        return {}
    matched.sort(key=lambda item: str(item.get("timestamp", "")))
    return matched[-1].get("details") or {}


def extract_question_context(call: dict[str, Any]) -> dict[str, Any]:
    contents = call.get("contents") or ""
    if not isinstance(contents, str):
        contents = json.dumps(contents, ensure_ascii=False, default=str)
    marker = "Ngữ cảnh phiên:\n"
    if marker not in contents:
        return {
            "system_instruction": str(call.get("system_instruction") or "")[:500],
            "user_prompt_excerpt": contents[:1400],
        }
    try:
        context = json.loads(contents.split(marker, 1)[1])
    except Exception:
        return {"context_parse": "failed", "prompt_chars": len(contents)}
    cv = context.get("cv_evidence") or {}
    job = context.get("job_requirements") or {}
    stage = context.get("stage") or {}
    skills = cv.get("skills") or {}
    return {
        "role": context.get("role"),
        "company": context.get("company"),
        "action": context.get("action"),
        "stage": stage.get("stage_name"),
        "rubric": stage.get("rubric_type"),
        "previous_question": context.get("previous_question"),
        "candidate_answer": context.get("candidate_answer"),
        "cv_skills": skills.get("hard_skills") or skills,
        "cv_projects": cv.get("projects"),
        "jd_title": job.get("title"),
        "jd_required_skills": job.get("required_skills"),
        "already_asked_count": len(context.get("already_asked") or []),
    }


def output_question_text(call: dict[str, Any]) -> str:
    response = call.get("response_text") or ""
    try:
        decoded = json.loads(response)
        if isinstance(decoded, dict) and isinstance(decoded.get("question_text"), str):
            return decoded["question_text"]
    except Exception:
        pass
    return str(response)


def self_test() -> None:
    sample_logs = [
        {"stage": "ASR_GATE", "turn_id": "t1", "details": {"decision_latency_ms": 12.5}},
        {"stage": "QUESTION_ENGINE", "details": {"question_id": "q1", "generation_latency_ms": 123}},
    ]
    assert read_logs_by_stage(sample_logs, "ASR_GATE", turn_id="t1")["decision_latency_ms"] == 12.5
    assert read_logs_by_stage(sample_logs, "QUESTION_ENGINE", question_id="q1")["generation_latency_ms"] == 123
    assert read_logs_by_stage(sample_logs, "MISSING") == {}
    context = {
        "role": "Java Backend Intern",
        "action": "same_level",
        "stage": {"stage_name": "technical_core", "rubric_type": "technical_correctness"},
        "candidate_answer": "Synthetic answer",
        "cv_evidence": {"skills": {"hard_skills": ["Java"]}},
        "job_requirements": {"title": "Backend Intern", "required_skills": ["Java"]},
    }
    fake_call = {"contents": "prompt\nNgữ cảnh phiên:\n" + json.dumps(context, ensure_ascii=False)}
    summary = extract_question_context(fake_call)
    assert summary["candidate_answer"] == "Synthetic answer"
    assert summary["action"] == "same_level"
    print("SELF_TEST=PASS provider_calls=0")


def aligned_audio_duration(payload: dict[str, Any]) -> float:
    for alignment in (payload.get("alignment"), payload.get("normalized_alignment")):
        if not isinstance(alignment, dict):
            continue
        values = alignment.get("character_end_times_seconds") or alignment.get("characterEndTimesSeconds")
        if isinstance(values, list):
            numbers = [float(value) for value in values if isinstance(value, (int, float))]
            if numbers:
                return max(numbers)
    return 0.0


def candidate_answer_for_question(question: str, turn_index: int) -> str:
    """Choose a grounded synthetic utterance that responds to the current prompt."""
    q = (question or "").casefold()
    if any(word in q for word in ("bạn có câu hỏi nào", "em có câu hỏi nào", "câu hỏi nào dành cho")):
        return SYNTHETIC_ANSWERS[16]
    if turn_index == 0 or any(word in q for word in ("giới thiệu bản thân", "lý do ứng tuyển", "động lực ứng tuyển")):
        return SYNTHETIC_ANSWERS[0]
    if any(word in q for word in ("stampede", "cache miss", "nhiều request", "nhiều thread", "đồng thời truy cập")):
        return SYNTHETIC_ANSWERS[8]
    if any(word in q for word in ("cache bị xóa", "ghi đè lại vào redis", "cache và database", "tính nhất quán giữa cache")):
        return SYNTHETIC_ANSWERS[17]
    if any(word in q for word in ("các tầng", "cấu trúc các tầng", "layer", "controller/service/repository")):
        return SYNTHETIC_ANSWERS[18]
    if any(word in q for word in ("singleton", "dependency injection", "instance variable", "thread-safety", "an toàn luồng", "bean scope")):
        return SYNTHETIC_ANSWERS[9]
    if any(word in q for word in ("message queue", "outbox", "đẩy message", "bắn một thông báo")):
        return SYNTHETIC_ANSWERS[14]
    if any(word in q for word in ("rollback", "distributed transaction", "xóa cache", "invalidate cache")):
        return SYNTHETIC_ANSWERS[15]
    if any(word in q for word in ("optimistic locking", "pessimistic locking", "version field", "xung đột cập nhật")):
        return SYNTHETIC_ANSWERS[12]
    if any(word in q for word in ("dirty read", "non-repeatable read", "isolation level", "mức độ cô lập")):
        return SYNTHETIC_ANSWERS[11]
    if any(word in q for word in ("dữ liệu test", "dọn dẹp state", "độc lập giữa", "isolation giữa")):
        return SYNTHETIC_ANSWERS[13]
    if any(word in q for word in ("redis", "cache", "bộ nhớ đệm")):
        return SYNTHETIC_ANSWERS[4]
    if any(word in q for word in ("transaction", "postgres", "sql", "database", "cơ sở dữ liệu", "isolation", "index")):
        return SYNTHETIC_ANSWERS[10]
    groups = [
        (("redis", "cache", "bộ nhớ đệm"), 4),
        (("junit", "test", "kiểm thử", "testing"), 5),
        (("rest", "api", "spring", "endpoint", "http"), 2),
        (("java", "oop", "đóng gói", "kế thừa", "đa hình"), 1),
        (("chậm", "debug", "lỗi", "hiệu năng", "performance", "tối ưu"), 6),
        (("nhóm", "review", "phối hợp", "giao tiếp"), 7),
    ]
    for keywords, answer_index in groups:
        if any(word in q for word in keywords):
            return SYNTHETIC_ANSWERS[answer_index]
    return SYNTHETIC_ANSWERS[turn_index % len(SYNTHETIC_ANSWERS)]


def transcript_similarity(expected: str, recognized: str) -> float:
    def normalize(value: str) -> list[str]:
        value = value.casefold().replace("đ", "d")
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return re.findall(r"[a-z0-9]+", value)
    return SequenceMatcher(None, normalize(expected), normalize(recognized), autojunk=False).ratio()


async def submit_spoken_answer(client: httpx.AsyncClient, app_ws: Any, session_id: str,
                               run_no: int, turn_index: int, question_text: str, question_id: str | None,
                               control: Path) -> dict[str, Any]:
    """Speak synthetic candidate text with VieNeu, transcribe WAV with Qwen, then advance."""
    scripted_answer = candidate_answer_for_question(question_text, turn_index)
    control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_user_tts"}), encoding="utf-8")
    input_tts_start = time.perf_counter()
    audio_resp = await client.get("/api/v1/tts/synthesize", params={"text": scripted_answer})
    input_tts_ms = round((time.perf_counter() - input_tts_start) * 1000, 1)
    if audio_resp.status_code != 200 or not audio_resp.content:
        return {"reason": f"candidate_tts_http_{audio_resp.status_code}", "provider_error": audio_resp.text[:800]}

    import io, wave
    import numpy as np
    import soundfile as sf
    with wave.open(io.BytesIO(audio_resp.content), "rb") as wav:
        duration_sec = wav.getnframes() / wav.getframerate()
    pcm, _sample_rate = sf.read(io.BytesIO(audio_resp.content), dtype="float32")
    if pcm.ndim == 2:
        pcm = pcm.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
    clipped_fraction = float(np.mean(np.abs(pcm) > 0.985)) if pcm.size else 0.0
    asr_evidence = {
        "source": "qwen_microphone", "duration_sec": duration_sec,
        "rms": rms, "clipped_fraction": clipped_fraction,
        "audio_quality_ok": 0.008 <= rms <= 0.6 and clipped_fraction < 0.12,
    }
    control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_qwen_stt"}), encoding="utf-8")
    stt_start = time.perf_counter()
    stt_resp = await client.post("/api/v1/stt/transcribe", params={"language": "vi", "session_id": session_id}, files={
        "file": ("candidate.wav", audio_resp.content, "audio/wav")
    })
    stt_ms = round((time.perf_counter() - stt_start) * 1000, 1)
    if stt_resp.status_code != 200:
        return {"reason": f"qwen_stt_http_{stt_resp.status_code}", "provider_error": stt_resp.text[:800]}
    transcript = (stt_resp.json().get("text") or "").strip()
    similarity = transcript_similarity(scripted_answer, transcript)
    turn_id = f"bench_{run_no}_{turn_index + 1}_{uuid.uuid4().hex[:8]}"
    turn = {
        "turn_id": turn_id, "turn_number": turn_index + 1,
        "question_id": question_id, "question": question_text,
        "scripted_speech": scripted_answer, "qwen_transcript": transcript,
        "script_transcript_similarity": round(similarity, 3),
        "input_tts_ms": input_tts_ms, "input_tts_chars": len(scripted_answer),
        "answer_audio_sec": round(duration_sec, 2), "qwen_stt_ms": stt_ms,
    }
    if not transcript:
        return {"turn": turn, "reason": "empty_qwen_transcript"}

    control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_orchestrator"}), encoding="utf-8")
    answer_started = time.perf_counter()
    await app_ws.send(json.dumps({
        "type": "final_transcript",
        "payload": {"turn_id": turn_id, "text": transcript, "term_candidates": [],
                    "asr_evidence": asr_evidence},
    }, ensure_ascii=False))
    gate_actions: list[str] = []
    confirmation_used = False
    turn["spoken_reprompts"] = []
    while True:
        event = json.loads(await app_ws.recv())
        kind = event.get("type")
        if kind == "asr_gate_result":
            gate = event.get("payload") or {}
            action = str(gate.get("asr_gate_action", "unknown"))
            gate_actions.append(action)
            if not gate.get("transcript_safe", False):
                if action not in {"REQUEST_VERIFICATION", "ASK_CONFIRMATION"} or similarity < 0.55:
                    turn.update({"gate_actions": gate_actions, "confirmation_used": False})
                    return {"turn": turn, "reason": "asr_gate_or_transcript_mismatch"}
        elif kind == "stream_interruption":
            spoken = str((event.get("payload") or {}).get("utterance") or "").strip()
            if not spoken or len(turn["spoken_reprompts"]) >= 2:
                return {"turn": turn, "reason": "invalid_or_repeated_asr_reprompt"}
            repeat_no = len(turn["spoken_reprompts"]) + 1
            control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_asr_reprompt_{repeat_no}"}), encoding="utf-8")
            prompt_started = time.perf_counter()
            spoken_response = await client.post("/api/v1/tts/synthesize-aligned", json={
                "text": spoken, "session_id": session_id,
            })
            if spoken_response.status_code != 200:
                return {"turn": turn, "reason": f"asr_reprompt_tts_http_{spoken_response.status_code}"}
            prompt_tts_ms = round((time.perf_counter() - prompt_started) * 1000, 1)
            prompt_duration = aligned_audio_duration(spoken_response.json())
            if prompt_duration:
                await asyncio.sleep(prompt_duration)
            repeat_started = time.perf_counter()
            repeated = await client.post("/api/v1/stt/transcribe", params={
                "language": "vi", "session_id": session_id, "kind": "final",
            }, files={"file": ("candidate-repeat.wav", audio_resp.content, "audio/wav")})
            if repeated.status_code != 200:
                return {"turn": turn, "reason": f"asr_repeat_stt_http_{repeated.status_code}"}
            repeated_text = str(repeated.json().get("text") or "").strip()
            turn["spoken_reprompts"].append({
                "text": spoken, "tts_ms": prompt_tts_ms, "playback_sec": round(prompt_duration, 2),
                "repeated_transcript": repeated_text,
                "qwen_ms": round((time.perf_counter() - repeat_started) * 1000, 1),
            })
            if not repeated_text:
                return {"turn": turn, "reason": "empty_asr_repeat_transcript"}
            await app_ws.send(json.dumps({
                "type": "final_transcript",
                "payload": {"turn_id": f"{turn_id}_repeat_{repeat_no}", "text": repeated_text,
                            "term_candidates": [], "asr_evidence": asr_evidence},
            }, ensure_ascii=False))
        elif kind == "stream_interruption_cancelled":
            return {"turn": turn, "reason": "asr_spoken_reprompt_unavailable"}
        elif kind in {"question_text", "session_ended"}:
            turn.update({"gate_actions": gate_actions, "confirmation_used": confirmation_used,
                         "transcript_to_next_event_ms": round((time.perf_counter() - answer_started) * 1000, 1)})
            return {"turn": turn, "next_event": event}
        elif kind == "error":
            code = str((event.get("payload") or {}).get("code", "error"))
            if code == "QUESTION_GENERATION_UNAVAILABLE":
                # Exercise the product's explicit retry control once after a
                # transient 503, preserving the committed candidate answer.
                turn["question_retry_used"] = True
                retry_started = time.perf_counter()
                control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_question_retry"}), encoding="utf-8")
                await app_ws.send(json.dumps({"type": "reconnect", "payload": {"retry_question": True}}))
                turn["question_retry_send_ms"] = round((time.perf_counter() - retry_started) * 1000, 1)
                while True:
                    retry_event = json.loads(await app_ws.recv())
                    retry_kind = retry_event.get("type")
                    if retry_kind in {"question_text", "session_ended"}:
                        turn.update({"gate_actions": gate_actions, "confirmation_used": confirmation_used,
                                     "transcript_to_next_event_ms": round((time.perf_counter() - answer_started) * 1000, 1)})
                        return {"turn": turn, "next_event": retry_event}
                    if retry_kind == "error":
                        break
            turn.update({"gate_actions": gate_actions, "confirmation_used": confirmation_used})
            return {"turn": turn,
                    "reason": "orchestrator_" + code,
                    "error_elapsed_ms": round((time.perf_counter() - answer_started) * 1000, 1)}


async def run_one_session(base: str, port: int, cache: Path, control: Path,
                          run_no: int) -> dict[str, Any]:
    client = httpx.AsyncClient(base_url=base, timeout=None)
    result: dict[str, Any] = {"run": run_no, "status": "PARTIAL", "turns": [], "questions": []}
    session_id = ""
    session_started = time.perf_counter()
    try:
        health = (await client.get("/health")).json()
        voice_info = (await client.get("/api/v1/tts/voices")).json()
        student_id = f"TEST_BENCH_{run_no}_{uuid.uuid4().hex[:8]}"
        synthetic_profile = {
            "candidate_name": "Ứng viên thử nghiệm",
            "profile": {
                "candidate_name": "Ứng viên thử nghiệm",
                "target_role": "Java Backend Intern",
                "skills": {"hard_skills": ["Java", "Spring Boot", "REST API", "PostgreSQL", "Redis", "JUnit"]},
                "projects": [{
                    "name": "TaskFlow (CV giả lập)",
                    "role": "Backend developer",
                    "technologies": ["Java", "Spring Boot", "PostgreSQL", "Redis"],
                    "description": "REST API quản lý công việc; PostgreSQL lưu dữ liệu, Redis cache truy vấn đọc nhiều.",
                }],
                "career_objective": "Rèn luyện phát triển backend Java.",
            },
        }
        (cache / (student_id + "_cand_mem.json")).write_text(
            json.dumps(synthetic_profile, ensure_ascii=False), encoding="utf-8"
        )

        create_start = time.perf_counter()
        create = await client.post("/api/v1/sessions/create", json={
            "student_id": student_id,
            "target_company": "TechLab (công ty giả lập)",
            "target_role": "Java Backend Intern",
            "domain_pack": "it_software",
            "jd_text": "Thực tập Java Backend: REST API Spring Boot, PostgreSQL/Redis, viết test, code review.",
            "skill_gaps": ["Java", "Spring Boot", "REST API", "PostgreSQL", "Redis", "testing"],
        })
        result["create_ms"] = round((time.perf_counter() - create_start) * 1000, 1)
        if create.status_code != 200:
            result["reason"] = f"session_create_http_{create.status_code}"
            return result

        session_id = create.json()["session_id"]
        result.update({"session_id": session_id, "laya": health.get("controller"),
                       "laya_loaded": bool(health.get("laya_model_loaded")),
                       "tts_provider": voice_info.get("default_provider"),
                       "tts_model": voice_info.get("default_model"),
                       "stt_model": get_settings().stt_model_id})
        state_resp = await client.get(f"/api/v1/sessions/{session_id}/state")
        session_state = state_resp.json() if state_resp.status_code == 200 else {}
        target_answers = int(session_state.get("remaining_scored_question_budget", 8) or 8)
        result["planned_scored_answers"] = target_answers
        result["gemini_model_configured"] = get_settings().gemini_flash_model

        app_uri = f"ws://127.0.0.1:{port}/ws/interview/{session_id}"
        async with websockets.connect(
            app_uri, open_timeout=None, close_timeout=None, ping_timeout=None, max_size=4_000_000,
        ) as app_ws:
            control.write_text(json.dumps({"run": run_no, "phase": "opening"}), encoding="utf-8")
            opening_started = time.perf_counter()
            opening_event = None
            opening_error = None
            while opening_event is None and opening_error is None:
                event = json.loads(await app_ws.recv())
                if event.get("type") == "question_text":
                    opening_event = event
                elif event.get("type") == "error":
                    opening_error = event
            if opening_error:
                result["reason"] = "opening_" + str((opening_error.get("payload") or {}).get("code", "error"))
                result["opening_error_ms"] = round((time.perf_counter() - opening_started) * 1000, 1)
            else:
                opening_payload = opening_event.get("payload") or {}
                current_question = str(opening_payload.get("question_text") or "").strip()
                current_question_id = opening_payload.get("question_id")
                result["opening_text"] = current_question
                result["opening_question_id"] = current_question_id
                result["opening_ws_ms"] = round((time.perf_counter() - opening_started) * 1000, 1)
                say(f"RUN_{run_no} OPENING_READY model={result['gemini_model_configured']} ws_ms={result['opening_ws_ms']} question={json.dumps(current_question, ensure_ascii=False)}")
                result["questions"].append({"question_id": current_question_id,
                                            "text": current_question, "kind": "opening"})

                control.write_text(json.dumps({"run": run_no, "phase": "opening_tts"}), encoding="utf-8")
                tts_start = time.perf_counter()
                opening_resp = await client.post("/api/v1/tts/synthesize-aligned", json={"text": current_question, "session_id": session_id})
                result["opening_tts_ms"] = round((time.perf_counter() - tts_start) * 1000, 1)
                if opening_resp.status_code != 200:
                    result["reason"] = f"opening_tts_http_{opening_resp.status_code}"
                    result["provider_error"] = opening_resp.text[:800]
                else:
                    opening_audio = opening_resp.json()
                    opening_playback = aligned_audio_duration(opening_audio)
                    result.update({
                        "opening_chars": len(current_question),
                        "opening_character_cost": opening_audio.get("character_cost"),
                        "opening_playback_sec": round(opening_playback, 2),
                        "question_audio_costs": [{
                            "question_id": current_question_id,
                            "character_cost": opening_audio.get("character_cost"),
                        }],
                    })
                    if opening_playback:
                        await asyncio.sleep(opening_playback)

                # Continue through the actual closing turn. The scored-question
                # budget is a ceiling, not a signal to skip an already-delivered wrap-up.
                turn_index = 0
                while not result.get("reason") and turn_index < target_answers + 2:
                    turn_result = await submit_spoken_answer(
                        client, app_ws, session_id, run_no, turn_index,
                        current_question, current_question_id, control,
                    )
                    turn = turn_result.get("turn")
                    if turn:
                        result["turns"].append(turn)
                        say(
                            f"RUN_{run_no} TURN_{turn['turn_number']} SPEECH={json.dumps(turn.get('scripted_speech',''), ensure_ascii=False)} "
                            f"QWEN={json.dumps(turn.get('qwen_transcript',''), ensure_ascii=False)} "
                            f"qwen_ms={turn.get('qwen_stt_ms')} similarity={turn.get('script_transcript_similarity')}"
                        )
                    if turn_result.get("reason"):
                        result["reason"] = turn_result["reason"]
                        result["turn_error_elapsed_ms"] = turn_result.get("error_elapsed_ms")
                        result["provider_error"] = turn_result.get("provider_error")
                        break

                    next_event = turn_result.get("next_event") or {}
                    if next_event.get("type") == "session_ended":
                        result["end_reason"] = (next_event.get("payload") or {}).get("reason", "orchestrator_finished")
                        result["ended_by_orchestrator"] = True
                        break

                    next_payload = next_event.get("payload") or {}
                    next_question = str(next_payload.get("question_text") or "").strip()
                    next_question_id = next_payload.get("question_id")
                    if not next_question:
                        result["reason"] = "empty_followup_question"
                        break
                    turn["followup_question"] = next_question
                    turn["followup_question_id"] = next_question_id
                    say(f"RUN_{run_no} TURN_{turn['turn_number']} NEXT_QUESTION={json.dumps(next_question, ensure_ascii=False)}")
                    result["questions"].append({
                        "question_id": next_question_id,
                        "text": next_question,
                        "kind": "followup_or_wrap_up",
                    })

                    control.write_text(json.dumps({"run": run_no, "phase": f"turn_{turn_index + 1}_followup_tts"}), encoding="utf-8")
                    follow_tts_start = time.perf_counter()
                    follow_resp = await client.post("/api/v1/tts/synthesize-aligned", json={"text": next_question, "session_id": session_id})
                    turn["followup_tts_ms"] = round((time.perf_counter() - follow_tts_start) * 1000, 1)
                    if follow_resp.status_code != 200:
                        result["reason"] = f"followup_tts_http_{follow_resp.status_code}"
                        result["provider_error"] = follow_resp.text[:800]
                        break
                    follow_body = follow_resp.json()
                    follow_playback = aligned_audio_duration(follow_body)
                    turn.update({
                        "followup_chars": len(next_question),
                        "followup_character_cost": follow_body.get("character_cost"),
                        "followup_playback_sec": round(follow_playback, 2),
                    })
                    turn["transcript_to_audio_ready_ms"] = round(
                        turn.get("transcript_to_next_event_ms", 0) + turn["followup_tts_ms"], 1
                    )
                    result["question_audio_costs"].append({
                        "question_id": next_question_id,
                        "character_cost": follow_body.get("character_cost"),
                    })
                    await app_ws.send(json.dumps({
                        "type": "client_timing",
                        "payload": {
                            "phase": "answer_to_first_audio",
                            "latency_ms": turn["transcript_to_audio_ready_ms"],
                            "turn_id": turn["turn_id"],
                        },
                    }))
                    if follow_playback:
                        await asyncio.sleep(follow_playback)

                    current_question = next_question
                    current_question_id = next_question_id
                    turn_index += 1

                if not result.get("reason") and not result.get("ended_by_orchestrator"):
                    result["reason"] = "session_did_not_emit_end_within_question_budget_cap"

        if not session_id:
            return result
        control.write_text(json.dumps({"run": run_no, "phase": "final_report"}), encoding="utf-8")
        end_started = time.perf_counter()
        end_resp = await client.post(f"/api/v1/sessions/{session_id}/end")
        result["final_report_ms"] = round((time.perf_counter() - end_started) * 1000, 1)
        response_body = end_resp.json() if end_resp.status_code == 200 else {}
        report = response_body.get("report") or {}
        # A transient Gemini 503 leaves the real rubric pending. The product
        # exposes an explicit retry route; exercise it once, without replaying
        # any candidate audio or altering previously committed answers.
        if end_resp.status_code == 200 and report.get("report_status") == "PENDING_EVALUATION":
            retry_started = time.perf_counter()
            control.write_text(json.dumps({"run": run_no, "phase": "final_report_retry"}), encoding="utf-8")
            retry_resp = await client.post(f"/api/v1/sessions/{session_id}/report/retry")
            result["final_report_retry_ms"] = round((time.perf_counter() - retry_started) * 1000, 1)
            result["final_report_retry_http"] = retry_resp.status_code
            result["final_report_retry_used"] = True
            if retry_resp.status_code == 200:
                report = retry_resp.json()
        result["report_status"] = report.get("report_status", response_body.get("report_status", "unknown"))
        result["report_score"] = report.get("overall_score")
        result["report_evaluations"] = report.get("turn_evaluations") or []
        result["scored_answers"] = len(result["report_evaluations"])
        result["report_total_answers"] = report.get("total_answers", len(result["turns"]))
        result["create_to_report_ms"] = round((time.perf_counter() - session_started) * 1000, 1)
        result["status"] = (
            "PASS" if end_resp.status_code == 200
            and result["report_status"] == "READY"
            and result["scored_answers"] == len(result["turns"])
            and result.get("ended_by_orchestrator") is True
            and len(result["turns"]) == target_answers + 1
            and str(result["turns"][-1].get("question_id") or "").startswith("q_wrap_")
            and result.get("laya_loaded") is True
            and result.get("tts_provider") == "vieneu"
            and not result.get("reason")
            else "PARTIAL"
        )
        say(
            f"RUN_{run_no} FINAL_REPORT status={result['report_status']} scored={result['scored_answers']}/"
            f"{len(result['turns'])} latency_ms={result['final_report_ms']} acceptance={result['status']}"
        )

        logs_resp = await client.get("/api/v1/sessions/live-logs",
                                     params={"session_id": session_id, "limit": 500})
        logs = logs_resp.json().get("logs", []) if logs_resp.status_code == 200 else []
        result["backend_timings"] = {
            "opening_generation_ms": read_logs_by_stage(
                logs, "QUESTION_ENGINE", question_id=result.get("opening_question_id")
            ).get("generation_latency_ms"),
            "turns": [{
                "turn_id": turn.get("turn_id"),
                "asr_gate_ms": read_logs_by_stage(logs, "ASR_GATE", turn_id=turn.get("turn_id")).get("decision_latency_ms"),
                "laya_decision_ms": read_logs_by_stage(logs, "LIVE_ORCHESTRATION", turn_id=turn.get("turn_id")).get("laya_latency_ms"),
                "laya_action": read_logs_by_stage(logs, "LIVE_ORCHESTRATION", turn_id=turn.get("turn_id")).get("next_action"),
                "laya_confidence": read_logs_by_stage(logs, "LIVE_ORCHESTRATION", turn_id=turn.get("turn_id")).get("confidence"),
                "laya_timed_out": read_logs_by_stage(logs, "LIVE_ORCHESTRATION", turn_id=turn.get("turn_id")).get("laya_timed_out"),
                "question_generation_ms": (read_logs_by_stage(logs, "QUESTION_ENGINE", question_id=turn["followup_question_id"]).get("generation_latency_ms") if turn.get("followup_question_id") else None),
                "answer_to_question_ms": read_logs_by_stage(logs, "ANSWER_TO_NEXT_QUESTION", turn_id=turn.get("turn_id")).get("latency_ms"),
            } for turn in result["turns"]],
        }
        result["total_answer_audio_seconds"] = round(sum(float(t.get("answer_audio_sec", 0)) for t in result["turns"]), 2)
        result["total_candidate_tts_characters"] = sum(int(t.get("input_tts_chars") or 0) for t in result["turns"])
        result["total_interviewer_tts_characters"] = sum(len(q.get("text") or "") for q in result.get("questions", []))
        return result
    finally:
        await client.aclose()

def main() -> None:
    # Windows PowerShell can otherwise use a legacy code page that cannot print Vietnamese traces.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Make real paid provider calls.")
    parser.add_argument("--self-test", action="store_true", help="Check trace parsing without provider calls.")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if args.self_test:
        sample = [{"stage": "ASR_GATE", "turn_id": "t", "details": {"decision_latency_ms": 1}}]
        assert read_logs_by_stage(sample, "ASR_GATE", turn_id="t")["decision_latency_ms"] == 1
        context = {"role": "Java Backend Intern", "action": "opening",
                   "stage": {"stage_name": "intro"}, "candidate_answer": "",
                   "cv_evidence": {}, "job_requirements": {}, "already_asked": []}
        assert extract_question_context({"contents": "Ngữ cảnh phiên:\n" + json.dumps(context)})["action"] == "opening"
        assert candidate_answer_for_question("Chia sẻ về bản thân", 0) == SYNTHETIC_ANSWERS[0]
        assert "Redis" in candidate_answer_for_question("Em xử lý cache như thế nào?", 2)
        assert "single-flight" in candidate_answer_for_question("Redis cache stampede khi cache miss", 2)
        assert "stateless" in candidate_answer_for_question("Spring singleton bean thread-safety", 3)
        assert transcript_similarity("xin chào ứng viên", "xin chao ung vien") > 0.95
        print("SELF_TEST=PASS provider_calls=0")
        return
    if not args.live:
        parser.error("No provider calls were made. Use --self-test or explicitly pass --live.")
    if args.runs != 2:
        parser.error("This acceptance benchmark is configured for exactly two runs.")
    settings = get_settings()
    source_at_start = source_hashes()
    if not settings.google_gemini_api_key:
        print("STOP credentials_missing; provider_calls=0")
        return
    report_path = ROOT / "docs" / "interview_pipeline_local_benchmark_20261016.json"
    all_runs: list[dict[str, Any]] = []
    run_numbers = [1, 2]
    if settings.tts_provider != "vieneu":
        print("STOP speech_provider_not_local; provider_calls=0")
        return
    print(
        "BENCHMARK_START runs=2 full_scored_question_budget_per_run="
        f"{settings.session_scored_question_budget}; model={settings.gemini_flash_model}; "
        f"synthetic speech through VieNeu/Qwen3-ASR; SDK retries disabled; fresh_runs={run_numbers}"
    )

    with tempfile.TemporaryDirectory(prefix="coc-interview-benchmark-") as tmp_name:
        tmp = Path(tmp_name)
        launcher = tmp / "benchmark_launcher.py"
        launcher.write_text(r'''
import asyncio as _asyncio
import json, os, threading, time
from pathlib import Path
from types import SimpleNamespace
import app.shared.infrastructure.redis as redis_core
redis_core.CACHE_DIR = Path(os.environ["BENCH_CACHE"])
redis_core.CACHE_DIR.mkdir(parents=True, exist_ok=True)
from app.shared.config import get_settings
s = get_settings()
s.interview_question_timeout_sec = 86400.0
s.interview_clarification_timeout_sec = 86400.0
s.laya_decision_timeout_sec = 86400.0
from google import genai
from google.genai import types
_real_client = genai.Client
_metrics_path = Path(os.environ["BENCH_METRICS"])
_phase_path = Path(os.environ["BENCH_PHASE"])
_lock = threading.Lock()
def _phase():
    try: return json.loads(_phase_path.read_text(encoding="utf-8"))
    except Exception: return {}
def _record(row):
    with _lock:
        with _metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
def _safe_error(exc):
    message = str(exc)[:1600]
    for secret in (s.google_gemini_api_key,):
        if secret: message = message.replace(secret, "[REDACTED]")
    return message
def _client(*a, **kw):
    kw["http_options"] = types.HttpOptions(timeout=0, retry_options=types.HttpRetryOptions(attempts=1))
    client = _real_client(*a, **kw)
    original = client.models.generate_content
    def _call(*ca, **ck):
        started = time.perf_counter()
        contents = ck.get("contents", "")
        if not isinstance(contents, str): contents = str(contents)
        config = ck.get("config")
        instruction = getattr(config, "system_instruction", "") if config is not None else ""
        p = _phase()
        try:
            response = original(*ca, **ck)
            try: output = response.text or ""
            except Exception: output = ""
            usage = getattr(response, "usage_metadata", None)
            candidates = getattr(response, "candidates", None) or []
            finish = getattr(candidates[0], "finish_reason", None) if candidates else None
            _record({
                "run": p.get("run"), "phase": p.get("phase"), "model": ck.get("model"),
                "status": "success", "latency_ms": round((time.perf_counter()-started)*1000,1),
                "prompt_tokens": getattr(usage,"prompt_token_count",None),
                "output_tokens": getattr(usage,"candidates_token_count",None),
                "finish_reason": str(finish) if finish is not None else None,
                "contents": contents[:30000], "system_instruction": str(instruction)[:6000],
                "response_text": output[:8000],
            })
            return response
        except BaseException as exc:
            resp = getattr(exc,"response",None)
            status = getattr(exc,"code",None) or getattr(exc,"status_code",None)
            if status is None and resp is not None: status=getattr(resp,"status_code",None)
            _record({
                "run": p.get("run"), "phase": p.get("phase"), "model": ck.get("model"),
                "status": "error", "latency_ms": round((time.perf_counter()-started)*1000,1),
                "error_type": type(exc).__name__,
                "http_status": status if isinstance(status,(int,str)) else None,
                "error_message": _safe_error(exc),
                "contents": contents[:30000], "system_instruction": str(instruction)[:6000],
            })
            raise
    client.models.generate_content = _call
    return client
genai.Client = _client
class _NoDeadline:
    def __getattr__(self,n): return getattr(_asyncio,n)
    async def wait_for(self, awaitable, timeout=None): return await awaitable
from app.main import app
import app.domains.interview.services.questions as q
import app.domains.interview.services.dialogue as d
import app.domains.interview.services.evidence_evaluator as e
import app.domains.interview.websocket as w
nd = _NoDeadline()
for m in (q,d,e,w): m.asyncio = nd
''', encoding="utf-8")

        for run_no in run_numbers:
            run_dir = tmp / f"run{run_no}"
            cache = run_dir / "sessions"
            cache.mkdir(parents=True)
            metrics = run_dir / "gemini.jsonl"
            phase = run_dir / "phase.json"
            phase.write_text(json.dumps({"run": run_no, "phase": "startup"}), encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "HF_HUB_OFFLINE": "1", "APP_ENV": "development", "APP_DEBUG": "false",
                "UPSTASH_REDIS_URL": "", "UPSTASH_REDIS_TOKEN": "",
                "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "",
                "BENCH_CACHE": str(cache), "BENCH_METRICS": str(metrics), "BENCH_PHASE": str(phase),
                "PYTHONPATH": str(tmp) + os.pathsep + str(BACKEND), "PYTHONIOENCODING": "utf-8",
            })
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            server_log = open(run_dir / "server.log", "w", encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "benchmark_launcher:app",
                 "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                cwd=BACKEND, env=env, stdout=server_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            print(f"RUN_{run_no} BACKEND_STARTED pid={process.pid}", flush=True)
            base = f"http://127.0.0.1:{port}"
            boot = time.perf_counter()
            healthy = None
            try:
                import urllib.request
                while process.poll() is None:
                    try:
                        with urllib.request.urlopen(base + "/health", timeout=None) as response:
                            data = json.loads(response.read().decode("utf-8"))
                            if response.status == 200 and data.get("status") == "healthy":
                                healthy = data
                                break
                    except Exception:
                        time.sleep(0.5)
                if healthy is None:
                    print(f"RUN_{run_no} BACKEND_START_FAILED", flush=True)
                    all_runs.append({"run": run_no, "status": "backend_failed"})
                    continue
                cold_start = round((time.perf_counter() - boot) * 1000, 1)
                print(f"RUN_{run_no} BACKEND_READY cold_start_ms={cold_start} "
                      f"laya_loaded={healthy.get('laya_model_loaded')}", flush=True)
                phase.write_text(json.dumps({"run": run_no, "phase": "opening"}), encoding="utf-8")
                result = asyncio.run(run_one_session(base, port, cache, phase, run_no))
                result["cold_start_ms"] = cold_start
                result["gemini_calls"] = []
                if metrics.exists():
                    for line in metrics.read_text(encoding="utf-8").splitlines():
                        try:
                            call = json.loads(line)
                            if call.get("run") == run_no:
                                result["gemini_calls"].append(call)
                        except Exception:
                            pass
                all_runs.append(result)

                # Emit acceptance and trace data before cleanup, even when a stage failed.
                print(f"RUN_{run_no} SUMMARY=" + json.dumps({
                    k: v for k, v in result.items()
                    if k not in {"opening_text", "turns", "questions", "gemini_calls", "report_evaluations"}
                }, ensure_ascii=False), flush=True)
                print(f"RUN_{run_no} OPENING=" + json.dumps(result.get("opening_text", ""), ensure_ascii=False), flush=True)
                print(f"RUN_{run_no} QUESTIONS=" + json.dumps(result.get("questions", []), ensure_ascii=False), flush=True)
                print(f"RUN_{run_no} USER_TURNS=" + json.dumps(result.get("turns", []), ensure_ascii=False), flush=True)
                print(f"RUN_{run_no} FINAL_EVALUATIONS=" + json.dumps(result.get("report_evaluations", []), ensure_ascii=False)[:3000], flush=True)
                for index, call in enumerate(result["gemini_calls"], 1):
                    print(f"RUN_{run_no} GEMINI_{index} phase={call.get('phase')} model={call.get('model')} "
                          f"status={call.get('status')} latency_ms={call.get('latency_ms')} "
                          f"tokens={call.get('prompt_tokens','n/a')}/{call.get('output_tokens','n/a')} "
                          f"http_status={call.get('http_status','n/a')} error={call.get('error_type','n/a')}", flush=True)
                    print(f"RUN_{run_no} GEMINI_INPUT_{index}=" +
                          json.dumps(extract_question_context(call), ensure_ascii=False)[:1200], flush=True)
                    if call.get("response_text"):
                        text = output_question_text(call)
                        print(f"RUN_{run_no} GEMINI_OUTPUT_{index}=" +
                              json.dumps(text[:1000], ensure_ascii=False), flush=True)
            except Exception as exc:
                print(f"RUN_{run_no} HARNESS_EXCEPTION={type(exc).__name__}", flush=True)
                existing = next((item for item in all_runs
                                 if item.get("run") == run_no), None)
                if existing is not None:
                    existing["harness_exception"] = type(exc).__name__
                else:
                    all_runs.append({"run": run_no, "status": "harness_error",
                                     "error_type": type(exc).__name__})
            finally:
                try:
                    process.terminate()
                    process.wait()
                except Exception:
                    try:
                        process.kill()
                        process.wait()
                    except Exception:
                        pass
                server_log.close()
                print(f"RUN_{run_no} BACKEND_STOPPED", flush=True)
            current_run = next((item for item in all_runs if item.get("run") == run_no), None)
            if current_run and any(call.get("http_status") == 429 for call in current_run.get("gemini_calls", [])):
                print(f"BENCHMARK_STOP provider_http_429 run={run_no}; no blind retry", flush=True)
                break
            if current_run and current_run.get("status") != "PASS":
                print(f"BENCHMARK_STOP incomplete_run={run_no}; fix before spending on another run", flush=True)
                break

    source_at_end = source_hashes()
    code_unchanged = source_at_start == source_at_end
    passed = sum(1 for run in all_runs if run.get("status") == "PASS") if code_unchanged else 0
    report_path.parent.mkdir(parents=True, exist_ok=True)
    all_runs.sort(key=lambda item: item.get("run", 0))
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256_at_start": source_at_start,
        "source_sha256_at_end": source_at_end,
        "code_unchanged_during_run": code_unchanged,
        "benchmark": "two independent full synthetic interview sessions through FastAPI, Gemini, VieNeu TTS, Qwen3-ASR, Laya gate, orchestration and final report",
        "constraints": {
            "runs_requested": 2,
            "synthetic_candidate_data": True,
            "synthetic_speech_audio": True,
            "answers_per_run_target": settings.session_scored_question_budget,
            "interview_runs_until_end_or_answer_budget": True,
            "provider_timeouts_disabled": True,
            "sdk_retries_disabled": True,
            "credentials_or_audio_persisted": False,
        },
        "acceptance": {"passed": passed, "requested": 2,
                       "statuses": [run.get("status") for run in all_runs]},
        "acceptance_definition": "PASS means eight substantive answers plus one answered wrap-up, orchestrator emitted session_ended, /end returned HTTP 200, report_status was READY, every submitted synthetic transcript was scored, Laya and local VieNeu were active, and no stage error occurred. It does not set a minimum score or certify interview-answer quality.",
        "known_limitations": [
            "This is backend/audio API E2E, not a physical microphone, browser VAD or audio/text synchronization test; playback duration is simulated.",
            "Candidate utterances are synthetic fixtures selected from question keywords; treat rubric scores as pipeline evidence, not as a model-quality benchmark.",
            "The full two-run acceptance is incomplete if either run is PARTIAL, even when its partial report is READY or NO_EVALUATION.",
        ],
        "post_run_code_fixes": [
            "Gemini default changed to the tested gemini-3.5-flash-lite model; live generation and report-evaluation timeouts are configurable and bounded.",
            "Speech is local: VieNeu generates candidate/interviewer WAV; Qwen3-ASR transcribes candidate WAV through the real REST route.",
        ],
        "runs": all_runs,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"BENCHMARK_REPORT={report_path}", flush=True)
    print(f"BENCHMARK_ACCEPTANCE={passed}/2 successful completed sessions; "
          f"statuses=" + json.dumps([run.get("status") for run in all_runs]), flush=True)


if __name__ == "__main__":
    main()
