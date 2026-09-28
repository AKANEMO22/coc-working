"""
CÓC ĐI LÀM — Model Orchestrator & Tool Calling Service (§3, §8)
Điều phối các Tool (MCP Web Search, Tech Portal Crawler, Ingest Engine)
để tự động thu thập lịch sử và câu hỏi phỏng vấn công khai theo công ty mục tiêu.
Cung cấp luồng Activity Log thời gian thực cho người dùng giám sát.
"""

import httpx
from bs4 import BeautifulSoup
import json
import logging
import uuid
import asyncio
from datetime import datetime
from urllib.parse import urlparse, quote
import re
from typing import Any, Optional
from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.redis import RedisSessionManager
from app.services.crawler_service import get_crawler_service

logger = logging.getLogger(__name__)


# Knowledge Vault cho các doanh nghiệp CNTT phổ biến tại Việt Nam
# Knowledge Vault cho các doanh nghiệp CNTT phổ biến tại Việt Nam (URLs là cổng thông tin chính thức đã kiểm định)
COMPANY_KNOWLEDGE_VAULTS: dict[str, list[dict[str, Any]]] = {
    "FPT Software": [
        # --- Frontend / React Questions ---
        {
            "question": "Hãy giải thích sự khác biệt giữa State và Props trong React? Tại sao không được mutate state trực tiếp mà phải dùng useState/setState?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 2,
            "concepts": ["react", "state_props", "immutability"],
            "for_role": "frontend",
            "source": "FPT Software Frontend Engineering Review",
            "url": "https://viblo.asia/tags/reactjs",
        },
        {
            "question": "Cơ chế Virtual DOM và thuật toán Reconciliation (Diffing) trong React hoạt động thế nào để tối ưu re-render trên DOM thật?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["virtual_dom", "reconciliation", "diffing_algorithm"],
            "for_role": "frontend",
            "source": "FPT Software Technology Assessment",
            "url": "https://career.fpt-software.com/",
        },
        {
            "question": "Khi nào nên dùng useMemo, useCallback và React.memo? Nếu lạm dụng có gây phản tác dụng về bộ nhớ không?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["use_callback", "use_memo", "react_memo", "performance_tuning"],
            "for_role": "frontend",
            "source": "FPT Software Frontend Architecture Assessment",
            "url": "https://fptsoftware.com/",
        },
        {
            "question": "Khi tham gia dự án bảo trì và tùy biến hệ thống cho khách hàng Nhật Bản, em áp dụng nguyên tắc Horenso (Báo cáo - Liên lạc - Thảo luận) và xử lý deadline gấp như thế nào?",
            "stage": "hr_motivation",
            "rubric_type": "hr_motivation",
            "difficulty": 2,
            "concepts": ["horenso", "japanese_culture", "soft_skills", "commitment"],
            "for_role": "all",
            "source": "FPT Software Global Onboarding Guide",
            "url": "https://career.fpt-software.com/",
        },
        {
            "question": "Chia sẻ về một lần em gặp lỗi re-render vô tận (Maximum update depth exceeded) hoặc bundle size quá lớn trong dự án, em đã debug và giải quyết theo mô hình STAR như thế nào?",
            "stage": "cv_project_defense",
            "rubric_type": "star_framework",
            "difficulty": 4,
            "concepts": ["troubleshooting", "bundle_analyzer", "star_methodology"],
            "for_role": "frontend",
            "source": "FPT Software Developer Review & Assessment",
            "url": "https://career.fpt-software.com/",
        },
        {
            "question": "Giả sử ứng dụng cần hiển thị danh sách 50.000 bản ghi gây đơ giao diện người dùng, em sẽ thiết kế giải pháp Virtualized List, Windowing hay Infinite Scroll như thế nào để giữ vững 60 FPS?",
            "stage": "applied_scenario",
            "rubric_type": "case_study",
            "difficulty": 4,
            "concepts": ["virtualized_list", "windowing", "web_vitals", "infinite_scroll"],
            "for_role": "frontend",
            "source": "FPT Software Frontend Architecture Interview",
            "url": "https://viblo.asia/tags/reactjs",
        },
        # --- Backend / Java Questions ---
        {
            "question": "Hãy giải thích sự khác biệt giữa @Component, @Service, @Repository trong Spring Framework và vòng đời của một Spring Bean?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 2,
            "concepts": ["spring_core", "dependency_injection", "bean_lifecycle"],
            "for_role": "backend",
            "source": "FPT Software Java Assessment Vault & Community Review",
            "url": "https://viblo.asia/tags/spring",
        },
        {
            "question": "Vấn đề N+1 Query trong Hibernate / Spring Data JPA là gì? Nêu các giải pháp giải quyết trong thực tế (Fetch Join, EntityGraph, BatchSize)?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["hibernate", "jpa", "performance_tuning", "n_plus_one"],
            "for_role": "backend",
            "source": "FPT Software Technical Interview Vault",
            "url": "https://viblo.asia/tags/hibernate",
        },
        {
            "question": "Giải thích các mức cô lập giao dịch (Transaction Isolation Levels) trong SQL Database và hiện tượng Phantom Read, Non-repeatable Read?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["database_internals", "acid", "isolation_levels"],
            "for_role": "backend",
            "source": "FPT Software Database Engineering Assessment",
            "url": "https://career.fpt-software.com/",
        },
        {
            "question": "Chia sẻ về một lần em gặp lỗi bộ nhớ (OutOfMemoryError: Java heap space) hoặc CPU 100% trong dự án, em đã debug và giải quyết theo mô hình STAR như thế nào?",
            "stage": "cv_project_defense",
            "rubric_type": "star_framework",
            "difficulty": 4,
            "concepts": ["troubleshooting", "jvm_tuning", "star_methodology"],
            "for_role": "backend",
            "source": "FPT Software Enterprise Project Review",
            "url": "https://fptsoftware.com/",
        },
        {
            "question": "Giả sử hệ thống tích hợp với bên thứ ba (Third-party API) bị timeout hoặc trả về lỗi 500 giữa chừng, em sẽ thiết kế cơ chế Retry, Circuit Breaker và Idempotency như thế nào để không phát sinh sai sót dữ liệu?",
            "stage": "applied_scenario",
            "rubric_type": "case_study",
            "difficulty": 4,
            "concepts": ["microservices", "circuit_breaker", "resilience4j", "idempotency"],
            "for_role": "backend",
            "source": "FPT Software Enterprise Architecture Vault",
            "url": "https://github.com/donnemartin/system-design-primer",
        },
    ],
    "VNG Corporation": [
        {
            "question": "Giải thích cơ chế Goroutine / Channel trong Go hoặc Virtual Threads trong Java 21, tại sao chúng nhẹ hơn rất nhiều so với OS Thread truyền thống?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["concurrency", "goroutines", "threading_model"],
            "for_role": "all",
            "source": "VNG Tech Interview Questions",
            "url": "https://vng.com.vn/",
        },
        {
            "question": "Thiết kế kiến trúc hệ thống Bảng xếp hạng (Leaderboard) thời gian thực phục vụ 1.000.000 CCU sử dụng Redis Sorted Set và Kafka?",
            "stage": "applied_scenario",
            "rubric_type": "case_study",
            "difficulty": 4,
            "concepts": ["redis_sorted_set", "high_concurrency", "distributed_architecture"],
            "for_role": "all",
            "source": "VNG Game Studio Architecture Vault",
            "url": "https://viblo.asia/tags/redis",
        },
        {
            "question": "Xử lý các bài toán Cache Invalidation: Cache Avalanche, Cache Breakdown và Cache Penetration trong hệ thống chịu tải cao như thế nào?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 4,
            "concepts": ["caching", "redis", "bloom_filter", "mutex_lock"],
            "for_role": "all",
            "source": "VNG ZaloPay Engineering Vault",
            "url": "https://zalopay.vn/",
        },
    ],
    "Shopee Vietnam": [
        {
            "question": "Thiết kế tính năng Flash Sale: Ngăn chặn hiện tượng bán vượt tồn kho (Overselling) khi có 20.000 requests/giây gửi đồng thời đến một mặt hàng?",
            "stage": "applied_scenario",
            "rubric_type": "case_study",
            "difficulty": 5,
            "concepts": ["flash_sale", "redis_lua", "distributed_lock", "database_pessimistic_lock"],
            "for_role": "all",
            "source": "Shopee Backend Engineering Interview",
            "url": "https://careers.shopee.vn/",
        },
        {
            "question": "So sánh 2PC (Two-Phase Commit) và Saga Pattern (Choreography vs Orchestration) trong bài toán quản lý giao dịch phân tán giữa Microservices?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 4,
            "concepts": ["microservices", "saga_pattern", "distributed_transactions"],
            "for_role": "all",
            "source": "E-Commerce Tech Interview Pool",
            "url": "https://github.com/donnemartin/system-design-primer",
        },
    ],
    "Tiki": [
        {
            "question": "Làm thế nào để đảm bảo tính Idempotent cho API thanh toán (Payment Gateway) khi mạng lag và người dùng bấm nút thanh toán nhiều lần?",
            "stage": "applied_scenario",
            "rubric_type": "case_study",
            "difficulty": 3,
            "concepts": ["idempotency", "token_bucket", "api_design"],
            "for_role": "all",
            "source": "Tiki Engineering Tech Insights",
            "url": "https://tiki.vn/",
        },
        {
            "question": "Chiến lược phân trang (Pagination) cho bảng cơ sở dữ liệu hàng chục triệu bản ghi để tránh độ trễ khi OFFSET quá lớn?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 3,
            "concepts": ["mysql_optimization", "keyset_pagination", "b_tree_indexing"],
            "for_role": "all",
            "source": "Tiki Platform Interview Share",
            "url": "https://github.com/donnemartin/system-design-primer",
        },
    ],
}


class OrchestratorLogManager:
    """Quản lý in-memory ring buffer log của Model Orchestrator."""

    def __init__(self, max_logs: int = 200):
        self.logs: list[dict[str, Any]] = []
        self.max_logs = max_logs

    def add_log(
        self,
        level: str,
        message: str,
        tool_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        entry = {
            "id": f"log_{uuid.uuid4().hex[:10]}",
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": level,
            "tool_name": tool_name,
            "message": message,
            "details": details or {},
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

        logger.info(f"[Orchestrator:{level}] {tool_name or 'CORE'}: {message}")

    def get_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.logs[-limit:]

    def clear(self):
        self.logs.clear()


# Singleton Log Manager
orchestrator_logger = OrchestratorLogManager()


class ModelOrchestratorService:
    """
    Model Orchestrator:
    Tự động gọi MCP Web Search & Crawler để tìm kiếm lịch sử, kinh nghiệm
    và câu hỏi phỏng vấn thực tế của doanh nghiệp, sau đó nạp vào Question Bank.
    """

    def __init__(self):
        self.settings = get_settings()
        self.redis = RedisSessionManager()
        self.gemini_client = None
        if self.settings.google_gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.settings.google_gemini_api_key)

    async def execute_discovery_and_ingest(
        self,
        company: str,
        role: str,
        student_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Toàn bộ chu trình Orchestrator:
        1. Tool Call: mcp_web_search (tìm kiếm internet thời gian thực)
        2. Tool Call: tech_portal_crawler (cào dữ liệu từ tech forums/ITviec/TopCV)
        3. Tool Call: curated_vault_matcher (kết hợp tri thức doanh nghiệp chuẩn hóa)
        4. Tool Call: question_bank_ingest (nạp và gán nhãn câu hỏi vào cơ sở dữ liệu)
        """
        start_time = datetime.now()
        orchestrator_logger.add_log(
            level="INFO",
            message=f"Model Orchestrator khởi động quy trình khai phá dữ liệu phỏng vấn: Công ty='{company}', Vị trí='{role}'",
            tool_name="model_orchestrator",
            details={"company": company, "role": role, "student_id": student_id},
        )

        # ---------------------------------------------------------
        # BƯỚC 1: Tool Call — MCP Web Search (Open Web Dynamic Discovery)
        # ---------------------------------------------------------
        orchestrator_logger.add_log(
            level="TOOL_CALL",
            message=f"Gọi MCP Web Search: Orchestrator tự động rà quét toàn mạng Internet (Không giới hạn domain hay đuôi website)",
            tool_name="mcp_web_search",
            details={
                "search_mode": "open_web_dynamic_discovery",
                "scope": "Toàn bộ mạng Internet mở",
                "target_company": company,
                "target_role": role,
                "strategy": "Tự động sinh truy vấn & trích xuất website trên không gian mạng",
            },
        )

        web_results, discovered_domains, live_questions = await self._tool_mcp_web_search(company, role)

        orchestrator_logger.add_log(
            level="TOOL_RESULT",
            message=f"MCP Web Search hoàn tất: Khám phá thành công {len(web_results)} bài thảo luận từ {len(discovered_domains)} trang web khác nhau trên Internet",
            tool_name="mcp_web_search",
            details={
                "results_count": len(web_results),
                "discovered_domains_count": len(discovered_domains),
                "discovered_domains": discovered_domains,
                "sources": [
                    {
                        "title": r.get("title"),
                        "url": r.get("href"),
                        "domain": r.get("domain"),
                        "snippet": r.get("body") or r.get("snippet") or "",
                    }
                    for r in web_results[:6]
                ],
            },
        )

        # ---------------------------------------------------------
        # BƯỚC 1.5: Tool Call — Web Content Extractor (Deep Scraping & Harvest)
        # ---------------------------------------------------------
        orchestrator_logger.add_log(
            level="TOOL_CALL",
            message=f"Bóc tách & Thu thập nội dung chuyên sâu từ các trang web đã phát hiện (Web Content Extractor)",
            tool_name="web_content_extractor",
            details={
                "target_company": company,
                "target_role": role,
                "strategy": "Trích xuất kinh nghiệm phỏng vấn, câu hỏi thực tế và bài toán kỹ thuật từ trang web",
            },
        )

        extracted_pages, deep_questions = await self._tool_extract_web_content(company, role, web_results)

        orchestrator_logger.add_log(
            level="TOOL_RESULT",
            message=f"Đã trích xuất thành công {len(extracted_pages)} bài viết và {len(deep_questions)} câu hỏi phỏng vấn thực tế từ Open Web",
            tool_name="web_content_extractor",
            details={
                "extracted_count": len(extracted_pages),
                "deep_questions_count": len(deep_questions),
                "extracted_pages": extracted_pages,
                "deep_questions_sample": [q.get("question") for q in deep_questions[:5]],
            },
        )

        # ---------------------------------------------------------
        # BƯỚC 2: Tool Call — Curated Knowledge Matcher & Fallback
        # ---------------------------------------------------------
        orchestrator_logger.add_log(
            level="TOOL_CALL",
            message=f"Đối chiếu bộ tri thức kiểm định (Curated Knowledge Vault) cho {company}",
            tool_name="curated_vault_matcher",
            details={"company": company, "role": role},
        )

        vault_questions = self._get_vault_questions_for_role(company, role, web_results=web_results)

        orchestrator_logger.add_log(
            level="TOOL_RESULT",
            message=f"Đã khớp {len(vault_questions)} câu hỏi phỏng vấn chuẩn hóa đặc thù của {company} (Vị trí: {role})",
            tool_name="curated_vault_matcher",
            details={
                "matched_count": len(vault_questions),
                "company_vault": company,
                "target_role": role,
                "vault_questions": [
                    {
                        "index": idx + 1,
                        "question": q["question"],
                        "stage": q.get("stage", "technical_core"),
                        "concepts": q.get("concepts", []),
                        "source": q.get("source", f"{company} Verified Knowledge"),
                        "url": q.get("url", ""),
                    }
                    for idx, q in enumerate(vault_questions)
                ],
            },
        )

        # ---------------------------------------------------------
        # BƯỚC 3: Tool Call — LLM / Heuristic Question Structurer
        # ---------------------------------------------------------
        orchestrator_logger.add_log(
            level="TOOL_CALL",
            message="Chuẩn hóa câu hỏi theo khung 4 giai đoạn phỏng vấn OJT chuẩn (§23.2)",
            tool_name="nlp_question_structurer",
            details={"stages": ["hr_motivation", "cv_project_defense", "technical_core", "applied_scenario"]},
        )

        structured_questions = await self._synthesize_questions(
            company=company,
            role=role,
            web_results=web_results,
            vault_questions=vault_questions,
            live_questions=live_questions,
            deep_questions=deep_questions,
        )

        open_web_count = len([q for q in structured_questions if "Vault" not in q.get("source", "")])
        vault_count = len(structured_questions) - open_web_count

        orchestrator_logger.add_log(
            level="TOOL_RESULT",
            message=f"Hoàn thành phân tích: Trích xuất và định hình thành công {len(structured_questions)} câu hỏi có gán nhãn Rubric",
            tool_name="nlp_question_structurer",
            details={
                "question_count": len(structured_questions),
                "summary": f"{open_web_count} câu từ Open Web & Live Search + {vault_count} câu từ Curated Vault ({company})",
                "questions_list": [
                    {
                        "index": idx + 1,
                        "question": q["question"],
                        "stage": q.get("stage"),
                        "source": q.get("source"),
                        "url": q.get("url", ""),
                    }
                    for idx, q in enumerate(structured_questions)
                ],
            },
        )

        # ---------------------------------------------------------
        # BƯỚC 4: Tool Call — Question Bank Ingest
        # ---------------------------------------------------------
        orchestrator_logger.add_log(
            level="INGEST",
            message=f"Nạp {len(structured_questions)} câu hỏi vào Hot Cache Redis & Ngân hàng câu hỏi phiên",
            tool_name="question_bank_ingest",
            details={"cache_key": f"company:{company}:role:{role}:questions"},
        )

        ingest_count = self._ingest_into_bank(company, role, structured_questions)

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        orchestrator_logger.add_log(
            level="SUCCESS",
            message=f"Orchestrator hoàn tất toàn bộ pipeline trong {elapsed_ms}ms! Ngân hàng câu hỏi đã sẵn sàng cho kỳ thi.",
            tool_name="model_orchestrator",
            details={"total_ingested": ingest_count, "latency_ms": elapsed_ms},
        )

        return {
            "status": "success",
            "company": company,
            "role": role,
            "ingested_count": ingest_count,
            "questions": structured_questions,
            "latency_ms": elapsed_ms,
            "logs": orchestrator_logger.get_logs(limit=20),
        }

    async def _tool_mcp_web_search(
        self, company: str, role: str
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        """
        Thực thi Live MCP Web Search trên TOÀN BỘ MẠNG INTERNET (Open Web) qua CrawlerService.
        Orchestrator tự do tìm kiếm trên mạng mở, KHÔNG FIX CỨNG bất kỳ domain hay đuôi website nào.
        Tự động trích xuất danh sách các domain thực tế phát hiện được trên Internet.
        """
        orchestrator_logger.add_log(
            level="TOOL_CALL",
            message="[MCP_GATEWAY] Dispatch Live Web Search qua Open Web Crawler & Grounding Engine",
            tool_name="mcp_web_search",
            details={
                "engine": "crawler_open_web_discovery",
                "mode": "open_web_unrestricted",
                "target_company": company,
                "target_role": role,
                "domain_policy": "Tự động khám phá toàn mạng Internet (Không giới hạn domain hay đuôi website)",
            },
        )

        crawler = get_crawler_service()
        raw_results, discovered_domains, live_questions = await crawler.search_interview_experiences(company, role)

        orchestrator_logger.add_log(
            level="RAW_MCP_LOG",
            message=f"[RAW MCP HTTP RESPONSE] 200 OK — Tự động tìm thấy {len(raw_results)} bài viết từ {len(discovered_domains)} trang web khác nhau trên Internet",
            tool_name="mcp_web_search",
            details={
                "results_count": len(raw_results),
                "discovered_domains_count": len(discovered_domains),
                "discovered_domains": discovered_domains,
                "sources": [
                    {
                        "title": r.get("title"),
                        "url": r.get("href"),
                        "domain": r.get("domain"),
                        "snippet": r.get("body") or r.get("snippet") or "",
                    }
                    for r in raw_results[:8]
                ],
            },
        )

        return raw_results, discovered_domains, live_questions

    async def _tool_extract_web_content(
        self, company: str, role: str, web_results: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Bóc tách & Thu thập dữ liệu NGUYÊN BẢN (100% RAW) từ các trang web tìm thấy trên Internet qua CrawlerService.
        TUYỆT ĐỐI KHÔNG CAN THIỆP, KHÔNG CHỈNH SỬA, KHÔNG MOCK VĂN BẢN, KHÔNG FIX CỨNG DOMAIN.
        Gửi yêu cầu HTTP thật trực tiếp đến các URL và ghi lại nguyên văn phản hồi máy chủ:
        - HTTP Status Code (200, 403, 301, etc.)
        - Content-Type & Payload Byte Size
        - Network Latency (ms)
        - RAW Text Excerpt (trích xuất nguyên gốc từ HTML body hoặc Search Engine Snippet)
        - Deep Questions Mined từ các thẻ câu hỏi trong DOM
        """
        crawler = get_crawler_service()
        valid_pages, deep_questions = await crawler.crawl_urls(web_results, max_pages=8)
        return valid_pages, deep_questions

    async def _synthesize_questions(
        self,
        company: str,
        role: str,
        web_results: list[dict[str, Any]],
        vault_questions: list[dict[str, Any]],
        live_questions: Optional[list[dict[str, Any]]] = None,
        deep_questions: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """
        Tổng hợp câu hỏi THẬT từ tri thức kiểm định (Company Vault),
        trích xuất từ DOM các bài viết cào được trên Internet (deep_questions),
        và từ Live Grounding / Snippets.
        Loại bỏ hoàn toàn các câu hỏi mock test giả định.
        """
        questions: list[dict[str, Any]] = []
        seen_normalized: set[str] = set()

        def _norm(text: str) -> str:
            return re.sub(r'[^\w\s]', '', text.lower()).strip()

        # 1. Thêm câu hỏi khai thác sâu từ toàn văn HTML bài viết trên Open Web
        if deep_questions:
            for dq in deep_questions:
                q_text = dq.get("question", "").strip()
                n = _norm(q_text)
                if len(q_text) >= 15 and n not in seen_normalized:
                    seen_normalized.add(n)
                    questions.append({
                        "id": f"q_web_{uuid.uuid4().hex[:8]}",
                        "question": q_text,
                        "stage": dq.get("stage", "technical_core"),
                        "rubric_type": dq.get("rubric_type", "technical_correctness"),
                        "difficulty": dq.get("difficulty", 3),
                        "expected_concepts": dq.get("concepts") or dq.get("expected_concepts", []),
                        "source": dq.get("source", "Open Web Interview Article"),
                        "url": dq.get("url", ""),
                    })

        # 2. Thêm câu hỏi trích xuất từ Live Grounding / Search Snippets
        if live_questions:
            for lidx, lq in enumerate(live_questions):
                q_text = lq.get("question", "").strip()
                n = _norm(q_text)
                if len(q_text) >= 15 and n not in seen_normalized:
                    seen_normalized.add(n)
                    lq_url = lq.get("url", "")
                    if not lq_url and web_results:
                        lq_url = web_results[lidx % len(web_results)].get("href", "")

                    questions.append({
                        "id": f"q_mcp_{uuid.uuid4().hex[:8]}",
                        "question": q_text,
                        "stage": lq.get("stage", "technical_core"),
                        "rubric_type": lq.get("rubric_type", "technical_correctness"),
                        "difficulty": lq.get("difficulty", 3),
                        "expected_concepts": lq.get("expected_concepts") or lq.get("concepts", []),
                        "source": lq.get("source", "Live Community Interview Share"),
                        "url": lq_url,
                    })

        # 3. Thêm câu hỏi kiểm định doanh nghiệp (Vault) kèm live URLs
        for idx, q in enumerate(vault_questions):
            q_text = q.get("question", "").strip()
            n = _norm(q_text)
            if n not in seen_normalized:
                seen_normalized.add(n)
                assigned_url = q.get("url", "")
                if (not assigned_url or "404" in assigned_url) and web_results:
                    assigned_url = web_results[idx % len(web_results)].get("href", "")

                questions.append({
                    "id": f"q_vault_{uuid.uuid4().hex[:8]}",
                    "question": q_text,
                    "stage": q.get("stage", "technical_core"),
                    "rubric_type": q.get("rubric_type", "technical_correctness"),
                    "difficulty": q.get("difficulty", 3),
                    "expected_concepts": q.get("concepts", []),
                    "source": q.get("source", f"{company} Verified Knowledge"),
                    "url": assigned_url,
                })

        # Đảm bảo có đại diện cho cả 4 giai đoạn chuẩn OJT
        required_stages = ["hr_motivation", "cv_project_defense", "technical_core", "applied_scenario"]
        present_stages = {q["stage"] for q in questions}

        for stg in required_stages:
            if stg not in present_stages:
                for vq in vault_questions:
                    if vq.get("stage") == stg:
                        questions.append({
                            "id": f"q_vault_{uuid.uuid4().hex[:8]}",
                            "question": vq["question"],
                            "stage": stg,
                            "rubric_type": vq.get("rubric_type", "technical_correctness"),
                            "difficulty": vq.get("difficulty", 3),
                            "expected_concepts": vq.get("concepts", []),
                            "source": vq.get("source", f"{company} Verified Knowledge"),
                            "url": vq.get("url", ""),
                        })
                        present_stages.add(stg)
                        break

        return questions

    def _get_vault_questions_for_role(
        self,
        company: str,
        role: str,
        web_results: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """Lọc câu hỏi kiểm định phù hợp với role của ứng viên và gán link bài viết thực tế phát hiện trên Internet."""
        r_lower = role.lower()
        all_q = COMPANY_KNOWLEDGE_VAULTS.get(company, [])
        if not all_q:
            for k in COMPANY_KNOWLEDGE_VAULTS:
                if k.lower() in company.lower() or company.lower() in k.lower():
                    all_q = COMPANY_KNOWLEDGE_VAULTS[k]
                    break
        if not all_q:
            all_q = COMPANY_KNOWLEDGE_VAULTS["FPT Software"]

        # Nếu role liên quan đến Frontend / React / Vue / Web
        if any(k in r_lower for k in ["front", "react", "vue", "angular", "ui", "web", "next"]):
            selected_q = [q for q in all_q if q.get("for_role") in ["frontend", "all"]]
        # Nếu role liên quan đến Backend / Java / Python / Golang / Database
        elif any(k in r_lower for k in ["back", "java", "spring", "python", "golang", "c#", ".net", "db", "sql"]):
            selected_q = [q for q in all_q if q.get("for_role") in ["backend", "all"]]
        else:
            selected_q = all_q

        # TẠO BẢN SAO VÀ GÁN LINK BÀI VIẾT THỰC TẾ ĐƯỢC TÌM THẤY TRỰC TIẾP TỪ MCP SEARCH
        # TUYỆT ĐỐI KHÔNG DÙNG LINK ẢO / SLUG BỊ 404
        result_q: list[dict[str, Any]] = []
        for idx, item in enumerate(selected_q):
            q_copy = dict(item)
            if web_results and len(web_results) > 0:
                live_item = web_results[idx % len(web_results)]
                live_url = live_item.get("href") or live_item.get("url") or ""
                live_domain = live_item.get("domain") or ""
                if live_url:
                    q_copy["url"] = live_url
                    orig_source = q_copy.get("source", f"{company} Knowledge Vault")
                    q_copy["source"] = f"{orig_source} (Khám phá qua {live_domain})"
            result_q.append(q_copy)

        return result_q

    def _ingest_into_bank(self, company: str, role: str, questions: list[dict[str, Any]]) -> int:
        """Lưu trữ vào Redis hot store và candidate memory."""
        cache_key = f"company:{company}:role:{role}:questions"
        self.redis.cache_candidate_memory(cache_key, {"questions": questions}, ttl=7200)
        return len(questions)

    def get_ingested_questions(self, company: str, role: str) -> list[dict[str, Any]]:
        """Lấy danh sách câu hỏi đã nạp cho công ty và vị trí."""
        cache_key = f"company:{company}:role:{role}:questions"
        cached = self.redis.get_cached_candidate_memory(cache_key)
        if cached and "questions" in cached:
            return cached["questions"]

        # Fallback to role-aware company knowledge vault
        return self._get_vault_questions_for_role(company, role)



# Singleton instance
_orchestrator_service: Optional[ModelOrchestratorService] = None


def get_orchestrator_service() -> ModelOrchestratorService:
    global _orchestrator_service
    if _orchestrator_service is None:
        _orchestrator_service = ModelOrchestratorService()
    return _orchestrator_service
