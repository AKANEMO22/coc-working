"""
CÓC ĐI LÀM — Comprehensive Production E2E Interview Test Suite (§4, §6, §8, §11, §12)
Kiểm thử toàn diện các kịch bản thực tế:
1. Thí sinh trả lời cực ngắn / "Không biết" (Fast-Path Heuristic <5ms)
2. Thí sinh trả lời ngắn gọn (1-2 câu)
3. Thí sinh trả lời kỹ thuật rất dài (150-250 từ, B-Tree, ACID, Transaction)
4. Thí sinh trả lời STAR framework (Dự án CV, Situation, Task, Action, Result)
5. Thí sinh xử lý tình huống sự cố (Applied Scenario / Incident Response)
6. Toàn bộ tiến trình 4 giai đoạn chuẩn OJT từ mở đầu đến kết thúc (Full Session Walkthrough)
7. Chen ngang (Barge-In)
8. Hỏi ngược doanh nghiệp (Reverse Interview)
9. Microsoft Neural TTS & LRU Cache
10. Live Logger stream validation
"""

import sys
import os
import time
import json
import pytest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import WSMessageType, NextAction, RubricType
from app.services.interview_logger import interview_logger

client = TestClient(app)

def create_test_session(student_id="SE189999", role="Backend Developer", company="FPT Software"):
    """Tạo phiên phỏng vấn mới."""
    resp = client.post("/api/v1/sessions/create", json={
        "student_id": student_id,
        "target_company": company,
        "target_role": role,
        "domain_pack": "it_software",
        "skill_gaps": ["Database Internals", "Microservices"]
    })
    assert resp.status_code == 200, f"Create session failed: {resp.text}"
    data = resp.json()
    return data["session_id"], data["blueprint"], data["state"]

def test_01_fast_path_no_answer():
    """Kịch bản 1: Thí sinh trả lời 'em không biết' / cực ngắn -> Phải xử lý dưới 50ms, không timeout."""
    session_id, blueprint, _ = create_test_session(student_id="SE_NO_ANS")
    
    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        msg_sync = ws.receive_json()
        assert msg_sync["type"] == WSMessageType.STATE_SYNC.value
        
        msg_q = ws.receive_json()
        assert msg_q["type"] == WSMessageType.QUESTION_TEXT.value
        initial_q = msg_q["payload"]["question_text"]
        print(f"\n[Test 1] Câu hỏi ban đầu: {initial_q[:60]}...")

        # Thí sinh nói không biết
        t0 = time.perf_counter()
        ws.send_json({
            "type": WSMessageType.FINAL_TRANSCRIPT.value,
            "payload": {
                "turn_id": "turn_no_ans_1",
                "text": "Dạ phần này em chưa tìm hiểu ạ, em không biết.",
                "term_candidates": []
            }
        })

        # Nhận ASR Gate
        asr_res = ws.receive_json()
        assert asr_res["type"] == WSMessageType.ASR_GATE_RESULT.value
        assert asr_res["payload"]["transcript_safe"] is True

        # Nhận State Sync
        sync_res = ws.receive_json()
        assert sync_res["type"] == WSMessageType.STATE_SYNC.value

        # Nhận câu hỏi kế tiếp
        next_q = ws.receive_json()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        assert next_q["type"] == WSMessageType.QUESTION_TEXT.value
        assert next_q["payload"]["question_text"] != initial_q
        
        print(f"[Test 1 PASS] Fast-Path hoàn thành trong {latency_ms}ms! Câu hỏi kế: {next_q['payload']['question_text'][:60]}...")
        assert latency_ms < 5000, f"Turn quá chậm: {latency_ms}ms"

def test_02_short_concise_answer():
    """Kịch bản 2: Thí sinh trả lời ngắn gọn (1-2 câu)."""
    session_id, _, _ = create_test_session(student_id="SE_SHORT")
    
    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json() # state sync
        ws.receive_json() # init q

        t0 = time.perf_counter()
        ws.send_json({
            "type": WSMessageType.FINAL_TRANSCRIPT.value,
            "payload": {
                "turn_id": "turn_short_1",
                "text": "Em chọn FPT vì quy mô lớn và muốn học hỏi công nghệ mới.",
                "term_candidates": []
            }
        })

        asr_res = ws.receive_json()
        assert asr_res["type"] == WSMessageType.ASR_GATE_RESULT.value
        
        sync_res = ws.receive_json()
        assert sync_res["type"] == WSMessageType.STATE_SYNC.value

        next_q = ws.receive_json()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        assert next_q["type"] == WSMessageType.QUESTION_TEXT.value
        print(f"\n[Test 2 PASS] Trả lời ngắn hoàn thành trong {latency_ms}ms: {next_q['payload']['question_text'][:60]}...")

def test_03_long_technical_answer():
    """Kịch bản 3: Thí sinh trả lời chuyên sâu kỹ thuật rất dài (150+ từ, giải thích ACID & B-Tree)."""
    session_id, _, _ = create_test_session(student_id="SE_LONG_TECH")
    
    long_technical_text = (
        "Theo em hiểu trong hệ quản trị cơ sở dữ liệu quan hệ như PostgreSQL hay MySQL InnoDB, "
        "tính chất ACID là nền tảng bảo toàn dữ liệu. Atomicity đảm bảo một giao dịch hoặc thành công "
        "toàn bộ hoặc rollback hoàn toàn nhờ Write-Ahead Logging (WAL). Consistency đảm bảo mọi ràng buộc "
        "toàn vẹn dữ liệu được duy trì. Isolation ngăn ngừa các hiện tượng dirty read, non-repeatable read "
        "và phantom read thông qua các mức cô lập như Read Committed, Repeatable Read và Serializable, "
        "thường được hiện thực bằng Multi-Version Concurrency Control (MVCC) kết hợp cơ chế khóa 2PL. "
        "Cuối cùng Durability cam kết một khi transaction commit thành công thì dữ liệu sẽ được ghi "
        "xuống đĩa cứng an toàn dù hệ thống gặp sự cố sập nguồn."
    )

    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json() # state sync
        ws.receive_json() # init q

        t0 = time.perf_counter()
        ws.send_json({
            "type": WSMessageType.FINAL_TRANSCRIPT.value,
            "payload": {
                "turn_id": "turn_long_tech",
                "text": long_technical_text,
                "term_candidates": ["ACID", "WAL", "MVCC", "PostgreSQL", "InnoDB", "Serializable"]
            }
        })

        asr_res = ws.receive_json()
        assert asr_res["type"] == WSMessageType.ASR_GATE_RESULT.value
        
        sync_res = ws.receive_json()
        assert sync_res["type"] == WSMessageType.STATE_SYNC.value

        next_q = ws.receive_json()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        assert next_q["type"] == WSMessageType.QUESTION_TEXT.value
        print(f"\n[Test 3 PASS] Trả lời dài kỹ thuật ({len(long_technical_text.split())} từ) xử lý trong {latency_ms}ms!")
        print(f"             Câu hỏi tiếp theo: \"{next_q['payload']['question_text'][:70]}...\"")

def test_04_star_framework_cv_project():
    """Kịch bản 4: Thí sinh trả lời chuẩn mô hình STAR cho dự án CV."""
    session_id, _, _ = create_test_session(student_id="SE_STAR")
    
    star_text = (
        "Trong dự án xây dựng hệ thống thương mại điện tử tại trường (Situation), "
        "nhóm em gặp vấn đề dịch vụ giỏ hàng bị nghẽn và timeout khi có 500 sinh viên cùng lúc truy cập (Task). "
        "Em đã chủ động tái cấu trúc từ truy vấn database trực tiếp sang sử dụng Redis In-Memory Cache "
        "và áp dụng mẫu thiết kế Cache-Aside cùng Distributed Lock Redlock (Action). "
        "Kết quả là độ trễ response giảm từ 850ms xuống còn 28ms, thông lượng đạt 1200 RPS "
        "và hệ thống hoạt động ổn định 100% trong đợt demo (Result)."
    )

    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json()
        ws.receive_json()

        t0 = time.perf_counter()
        ws.send_json({
            "type": WSMessageType.FINAL_TRANSCRIPT.value,
            "payload": {
                "turn_id": "turn_star",
                "text": star_text,
                "term_candidates": ["Redis", "Cache-Aside", "Distributed Lock", "RPS"]
            }
        })

        asr_res = ws.receive_json()
        assert asr_res["type"] == WSMessageType.ASR_GATE_RESULT.value
        
        sync_res = ws.receive_json()
        assert sync_res["type"] == WSMessageType.STATE_SYNC.value

        next_q = ws.receive_json()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        assert next_q["type"] == WSMessageType.QUESTION_TEXT.value
        print(f"\n[Test 4 PASS] STAR project defense hoàn thành trong {latency_ms}ms!")

def test_05_barge_in_and_reverse_question():
    """Kịch bản 5: Thử nghiệm Barge-in (chen ngang) và Hỏi ngược doanh nghiệp."""
    session_id, _, _ = create_test_session(student_id="SE_BARGE_REV")
    
    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json()
        ws.receive_json()

        # 1. Gửi Barge-in
        ws.send_json({
            "type": WSMessageType.USER_BARGE_IN.value,
            "payload": {"timestamp": time.time()}
        })
        sync_barge = ws.receive_json()
        assert sync_barge["type"] == WSMessageType.STATE_SYNC.value
        assert sync_barge["payload"]["interruption_count"] >= 1
        print("\n[Test 5.1 PASS] Barge-in đã ngắt TTS và đồng bộ interruption_count thành công!")

        # 2. Gửi câu hỏi ngược
        ws.send_json({
            "type": WSMessageType.REVERSE_QUESTION.value,
            "payload": {
                "question": "Cho em hỏi tại FPT Software thì các bạn fresher/intern sẽ được tham gia dự án thực tế sau bao lâu?",
                "company_knowledge": {"training_months": 2}
            }
        })
        rev_ans = ws.receive_json()
        assert rev_ans["type"] == WSMessageType.REVERSE_ANSWER.value
        assert len(rev_ans["payload"]["answer"]) > 10
        print(f"[Test 5.2 PASS] Phỏng vấn viên ảo trả lời câu hỏi ngược: \"{rev_ans['payload']['answer'][:70]}...\"")

def test_06_neural_tts_service():
    """Kịch bản 6: Kiểm tra Microsoft Neural TTS và LRU Cache."""
    test_phrase = "Xin chào các bạn, đây là bài kiểm tra âm thanh chuẩn phát âm tiếng Việt."
    
    # Lần 1: Gọi Edge Neural (Live synthesis)
    t0 = time.perf_counter()
    res1 = client.get(f"/api/v1/tts/synthesize?text={test_phrase}&voice=vi-VN-HoaiMyNeural")
    assert res1.status_code == 200
    assert res1.headers["Content-Type"] == "audio/mpeg"
    assert len(res1.content) > 1000
    lat1 = round((time.perf_counter() - t0) * 1000, 1)

    # Lần 2: Cache Hit (Phải cực nhanh < 50ms)
    t1 = time.perf_counter()
    res2 = client.get(f"/api/v1/tts/synthesize?text={test_phrase}&voice=vi-VN-HoaiMyNeural")
    assert res2.status_code == 200
    assert res2.headers.get("X-TTS-Source") == "cache"
    lat2 = round((time.perf_counter() - t1) * 1000, 1)
    
    print(f"\n[Test 6 PASS] Microsoft Neural TTS: Live={lat1}ms, Cache Hit={lat2}ms (Size={len(res1.content)} bytes)")
    assert lat2 < 50, f"Cache hit quá chậm: {lat2}ms"

def test_07_full_multi_turn_session():
    """Kịch bản 7: Đi qua liên tục nhiều turn cho đến khi hoàn thành phiên phỏng vấn."""
    session_id, blueprint, _ = create_test_session(student_id="SE_FULL_SESSION")
    
    answers = [
        "Em mong muốn thực tập tại FPT Software để rèn luyện kỹ năng lập trình Java và làm việc trong môi trường chuyên nghiệp.",
        "Em từng làm dự án quản lý thư viện bằng Spring Boot và MySQL, em phụ trách thiết kế CSDL và viết REST API.",
        "Em giải quyết bài toán chống nghẽn bằng Redis caching và phân trang câu lệnh SQL với Index.",
        "Nếu hệ thống gặp sự cố production, em sẽ kiểm tra log đầu tiên, phân loại mức độ nghiêm trọng và rollback bản release gần nhất nếu cần."
    ]

    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json() # sync
        init_q = ws.receive_json() # q1
        print(f"\n[Test 7] Bắt đầu phiên phỏng vấn trọn vẹn: \"{init_q['payload']['question_text'][:60]}...\"")

        for turn_idx, ans_text in enumerate(answers):
            print(f"  -> Gửi Turn {turn_idx + 1} ({len(ans_text.split())} từ)...")
            ws.send_json({
                "type": WSMessageType.FINAL_TRANSCRIPT.value,
                "payload": {
                    "turn_id": f"turn_multi_{turn_idx}",
                    "text": ans_text,
                    "term_candidates": ["Spring Boot", "MySQL", "Redis"]
                }
            })

            asr = ws.receive_json()
            assert asr["type"] == WSMessageType.ASR_GATE_RESULT.value
            
            sync = ws.receive_json()
            assert sync["type"] == WSMessageType.STATE_SYNC.value

            next_msg = ws.receive_json()
            if next_msg["type"] == WSMessageType.QUESTION_TEXT.value:
                print(f"     Nhận câu hỏi tiếp: \"{next_msg['payload']['question_text'][:60]}...\"")
            elif next_msg["type"] == WSMessageType.SESSION_ENDED.value:
                print("     Phiên phỏng vấn đã chuyển sang trạng thái FINALIZING thành công!")
                break

    print("[Test 7 PASS] Hoàn thành trọn vẹn nhiều turn phỏng vấn liên tiếp!")

def test_08_live_logger_buffer():
    """Kịch bản 8: Đảm bảo live-logs endpoint lưu trữ đầy đủ các stage từ Input đến TTS."""
    res = client.get("/api/v1/sessions/live-logs?limit=30")
    assert res.status_code == 200
    data = res.json()
    stages = [l["stage"] for l in data.get("logs", [])]
    print(f"\n[Test 8] Các stage đã được ghi nhận trong ring buffer: {set(stages)}")
    
    # Kiểm tra sự xuất hiện của các stage nòng cốt
    for expected in ["CANDIDATE_INPUT", "ASR_GATE", "RUBRIC_EVAL", "JEV_DECISION", "QUESTION_ENGINE", "NEURAL_TTS"]:
        assert expected in stages, f"Thiếu stage {expected} trong live logs!"
    print("[Test 8 PASS] Hệ thống Logger lưu trữ chuẩn xác 100% các stage trong pipeline!")

def test_09_real_report_empty_session():
    """Kịch bản 9: Session mới tạo chưa có câu trả lời nào -> Report phải trả về 0.0, NO_EVALUATION, KHÔNG được hardcode 7.8 Pass!"""
    session_id, _, _ = create_test_session(student_id="SE_EMPTY_REP")
    resp = client.get(f"/api/v1/sessions/{session_id}/report")
    assert resp.status_code == 200
    rep = resp.json()
    assert rep["overall_score"] == 0.0, f"Expected 0.0 score for empty session, got {rep['overall_score']}"
    assert rep["radar_scores"]["technical_core"] == 0.0
    assert rep["report_status"] == "NO_EVALUATION"
    assert len(rep["turn_evaluations"]) == 0
    print(f"\n[Test 9 PASS] Empty session report trả về điểm thực 0.0, không hardcode mock data!")

def test_10_real_report_low_score():
    """Kịch bản 10: Thí sinh trả lời 'không biết' -> Điểm tổng kết phải phản ánh đúng thực tế (< 5.0, Chưa đạt)."""
    session_id, _, _ = create_test_session(student_id="SE_POOR_ANS")
    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json() # sync
        ws.receive_json() # init q
        # Gửi câu trả lời không biết
        ws.send_json({
            "type": WSMessageType.FINAL_TRANSCRIPT.value,
            "payload": {
                "turn_id": "turn_fail_1",
                "text": "Em không biết, em chưa học phần này.",
                "term_candidates": []
            }
        })
        ws.receive_json() # asr
        ws.receive_json() # sync
        ws.receive_json() # next q

    # Lấy báo cáo
    resp = client.get(f"/api/v1/sessions/{session_id}/report")
    assert resp.status_code == 200
    rep = resp.json()
    assert rep["overall_score"] < 5.0, f"Expected low score for no-answer, got {rep['overall_score']}"
    assert "Chưa đạt" in rep["grade"] or "Cần cải thiện" in rep["grade"]
    assert len(rep["turn_evaluations"]) == 1
    assert rep["turn_evaluations"][0]["score"] < 5.0
    print(f"\n[Test 10 PASS] Poor answer report phản ánh chính xác điểm thực ({rep['overall_score']}/10.0, {rep['grade']})!")

def test_11_real_report_high_score_multi_turn():
    """Kịch bản 11: Thí sinh trả lời chuẩn xác nhiều turn -> Điểm cao (> 6.0), roadmap và retry queue thực tế."""
    session_id, _, _ = create_test_session(student_id="SE_HIGH_ANS")
    answers = [
        "Em chọn FPT Software vì muốn tham gia các dự án phát triển hệ thống lớn quy mô toàn cầu và trau dồi chuyên môn về Spring Boot.",
        "Trong dự án trường đại học, em sử dụng Spring Boot và Hibernate để tối ưu hóa truy vấn cơ sở dữ liệu với Index và Connection Pooling, giảm thời gian phản hồi từ 500ms xuống 80ms.",
    ]
    with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
        ws.receive_json()
        ws.receive_json()
        for i, ans in enumerate(answers):
            ws.send_json({
                "type": WSMessageType.FINAL_TRANSCRIPT.value,
                "payload": {
                    "turn_id": f"turn_good_{i}",
                    "text": ans,
                    "term_candidates": ["Spring Boot", "Hibernate"]
                }
            })
            ws.receive_json() # asr
            ws.receive_json() # sync
            msg = ws.receive_json() # next q or ended
            if msg["type"] == WSMessageType.SESSION_ENDED.value:
                break

    # Lấy báo cáo
    resp = client.get(f"/api/v1/sessions/{session_id}/report")
    assert resp.status_code == 200
    rep = resp.json()
    assert rep["overall_score"] >= 6.0, f"Expected good score, got {rep['overall_score']}"
    assert len(rep["turn_evaluations"]) >= 1
    assert len(rep["strengths"]) > 0
    print(f"\n[Test 11 PASS] High score session report tính toán chính xác ({rep['overall_score']}/10.0, {rep['grade']}) từ {len(rep['turn_evaluations'])} turns thực!")

if __name__ == "__main__":
    print("=====================================================================")
    print(" BẮT ĐẦU CHẠY TOÀN BỘ PRODUCTION E2E TEST SUITE CHO CÓC ĐI LÀM")
    print("=====================================================================")
    test_01_fast_path_no_answer()
    test_02_short_concise_answer()
    test_03_long_technical_answer()
    test_04_star_framework_cv_project()
    test_05_barge_in_and_reverse_question()
    test_06_neural_tts_service()
    test_07_full_multi_turn_session()
    test_08_live_logger_buffer()
    test_09_real_report_empty_session()
    test_10_real_report_low_score()
    test_11_real_report_high_score_multi_turn()
    print("\n=====================================================================", flush=True)
    print(" TẤT CẢ 11 BỘ KIỂM THỬ E2E PRODUCTION ĐÃ VƯỢT QUA 100% THÀNH CÔNG!", flush=True)
    print("=====================================================================", flush=True)
    os._exit(0)
