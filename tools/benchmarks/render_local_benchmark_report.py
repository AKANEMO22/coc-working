"""Render local two-session E2E JSON into a readable Vietnamese audit."""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "benchmarks" / "interview_pipeline_local_benchmark_20261016.json"
TARGET = ROOT / "docs" / "benchmarks" / "interview_pipeline_local_benchmark_20261016.md"


def safe(value: object) -> str:
    text = str(value if value is not None else "—")
    text = re.sub(r"sk_[A-Za-z0-9_-]{16,}", "[REDACTED_KEY]", text)
    text = re.sub(r"AQ\.[A-Za-z0-9_-]{16,}", "[REDACTED_KEY]", text)
    return text


def table_cell(value: object) -> str:
    return safe(value).replace("|", "\\|").replace("\n", " ")


def stat(values: list[float]) -> str:
    return f"median {statistics.median(values):.1f}; max {max(values):.1f}" if values else "—"


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    acceptance = data.get("acceptance") or {}
    lines = [
        "# Nghiệm thu pipeline phỏng vấn local — 16/10/2026", "",
        f"- Chứng cứ máy đọc: `{SOURCE}`.",
        f"- Kết quả: **{acceptance.get('passed')}/{acceptance.get('requested')}** phiên PASS; "
        f"trạng thái {', '.join(acceptance.get('statuses') or [])}.",
        f"- Source không đổi giữa các phiên: **{safe(data.get('code_unchanged_during_run'))}**. Nếu False, không tính kết quả nghiệm thu dù các phiên riêng lẻ báo PASS.",
        "- Đây là E2E backend/audio API với CV/JD và câu trả lời giả lập: VieNeu WAV → Qwen3-ASR → WebSocket → Laya → Gemini → VieNeu → rubric cuối phiên. Playback được mô phỏng bằng thời gian audio.",
        "- UI, micro và Silero trong Chrome được kiểm tra riêng ở `docs/benchmarks/browser_local_voice_smoke_20261016.json`.",
        "- VieNeu trả mốc chữ **ước lượng**, không phải forced alignment; chưa thể xác nhận chữ khớp từng âm tiết chỉ bằng benchmark này.",
        "", "## Các model đã sử dụng", "",
        "| Thành phần | Model | Nơi chạy |", "|---|---|---|",
        "| STT | Qwen3-ASR-1.7B | Backend local CUDA |",
        "| TTS | VieNeu-TTS v3 Turbo | Backend local CUDA |",
        "| Quyết định luồng | Laya Multilingual 322M | Backend local CUDA, eager |",
        "| Sinh câu và rubric | Gemini 3.5 Flash Lite | Google API |",
        "| VAD UI | Silero ONNX | Browser, kiểm tra riêng |",
        "", "## Tổng thời gian", "",
        "| Phiên | Kết quả | Lượt nói | Lượt chấm | Cold start s | Mở đầu Gemini ms | TTS mở đầu ms | Từ tạo phiên đến report s | Điểm |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    runs = data.get("runs") or []
    for run in runs:
        b = run.get("backend_timings") or {}
        row = [run.get("run"), run.get("status"), len(run.get("turns") or []), run.get("scored_answers"),
               round(float(run.get("cold_start_ms") or 0) / 1000, 1), b.get("opening_generation_ms"),
               run.get("opening_tts_ms"), round(float(run.get("create_to_report_ms") or 0) / 1000, 1), run.get("report_score")]
        lines.append("| " + " | ".join(map(table_cell, row)) + " |")

    for run in runs:
        turns = run.get("turns") or []
        timings = (run.get("backend_timings") or {}).get("turns") or []
        lines += ["", f"## Phiên {safe(run.get('run'))} — {safe(run.get('status'))}", "",
                  f"- Phiên `{safe(run.get('session_id'))}`; kết thúc: {safe(run.get('end_reason') or run.get('reason'))}; rubric {safe(run.get('report_status'))}, {safe(run.get('scored_answers'))}/{len(turns)} lượt.",
                  f"- Audio câu trả lời tổng cộng {safe(run.get('total_answer_audio_seconds'))} s; Gemini gọi {len(run.get('gemini_calls') or [])} lần; điểm {safe(run.get('report_score'))}.",
                  f"- Retry tường minh sinh câu sau lỗi 503: {sum(bool(turn.get('question_retry_used')) for turn in turns)} lượt; retry rubric: {safe(run.get('final_report_retry_used') or False)}.",
                  "- Độ trễ (ms): Qwen STT " + stat([float(t["qwen_stt_ms"]) for t in turns if isinstance(t.get("qwen_stt_ms"), (int, float))]) +
                  "; câu đã xác nhận → câu kế " + stat([float(t["answer_to_question_ms"]) for t in timings if isinstance(t.get("answer_to_question_ms"), (int, float))]) +
                  "; câu đã xác nhận → audio sẵn sàng " + stat([float(t["transcript_to_audio_ready_ms"]) for t in turns if isinstance(t.get("transcript_to_audio_ready_ms"), (int, float))]) + ".",
                  "", "### Câu mở đầu", "", safe(run.get("opening_text")), ""]
        if run.get("provider_error"):
            lines += ["**Lỗi:** " + safe(run["provider_error"]), ""]
        for index, turn in enumerate(turns):
            timing = timings[index] if index < len(timings) else {}
            lines += [
                f"### Lượt {safe(turn.get('turn_number', index + 1))}", "",
                f"- AI hỏi: {safe(turn.get('question'))}",
                f"- Ứng viên giả lập nói: {safe(turn.get('scripted_speech'))}",
                f"- Qwen nghe được: {safe(turn.get('qwen_transcript'))}",
                f"- So khớp lời nói/ASR: {safe(turn.get('script_transcript_similarity'))}; gate: {safe(turn.get('gate_actions'))}; xác nhận transcript: {safe(turn.get('confirmation_used'))}.",
                f"- Laya: {safe(timing.get('laya_action'))}; confidence {safe(timing.get('laya_confidence'))}; {safe(timing.get('laya_decision_ms'))} ms; timeout: {safe(timing.get('laya_timed_out'))}.",
                f"- Timing: VieNeu ứng viên {safe(turn.get('input_tts_ms'))} ms; Qwen {safe(turn.get('qwen_stt_ms'))} ms; Gemini câu tiếp {safe(timing.get('question_generation_ms'))} ms; VieNeu câu tiếp {safe(turn.get('followup_tts_ms'))} ms; câu trả lời → audio sẵn sàng {safe(turn.get('transcript_to_audio_ready_ms'))} ms.",
                f"- AI hỏi tiếp: {safe(turn.get('followup_question'))}", "",
            ]
            for repeat in turn.get("spoken_reprompts") or []:
                lines += [f"- **AI tự hỏi lại bằng giọng nói:** {safe(repeat.get('text'))}",
                          f"  VieNeu {safe(repeat.get('tts_ms'))} ms; audio {safe(repeat.get('playback_sec'))} s; "
                          f"Qwen nghe lần hai: {safe(repeat.get('repeated_transcript'))} ({safe(repeat.get('qwen_ms'))} ms).", ""]
        lines += ["### Gemini: prompt và phản hồi từng call", ""]
        for index, call in enumerate(run.get("gemini_calls") or [], 1):
            lines += [f"#### Call {index}: {safe(call.get('phase'))}", "",
                      f"Model `{safe(call.get('model'))}`; status {safe(call.get('status'))}; {safe(call.get('latency_ms'))} ms; tokens vào/ra {safe(call.get('prompt_tokens'))}/{safe(call.get('output_tokens'))}.",
                      "", "System instruction:", "", "```text", safe(call.get("system_instruction")), "```",
                      "", "Input:", "", "```text", safe(call.get("contents")), "```",
                      "", "Output:", "", "```text", safe(call.get("response_text") or call.get("error_message")), "```", ""]
        lines += ["### Rubric cuối phiên", ""]
        for evaluation in run.get("report_evaluations") or []:
            lines.append(f"- Lượt {safe(evaluation.get('turn_number'))}, stage {safe(evaluation.get('stage'))}, điểm {safe(evaluation.get('score'))}: {safe(evaluation.get('candidate_summary'))}; gợi ý {safe(evaluation.get('better_answer_hint'))}")
        lines.append("")
    lines += ["## Giới hạn nghiệm thu", "",
              "PASS chứng minh HTTP/WebSocket, model local và Gemini đi đến báo cáo với transcript giả lập. Điểm rubric là đánh giá nội dung lời đáp thử, không phải chứng nhận chất lượng tuyển dụng. Báo cáo browser riêng xác minh mic/Silero/UI; nếu browser test PARTIAL thì trải nghiệm người dùng chưa nghiệm thu đủ.", ""]
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(TARGET)


if __name__ == "__main__":
    main()
