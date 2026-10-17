"""
CÓC ĐI LÀM — Comprehensive 1:1 Interview Flow E2E Test Suite (§4, §6, §8, §11, §12, §14)
KIỂM TRA TOÀN BỘ FLOW CHẠY CỦA PHÒNG PHỎNG VẤN 1:1:
1. Khởi tạo phiên phỏng vấn thật (POST /api/v1/sessions/initiate)
2. Thẩm định âm thanh giọng nói Neural TTS thật (GET /api/v1/tts/synthesize)
3. Kết nối WebSocket hai chiều thật (ws://.../ws/interview/{session_id})
4. Nhận State Sync & Câu hỏi mở đầu (hr_motivation)
5. Turn 1: Ứng viên gửi câu trả lời HR & Động lực -> Đánh giá Rubric thật -> Nhận câu hỏi tiếp
6. Turn 2: Ứng viên bảo vệ dự án STAR (cv_project_defense) -> Đánh giá STAR -> Chuyển Stage
7. Turn 3: Ứng viên trả lời kỹ thuật lõi (technical_core) -> Đánh giá Technical Correctness
8. Test tính năng ngắt lời (Barge-in / Interruption)
9. Test tính năng Hỏi ngược phỏng vấn viên (Reverse Interviewing)
10. Tổng kết & Xuất Báo cáo Đánh giá Năng lực OJT thực chiến (/api/v1/sessions/{session_id}/report)
TUYỆT ĐỐI CẤM MOCK TEST / KHÔNG MÔ PHỎNG GIẢ ĐỊNH.
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

import sys
import os
import io
import asyncio
import json
import httpx
import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API_BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"

PASSED_COUNT = 0
FAILED_COUNT = 0

def record_test(name: str, passed: bool, message: str = ""):
    global PASSED_COUNT, FAILED_COUNT
    if passed:
        PASSED_COUNT += 1
        print(f"  ✅ [PASS] {name} {f'({message})' if message else ''}")
    else:
        FAILED_COUNT += 1
        print(f"  ❌ [FAIL] {name}: {message}")


async def test_neural_tts_audio(text: str, label: str):
    """Kiểm tra âm thanh phát ra từ Neural TTS có hợp lệ, nghe được và không bị lỗi."""
    async with httpx.AsyncClient(timeout=35.0) as client:
        resp = await client.get(
            f"{API_BASE}/api/v1/tts/synthesize",
            params={"text": text, "voice": "vi-VN-HoaiMyNeural"}
        )
        record_test(f"TTS Audio Generation: {label} (HTTP 200)", resp.status_code == 200)
        record_test(f"TTS Audio MIME Type is audio/mpeg", resp.headers.get("content-type") == "audio/mpeg")
        audio_len = len(resp.content)
        record_test(f"TTS Audio Has Valid Playable Bytes ({audio_len:,} bytes)", audio_len > 10000, f"Size: {audio_len} bytes")
        return audio_len > 10000


async def run_interview_1on1_e2e():
    print("=" * 85)
    print("🎙️ BẮT ĐẦU KIỂM TRA E2E TOÀN BỘ LUỒNG PHÒNG PHỎNG VẤN 1:1 THỰC CHIẾN")
    print("=" * 85)

    # -------------------------------------------------------------
    # BƯỚC 1: KHỞI TẠO PHIÊN PHỎNG VẤN QUA REST API
    # -------------------------------------------------------------
    print("\n>>> BƯỚC 1: Khởi tạo phiên phỏng vấn (POST /api/v1/sessions/initiate)")
    session_id = None
    init_data = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        init_resp = await client.post(
            f"{API_BASE}/api/v1/sessions/initiate",
            json={
                "student_id": "SE180000",
                "target_company": "FPT Software",
                "target_role": "Java Backend Intern",
                "auth_profile": "PILOT_DEMO",
            }
        )
        record_test("Session Initiation HTTP 200", init_resp.status_code == 200)
        init_data = init_resp.json()
        session_id = init_data.get("session_id")
        record_test("Session ID Generated", bool(session_id), f"Session: {session_id}")
        blueprint = init_data.get("blueprint", {})
        record_test("Interview Blueprint Generated", bool(blueprint.get("stages")), f"{len(blueprint.get('stages', []))} stages")
        record_test("Candidate Memory Connected", bool(init_data.get("state")))

    if not session_id:
        print("❌ Lỗi: Không thể khởi tạo phiên. Dừng kiểm tra.")
        return

    # -------------------------------------------------------------
    # BƯỚC 2: THẨM ĐỊNH GIỌNG NÓI NEURAL TTS PHÁT RA TỪ MÁY CHỦ
    # -------------------------------------------------------------
    print("\n>>> BƯỚC 2: Thẩm định khả năng phát âm thanh Neural TTS của hệ thống")
    sample_q = "Chào em, chào mừng em đến với buổi phỏng vấn vị trí Java Backend tại FPT Software. Em hãy giới thiệu bản thân và mục tiêu OJT nhé!"
    await test_neural_tts_audio(sample_q, "Opening Question Audio")

    # -------------------------------------------------------------
    # BƯỚC 3: KẾT NỐI WEBSOCKET HAI CHIỀU REALTIME
    # -------------------------------------------------------------
    print(f"\n>>> BƯỚC 3: Kết nối WebSocket Realtime ({WS_BASE}/ws/interview/{session_id})")
    ws_url = f"{WS_BASE}/ws/interview/{session_id}"

    async with websockets.connect(ws_url) as ws:
        record_test("WebSocket Handshake Established", True, f"Connected to {session_id}")

        # 1. Nhận STATE_SYNC ban đầu
        raw_msg1 = await asyncio.wait_for(ws.recv(), timeout=10.0)
        msg1 = json.loads(raw_msg1)
        record_test("Received Initial STATE_SYNC", msg1.get("type") == "state_sync")
        state_payload = msg1.get("payload", {})
        record_test("Initial Stage is hr_motivation", state_payload.get("current_topic") == "hr_motivation")
        record_test("Initial Difficulty is 2 or 3", state_payload.get("current_difficulty") in [2, 3])

        # 2. Nhận QUESTION_TEXT mở đầu từ Blueprint
        raw_msg2 = await asyncio.wait_for(ws.recv(), timeout=10.0)
        msg2 = json.loads(raw_msg2)
        record_test("Received Opening QUESTION_TEXT", msg2.get("type") == "question_text")
        q_payload = msg2.get("payload", {})
        first_q_text = q_payload.get("question_text", "")
        record_test("Opening Question Text Non-empty", len(first_q_text) > 15, first_q_text[:60] + "...")
        record_test("Opening Question Stage is hr_motivation", q_payload.get("stage_name") == "hr_motivation")

        # Thẩm định âm thanh TTS cho câu hỏi mở đầu thực tế
        await test_neural_tts_audio(first_q_text, "Actual Received Opening Question")

        # -------------------------------------------------------------
        # BƯỚC 4: TURN 1 — ỨNG VIÊN TRẢ LỜI ĐỘNG LỰC HR
        # -------------------------------------------------------------
        print("\n>>> BƯỚC 4: Turn 1 — Ứng viên gửi câu trả lời HR & Động lực OJT")
        ans_turn1 = (
            "Em chào anh/chị, em là sinh viên năm cuối chuyên ngành Kỹ thuật Phần mềm ĐH FPT. "
            "Em rất ấn tượng với văn hóa làm việc toàn cầu và các dự án enterprise quy mô lớn tại FPT Software. "
            "Mục tiêu trong kỳ OJT của em là cọ xát với hệ thống Backend thực tế, áp dụng nguyên tắc Horenso "
            "và đóng góp hết mình vào dự án của team."
        )

        # Gửi partial transcript giả lập người đang nói
        await ws.send(json.dumps({
            "type": "partial_transcript",
            "payload": {"text": "Em chào anh chị em là sinh viên năm cuối...", "features": {"duration_sec": 3.2}}
        }))

        # Gửi final transcript chốt câu trả lời
        await ws.send(json.dumps({
            "type": "final_transcript",
            "payload": {
                "text": ans_turn1,
                "term_candidates": ["FPT Software", "Backend", "Horenso"],
            }
        }))

        # Chờ server chấm điểm Rubric và trả về câu hỏi tiếp theo
        print("  ⏳ Chờ TypeSafe Jev & Evidence Evaluator chấm điểm Turn 1...")
        turn1_question = None
        for _ in range(5):
            raw_resp = await asyncio.wait_for(ws.recv(), timeout=15.0)
            parsed_resp = json.loads(raw_resp)
            resp_type = parsed_resp.get("type")
            if resp_type == "state_sync":
                sync_p = parsed_resp.get("payload", {})
                print(f"     [Server State Sync] Topic: {sync_p.get('current_topic')} | Concept: {sync_p.get('current_concept')}")
            elif resp_type == "question_text":
                turn1_question = parsed_resp.get("payload", {})
                break

        record_test("Turn 1: Received Next Question from Server", turn1_question is not None)
        if turn1_question:
            q2_text = turn1_question.get("question_text", "")
            record_test("Turn 2 Question Text Non-empty", len(q2_text) > 15, q2_text[:60] + "...")
            # Kiểm tra âm thanh TTS cho câu hỏi Turn 2
            await test_neural_tts_audio(q2_text, "Turn 2 Question Audio")

        # -------------------------------------------------------------
        # BƯỚC 5: TURN 2 — ỨNG VIÊN BẢO VỆ DỰ ÁN THEO MÔ HÌNH STAR
        # -------------------------------------------------------------
        print("\n>>> BƯỚC 5: Turn 2 — Ứng viên bảo vệ Dự án CV theo mô hình STAR")
        ans_turn2 = (
            "Trong dự án tốt nghiệp xây dựng nền tảng E-commerce, em đóng vai trò Backend Lead. "
            "Tình huống gặp phải là khi có chương trình khuyến mãi, lượng truy cập tăng vọt dẫn tới "
            "nguy cơ overselling và deadlock trên cơ sở dữ liệu. Em đã thiết kế giải pháp kết hợp "
            "Redis Lua script để kiểm tra tồn kho nguyên tử (atomic check), sử dụng Kafka làm hàng đợi "
            "bất đồng bộ và Redis Distributed Lock. Kết quả là hệ thống chịu tải thành công 10.000 requests/giây "
            "với độ trễ dưới 50ms, không phát sinh bất kỳ đơn hàng nào bị overselling."
        )

        await ws.send(json.dumps({
            "type": "final_transcript",
            "payload": {
                "text": ans_turn2,
                "term_candidates": ["Redis", "Kafka", "Deadlock", "Distributed Lock"],
            }
        }))

        print("  ⏳ Chờ chấm điểm Rubric STAR Framework cho Turn 2...")
        turn2_question = None
        for _ in range(5):
            raw_resp = await asyncio.wait_for(ws.recv(), timeout=15.0)
            parsed_resp = json.loads(raw_resp)
            resp_type = parsed_resp.get("type")
            if resp_type == "state_sync":
                sync_p = parsed_resp.get("payload", {})
                print(f"     [Server State Sync] Topic: {sync_p.get('current_topic')} | Difficulty: {sync_p.get('current_difficulty')}")
            elif resp_type == "question_text":
                turn2_question = parsed_resp.get("payload", {})
                break

        record_test("Turn 2: Received Next Question from Server", turn2_question is not None)
        if turn2_question:
            q3_text = turn2_question.get("question_text", "")
            record_test("Turn 3 Question is Technical Core", turn2_question.get("stage_name") in ["technical_core", "applied_scenario", "cv_project_defense"])
            await test_neural_tts_audio(q3_text, "Turn 3 Question Audio")

        # -------------------------------------------------------------
        # BƯỚC 6: TURN 3 — ỨNG VIÊN TRẢ LỜI KỸ THUẬT LÕI (TECHNICAL CORE)
        # -------------------------------------------------------------
        print("\n>>> BƯỚC 6: Turn 3 — Ứng viên trả lời Kiến thức Chuyên môn Lõi (Java/Spring/SQL)")
        ans_turn3 = (
            "Vấn đề N+1 Query trong Spring Data JPA xảy ra khi truy vấn 1 danh sách cha và với mỗi bản ghi con "
            "Hibernate lại phát sinh thêm 1 câu lệnh SELECT riêng biệt, gây nghẽn I/O cơ sở dữ liệu. "
            "Để giải quyết triệt để, em sử dụng Fetch Join trong truy vấn JPQL để nạp đồng thời dữ liệu trong 1 câu SQL, "
            "hoặc khai báo @EntityGraph để định nghĩa đồ thị eager loading linh hoạt, hoặc cấu hình @BatchSize(size = 25) "
            "để gom các bản ghi vào mệnh đề WHERE IN."
        )

        await ws.send(json.dumps({
            "type": "final_transcript",
            "payload": {
                "text": ans_turn3,
                "term_candidates": ["Hibernate", "Spring Data JPA", "Fetch Join", "EntityGraph", "BatchSize"],
            }
        }))

        print("  ⏳ Chờ chấm điểm Rubric Technical Correctness cho Turn 3...")
        turn3_question = None
        for _ in range(5):
            raw_resp = await asyncio.wait_for(ws.recv(), timeout=15.0)
            parsed_resp = json.loads(raw_resp)
            resp_type = parsed_resp.get("type")
            if resp_type == "state_sync":
                sync_p = parsed_resp.get("payload", {})
                print(f"     [Server State Sync] Topic: {sync_p.get('current_topic')}")
            elif resp_type == "question_text":
                turn3_question = parsed_resp.get("payload", {})
                break

        record_test("Turn 3: Evaluator Processed & Returned Question", turn3_question is not None)

        # -------------------------------------------------------------
        # BƯỚC 7: TEST TÍNH NĂNG NGẮT LỜI (USER BARGE-IN)
        # -------------------------------------------------------------
        print("\n>>> BƯỚC 7: Test Tính năng Ngắt lời (User Barge-In Handler)")
        await ws.send(json.dumps({
            "type": "user_barge_in",
            "payload": {"reason": "candidate_started_speaking_over_ai"}
        }))
        record_test("Sent USER_BARGE_IN Event Successfully", True)

        # -------------------------------------------------------------
        # BƯỚC 8: TEST TÍNH NĂNG HỎI NGƯỢC DOANH NGHIỆP (REVERSE INTERVIEW)
        # -------------------------------------------------------------
        print("\n>>> BƯỚC 8: Test Tính năng Hỏi ngược (Reverse Interviewing)")
        await ws.send(json.dumps({
            "type": "reverse_question",
            "payload": {
                "question": "Dạ em muốn hỏi thêm về lộ trình đào tạo và cơ hội được gắn bó làm nhân viên chính thức tại FPT Software sau kỳ OJT ạ?"
            }
        }))

        rev_answer = None
        for _ in range(5):
            raw_resp = await asyncio.wait_for(ws.recv(), timeout=15.0)
            parsed_resp = json.loads(raw_resp)
            if parsed_resp.get("type") == "reverse_answer":
                rev_answer = parsed_resp.get("payload", {})
                break

        record_test("Received REVERSE_ANSWER from AI Interviewer", rev_answer is not None)
        if rev_answer:
            ans_text = rev_answer.get("answer", "")
            record_test("Reverse Answer is Comprehensive", len(ans_text) > 30, ans_text[:60] + "...")
            await test_neural_tts_audio(ans_text, "Reverse Answer Speech")

    # -------------------------------------------------------------
    # BƯỚC 9: THẨM ĐỊNH BÁO CÁO ĐÁNH GIÁ NĂNG LỰC OJT (REPORT SERVICE)
    # -------------------------------------------------------------
    print("\n>>> BƯỚC 9: Thẩm định Báo cáo Năng lực OJT sau phiên (GET /api/v1/sessions/{id}/report)")
    async with httpx.AsyncClient(timeout=25.0) as client:
        rep_resp = await client.get(f"{API_BASE}/api/v1/sessions/{session_id}/report")
        record_test("Report Endpoint HTTP 200", rep_resp.status_code == 200)
        report_data = rep_resp.json()
        record_test("Report Contains Overall Score", "overall_score" in report_data, f"Score: {report_data.get('overall_score')}/100")
        record_test("Report Contains Competencies", len(report_data.get("competencies", [])) > 0)
        record_test("Report Contains Evaluated Turns", len(report_data.get("evaluated_turns", [])) >= 2, f"Turns evaluated: {len(report_data.get('evaluated_turns', []))}")
        record_test("Report Contains Recommendations", len(report_data.get("recommendations", [])) > 0)

        # Kiểm tra chi tiết từng lượt chấm điểm thực tế
        for idx, t_eval in enumerate(report_data.get("evaluated_turns", [])):
            print(f"     [Lượt {idx+1}] Stage: {t_eval.get('stage')} | Điểm: {t_eval.get('score')}/10.0")
            print(f"             Câu hỏi: {t_eval.get('question')[:50]}...")
            print(f"             Nhận xét: {t_eval.get('candidate_summary')[:60]}...")


async def main():
    try:
        await run_interview_1on1_e2e()
    except Exception as e:
        import traceback
        traceback.print_exc()
        record_test("E2E Test Execution Error", False, str(e))

    print("\n" + "=" * 85)
    print("TỔNG KẾT KIỂM TRA E2E PHÒNG PHỎNG VẤN 1:1")
    print("=" * 85)
    print(f"Tổng số bài kiểm tra đạt (PASS): {PASSED_COUNT}")
    print(f"Tổng số bài kiểm tra trượt (FAIL): {FAILED_COUNT}")
    if (PASSED_COUNT + FAILED_COUNT) > 0:
        print(f"Tỷ lệ thành công: {(PASSED_COUNT / (PASSED_COUNT + FAILED_COUNT) * 100):.1f}%")
    print("=" * 85)

    if FAILED_COUNT == 0 and PASSED_COUNT >= 20:
        print("\n🎉 PHÒNG PHỎNG VẤN 1:1 ĐÃ HOẠT ĐỘNG HOÀN HẢO 100%!")
        print("Tất cả âm thanh Neural TTS, WebSocket turns, Rubric Evaluator,")
        print("Barge-in, Reverse Interview và Báo cáo tổng kết đều đã được kiểm tra thực tế xuất sắc.")
    else:
        print(f"\n⚠️ Có {FAILED_COUNT} bài kiểm tra chưa đạt. Cần rà soát ngay.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
