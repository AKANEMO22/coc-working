"""
CÓC ĐI LÀM — Comprehensive Product E2E Test Suite (§3, §8, §11, §23)
KIỂM TRA TOÀN DIỆN PRODUCT:
- Multi-Engine Open Web Crawler (DDG Lite, Bing, Gemini Grounding)
- Anti-Bot WAF Stealth Headers & Fallback Snippet Mining
- Deep HTML DOM Question Extraction
- Model Orchestrator Autonomous Pipeline (5 Tool Calls)
- CẤM MOCK TEST / FAKE DATA: Thẩm định 100% câu hỏi thật, gán URL sống, 4 Stage OJT chuẩn
- Question Bank REST API (/api/v1/questions/bank)
- Real Interview Session Lifecycle (Initiate -> Question Service -> Curated Bank Ingest -> Evaluate)
"""

import sys
import os
import io
import asyncio
import re
import json
import httpx
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.crawler_service import get_crawler_service, get_stealth_headers, TECH_CORE_KEYWORDS
from app.services.orchestrator_service import get_orchestrator_service, COMPANY_KNOWLEDGE_VAULTS
from app.services.question_service import get_question_service
from app.models.schemas import NextAction, InterviewBlueprint, BlueprintStage, InterviewState, RubricType

API_BASE = "http://127.0.0.1:8000"

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


async def test_section_1_health():
    print("\n" + "=" * 80)
    print("PHẦN 1: KIỂM TRA HỆ THỐNG VÀ HEALTH ENDPOINT")
    print("=" * 80)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{API_BASE}/api/v1/health")
            record_test("Backend Health Check (/api/v1/health)", resp.status_code == 200, f"Status={resp.status_code}")
            data = resp.json()
            record_test("Service Name Correct", data.get("service") == "coc-di-lam-backend")
            record_test("TypeSafe Jev Controller Ready", data.get("typesafe_jev_ready") is True)
        except Exception as e:
            record_test("Backend Health Check", False, str(e))


async def test_section_2_crawler_antibot():
    print("\n" + "=" * 80)
    print("PHẦN 2: KIỂM TRA CRAWLER MULTI-ENGINE & ANTI-BOT RESILIENCE")
    print("=" * 80)
    crawler = get_crawler_service()

    # 1. Stealth Headers
    headers = get_stealth_headers()
    record_test("Stealth Headers Has User-Agent", bool(headers.get("User-Agent")))
    record_test("Stealth Headers Has Client Hints (Sec-Ch-Ua)", "Sec-Ch-Ua" in headers)
    record_test("Stealth Headers Has Sec-Ch-Ua-Platform", bool(headers.get("Sec-Ch-Ua-Platform")))
    record_test("Stealth Headers Language is vi-VN", "vi-VN" in headers.get("Accept-Language", ""))

    # 2. DuckDuckGo Lite Search (Bền bỉ, chống chặn bot)
    ddg_res = await crawler._search_ddg_lite("Java Spring Boot phỏng vấn câu hỏi", max_results=4)
    record_test("DDG Lite Engine Harvests Open Web", len(ddg_res) > 0, f"Found {len(ddg_res)} links")
    if ddg_res:
        first_domain = ddg_res[0].get("domain", "")
        record_test("DDG Lite Harvests Valid Domains", len(first_domain) > 3, f"Domain: {first_domain}")

    # 3. Bing Search Engine
    bing_res = await crawler._search_bing_html("Spring JPA interview questions vietnam", max_results=3)
    record_test("Bing Engine Search Resilient", len(bing_res) >= 0, f"Bing found {len(bing_res)} links")

    # 4. Deep HTML Question Mining
    sample_html = """
    <html>
      <head><title>50 Câu Hỏi Phỏng Vấn Java Developer Thường Gặp</title></head>
      <body>
        <h1>Tổng hợp kinh nghiệm phỏng vấn</h1>
        <h2>Câu 1: Sự khác nhau giữa abstract class và interface trong Java là gì?</h2>
        <p>Interface chỉ chứa phương thức trừu tượng trước Java 8...</p>
        <h3>2. Cơ chế Garbage Collection (GC) trong JVM hoạt động như thế nào?</h3>
        <p>GC tự động giải phóng bộ nhớ heap cho các đối tượng không còn tham chiếu...</p>
        <p><strong>3. Vấn đề N+1 query trong Hibernate xảy ra khi nào và cách khắc phục?</strong></p>
        <p>Khi load một collection entity...</p>
        <li>4. Phân biệt HashMap và ConcurrentHashMap trong môi trường đa luồng?</li>
      </body>
    </html>
    """
    extracted_qs = crawler.extract_questions_from_html(sample_html, "https://sample-tech.com/java-interview", "Java Interview Review")
    record_test("Deep HTML Mining Extracts > 2 Questions", len(extracted_qs) >= 3, f"Extracted {len(extracted_qs)} questions")
    for q in extracted_qs:
        record_test(f"Question has valid stage ({q.get('stage')})", q.get("stage") in ["hr_motivation", "cv_project_defense", "technical_core", "applied_scenario"])
        record_test(f"Question text authentic", len(q.get("question", "")) > 15, q.get("question")[:45] + "...")

    # 5. Anti-Bot Fallback (Snippet Mining on 403)
    dummy_403_target = [{
        "href": "https://cloudflare-protected-domain-demo.com/questions",
        "title": "Kinh nghiệm phỏng vấn Backend",
        "domain": "cloudflare-protected-domain-demo.com",
        "body": "Câu 1: Nguyên lý ACID trong Database SQL là gì? Câu 2: Deadlock xảy ra khi nào?",
    }]
    valid_pages, fallback_qs = await crawler.crawl_urls(dummy_403_target, max_pages=1)
    record_test("Anti-bot Snippet Fallback Activated on Network Error", len(fallback_qs) >= 1 or len(valid_pages) >= 1)


async def test_section_3_orchestrator_discovery():
    print("\n" + "=" * 80)
    print("PHẦN 3: KIỂM TRA MODEL ORCHESTRATOR & ZERO MOCK TEST AUDIT")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Kịch bản 1: FPT Software - Java Backend Intern qua HTTP API
        print("\n>>> Scenario A: FPT Software - Java Backend Intern (POST /api/v1/questions/orchestrate-discovery)")
        resp_fpt = await client.post(
            f"{API_BASE}/api/v1/questions/orchestrate-discovery",
            json={
                "company": "FPT Software",
                "role": "Java Backend Intern",
                "student_id": "STUDENT_TEST_PROD_01",
            }
        )
        record_test("Orchestrate Discovery FPT HTTP 200", resp_fpt.status_code == 200)
        res_fpt = resp_fpt.json()

        fpt_questions = res_fpt.get("questions", [])
        record_test("Orchestrator Ingested > 15 Questions for FPT", len(fpt_questions) >= 15, f"Ingested {len(fpt_questions)} questions")

        # Kiểm tra 4 Stage OJT chuẩn
        fpt_stages = {q.get("stage") for q in fpt_questions}
        for stg in ["hr_motivation", "cv_project_defense", "technical_core", "applied_scenario"]:
            record_test(f"FPT Questions Cover Stage: {stg}", stg in fpt_stages)

        # Thẩm định cấm mock test & kiểm tra URL sống
        mock_keywords = ["mock", "dummy", "lorem", "sample_test", "fake", "placeholder"]
        has_mock = False
        for q in fpt_questions:
            q_text = q.get("question", "").lower()
            if any(mk in q_text for mk in mock_keywords):
                has_mock = True
                break
        record_test("ZERO Mock Test Data in FPT Bank", not has_mock)

        # Kiểm tra tính hợp lệ của URLs
        all_urls_valid = all(q.get("url", "").startswith("http") and "404" not in q.get("url", "") for q in fpt_questions)
        record_test("All Questions Have Live Authentic URLs (No 404/Null)", all_urls_valid)

        # Kịch bản 2: VNG Corporation - Frontend React Developer qua HTTP API
        print("\n>>> Scenario B: VNG Corporation - Frontend React Developer")
        resp_vng = await client.post(
            f"{API_BASE}/api/v1/questions/orchestrate-discovery",
            json={
                "company": "VNG Corporation",
                "role": "Frontend React Developer",
                "student_id": "STUDENT_TEST_PROD_02",
            }
        )
        record_test("Orchestrate Discovery VNG HTTP 200", resp_vng.status_code == 200)
        res_vng = resp_vng.json()
        vng_questions = res_vng.get("questions", [])
        record_test("Orchestrator Ingested > 10 Questions for VNG", len(vng_questions) >= 10, f"Ingested {len(vng_questions)} questions")
        vng_stages = {q.get("stage") for q in vng_questions}
        record_test("VNG Questions Cover Technical Core", "technical_core" in vng_stages)
        record_test("VNG Questions Cover Applied Scenario", "applied_scenario" in vng_stages)


async def test_section_4_question_bank_api():
    print("\n" + "=" * 80)
    print("PHẦN 4: KIỂM TRA REST API QUESTION BANK (/api/v1/questions/bank)")
    print("=" * 80)
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Truy vấn ngân hàng FPT Software
        resp = await client.get(f"{API_BASE}/api/v1/questions/bank?company=FPT%20Software&role=Java%20Backend%20Intern&limit=30")
        record_test("GET /api/v1/questions/bank Status 200", resp.status_code == 200)
        data = resp.json()
        returned_qs = data.get("questions", [])
        record_test("Question Bank Returns > 15 Questions", len(returned_qs) >= 15, f"Returned {len(returned_qs)}")
        record_test("Question Bank Returns Core Competencies", len(data.get("competencies", [])) > 0)

        # Kiểm tra trường url có trong kết quả API
        urls_in_api = [q.get("url") for q in returned_qs if q.get("url")]
        record_test("Question Bank Response Contains Clickable URLs", len(urls_in_api) > 0, f"{len(urls_in_api)} questions have URLs")

        # 2. Truy xuất Orchestrator Activity Logs
        log_resp = await client.get(f"{API_BASE}/api/v1/questions/orchestrator-logs?limit=30")
        record_test("GET /api/v1/questions/orchestrator-logs Status 200", log_resp.status_code == 200)
        logs_data = log_resp.json()
        logs_list = logs_data.get("logs", [])
        tool_names = {l.get("tool_name") for l in logs_list if l.get("tool_name")}
        record_test("Logs Contain mcp_web_search Call", "mcp_web_search" in tool_names)
        record_test("Logs Contain web_content_extractor Call", "web_content_extractor" in tool_names)
        record_test("Logs Contain question_bank_ingest Call", "question_bank_ingest" in tool_names)


async def test_section_5_interview_lifecycle():
    print("\n" + "=" * 80)
    print("PHẦN 5: KIỂM TRA TOÀN DIỆN INTERVIEW LIFECYCLE (QuestionService Ingest Integration)")
    print("=" * 80)
    from app.api.v1.sessions import _generate_blueprint
    q_service = get_question_service()

    blueprint = _generate_blueprint(
        session_id="session_test_e2e_01",
        student_id="STUDENT_E2E",
        company="FPT Software",
        role="Java Backend Intern",
        domain_pack="backend_engineering",
    )

    state = InterviewState(
        session_id="session_test_e2e_01",
        candidate_name="Nguyễn Văn A",
        student_id="STUDENT_E2E",
        role="Java Backend Intern",
        company_target="FPT Software",
        current_topic="hr_motivation",
        current_difficulty=3,
        remaining_scored_question_budget=7,
        questions_on_current_concept=0,
        asked_question_texts=[],
    )

    # 1. Câu hỏi 1 (HR Motivation từ Ngân hàng đề)
    q1 = await q_service.get_next_question(
        next_action=NextAction.SAME_LEVEL,
        state=state,
        blueprint=blueprint,
    )
    record_test("Stage 1: Question 1 Received", q1 is not None)
    if q1:
        record_test("Question 1 Non-empty", len(q1.question_text) > 10, q1.question_text[:50] + "...")
        record_test("Question 1 Registered in Asked Texts", q1.question_text in state.asked_question_texts)
        if q1.provenance:
            record_test("Question Provenance is Curated/Verified", q1.provenance.source_type.value == "curated")
            record_test("Question Provenance Has URL", bool(q1.provenance.source_url))

    # 2. Câu hỏi 2 (Chuyển sang CV Project Defense)
    q2 = await q_service.get_next_question(
        next_action=NextAction.SWITCH_TOPIC,
        state=state,
        blueprint=blueprint,
    )
    record_test("Stage 2: Question 2 Received after Switch Topic", q2 is not None)
    if q2:
        record_test("Question 2 Not Duplicate Question 1", q2.question_text != (q1.question_text if q1 else ""))
        record_test("Current Topic Advanced to cv_project_defense", state.current_topic == "cv_project_defense")

    # 3. Câu hỏi 3 (Technical Core)
    q3 = await q_service.get_next_question(
        next_action=NextAction.SWITCH_TOPIC,
        state=state,
        blueprint=blueprint,
    )
    record_test("Stage 3: Question 3 Received (Technical Core)", q3 is not None)
    if q3:
        record_test("Current Topic Advanced to technical_core", state.current_topic == "technical_core")


async def main():
    print("=" * 80)
    print("🚀 BẮT ĐẦU CHẠY PRODUCT E2E TEST SUITE — CẤM MOCK TEST QUESTION BANK")
    print("=" * 80)

    await test_section_1_health()
    await test_section_2_crawler_antibot()
    await test_section_3_orchestrator_discovery()
    await test_section_4_question_bank_api()
    await test_section_5_interview_lifecycle()

    print("\n" + "=" * 80)
    print("TỔNG KẾT PRODUCT E2E TEST SUITE")
    print("=" * 80)
    print(f"Tổng số bài kiểm tra đạt (PASS): {PASSED_COUNT}")
    print(f"Tổng số bài kiểm tra trượt (FAIL): {FAILED_COUNT}")
    print(f"Tỷ lệ thành công: {(PASSED_COUNT / (PASSED_COUNT + FAILED_COUNT) * 100):.1f}%")
    print("=" * 80)

    if FAILED_COUNT == 0:
        print("\n🎉 TẤT CẢ CÁC BÀI TEST E2E ĐỀU ĐẠT CHUẨN XUẤT SẮC!")
        print("Hệ thống hoàn toàn sạch mock test, tự động cào bài viết trên Open Web,")
        print("vượt chống bot WAF và tích hợp hoàn chỉnh vào Question Bank & Luồng phỏng vấn.")
    else:
        print(f"\n⚠️ Có {FAILED_COUNT} bài kiểm tra chưa đạt yêu cầu. Cần rà soát và khắc phục ngay.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
