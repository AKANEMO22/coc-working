"""
CÓC ĐI LÀM — Crawler Service (§3)
Data Intelligence Plane: Open Web Scraper & Multi-Engine Crawler Service.
Khám phá và thu thập dữ liệu phỏng vấn thực tế từ TOÀN BỘ MẠNG INTERNET (Không giới hạn domain hay đuôi website).
Hỗ trợ Multi-Engine (DuckDuckGo Lite, DuckDuckGo HTML, Bing Web, Google Search Grounding),
hệ thống Anti-Bot Stealth Engine (Client Hints, Jitter, Snippet Fallback) và Deep Question Mining.
Tuyệt đối không sử dụng mock test.
"""

import asyncio
import logging
import time
import random
import re
import base64
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, quote, unquote
import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Danh sách User-Agents hiện đại cho cơ chế Stealth Browser Rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Danh sách domain đóng / yêu cầu đăng nhập cần loại bỏ
BLOCKED_DOMAINS = [
    "facebook.com", "instagram.com", "tiktok.com", "twitter.com",
    "x.com", "linkedin.com", "pinterest.com", "threads.net", "youtube.com"
]

# Từ khóa kỹ thuật / phỏng vấn dùng để thẩm định câu hỏi hợp lệ
TECH_CORE_KEYWORDS = [
    "java", "spring", "sql", "database", "api", "rest", "oop", "class", "interface",
    "index", "query", "orm", "hibernate", "jpa", "thread", "concurrency", "cache",
    "redis", "kafka", "microservice", "docker", "git", "star", "dự án", "cv", "lỗi",
    "exception", "tải cao", "bảo mật", "deadlock", "acid", "react", "state", "props",
    "hook", "dom", "component", "fresher", "intern", "ojt", "phỏng vấn", "garbage",
    "jvm", "memory", "leak", "singleton", "solid", "b-tree", "golang", "python",
    "node", "typescript", "architecture", "leaderboard", "nosql", "ci/cd", "security",
    "unit test", "automation", "clean code", "performance", "scalability", "vấn đề",
    "giải pháp", "khác nhau", "ưu điểm", "nhược điểm", "nguyên lý"
]

NOISE_KEYWORDS = [
    "đăng ký", "đăng nhập", "chính sách", "liên hệ", "bản quyền", "xem thêm",
    "bình luận", "quảng cáo", "két sắt", "sđt", "hotline", "mua ngay", "giá bao nhiêu",
    "copyright", "điều khoản", "tuyển dụng gấp", "mức lương", "phúc lợi", "bảo hiểm",
    "gửi xe", "cơm trưa", "du lịch hàng năm", "thưởng tết"
]


def get_stealth_headers(referer: str = "https://www.google.com/") -> dict[str, str]:
    """Tạo bộ HTTP Headers chuẩn giả lập danh tính trình duyệt Chrome/Edge thật có đầy đủ Client-Hints."""
    ua = random.choice(USER_AGENTS)
    is_mac = "Macintosh" in ua
    platform = '"macOS"' if is_mac else '"Windows"'
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": platform,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Referer": referer,
    }


class CrawlerService:
    """
    Cloud Data Orchestrator & Crawler (§3).
    - Khám phá dữ liệu trên toàn bộ không gian mạng Internet mở qua Multi-Engine.
    - Chống bot WAF (Cloudflare bypass headers, per-domain jitter, fallback snippet).
    - Deep Question Mining Engine: bóc tách câu hỏi trực tiếp từ nội dung bài viết.
    - Tuyệt đối không sử dụng mock test / dữ liệu giả.
    """

    def __init__(self, max_concurrent: int = 6, timeout: float = 6.0):
        self.settings = get_settings()
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._gemini_client = None

        api_key = getattr(self.settings, "google_gemini_api_key", None) or getattr(self.settings, "gemini_api_key", "")
        if api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.warning(f"CrawlerService Gemini init warning: {e}")

    # =========================================================================
    # SEARCH ENGINES AGGREGATION
    # =========================================================================

    async def _search_ddg_lite(self, query: str, max_results: int = 6) -> list[dict[str, Any]]:
        """Công cụ 1: DuckDuckGo Lite qua HTTP POST (Bền bỉ, siêu nhẹ, không bị bot block)."""
        results = []
        url = "https://lite.duckduckgo.com/lite/"
        try:
            headers = get_stealth_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            async with httpx.AsyncClient(timeout=6.0, headers=headers, follow_redirects=True, verify=False) as client:
                resp = await client.post(url, content=f"q={quote(query)}")
                if resp.status_code in [200, 202]:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("a", class_="result-link")
                    snippets = soup.find_all("td", class_="result-snippet")
                    for i, link in enumerate(links):
                        href = link.get("href", "")
                        if "uddg=" in href:
                            p = parse_qs(urlparse(href).query)
                            if "uddg" in p:
                                href = unquote(p["uddg"][0])
                        snip = snippets[i].get_text().strip() if i < len(snippets) else ""
                        if href.startswith("http"):
                            domain = urlparse(href).netloc.replace("www.", "")
                            if not any(b in domain.lower() for b in BLOCKED_DOMAINS):
                                results.append({
                                    "title": link.get_text().strip(),
                                    "href": href,
                                    "domain": domain,
                                    "body": snip,
                                    "source": domain,
                                    "engine": "duckduckgo_lite",
                                })
                                if len(results) >= max_results:
                                    break
        except Exception as e:
            logger.debug(f"[CrawlerService] DDG Lite search error: {e}")
        return results

    async def _search_ddg_html(self, query: str, max_results: int = 6) -> list[dict[str, Any]]:
        """Công cụ 2: DuckDuckGo HTML Engine qua HTTP GET."""
        results = []
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=get_stealth_headers(), follow_redirects=True, verify=False) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for res in soup.find_all("div", class_="result"):
                        title_el = res.find("a", class_="result__a") or res.find("a", class_="result__title")
                        snippet_el = res.find("a", class_="result__snippet")
                        url_el = res.find("a", class_="result__url")
                        if title_el:
                            title = title_el.get_text().strip()
                            raw_href = (url_el.get("href") if url_el else "") or title_el.get("href", "")
                            real_url = raw_href
                            if "uddg=" in raw_href:
                                p = parse_qs(urlparse(raw_href).query)
                                if "uddg" in p:
                                    real_url = unquote(p["uddg"][0])
                            if real_url.startswith("http"):
                                domain = urlparse(real_url).netloc.replace("www.", "")
                                if not any(b in domain.lower() for b in BLOCKED_DOMAINS):
                                    results.append({
                                        "title": title,
                                        "href": real_url,
                                        "domain": domain,
                                        "body": snippet_el.get_text().strip() if snippet_el else "",
                                        "source": domain,
                                        "engine": "duckduckgo_html",
                                    })
                                    if len(results) >= max_results:
                                        break
        except Exception as e:
            logger.debug(f"[CrawlerService] DDG HTML search error: {e}")
        return results

    async def _search_bing_html(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Công cụ 3: Bing Web Search Engine với cơ chế tự động giải mã tracking link."""
        results = []
        url = f"https://www.bing.com/search?q={quote(query)}"
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=get_stealth_headers("https://www.bing.com/"), follow_redirects=True, verify=False) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for b_algo in soup.find_all("li", class_="b_algo"):
                        a_tag = b_algo.find("h2")
                        if a_tag and a_tag.find("a"):
                            link = a_tag.find("a")
                            href = link.get("href", "")
                            title = link.get_text().strip()
                            p_snip = b_algo.find("p")
                            snippet = p_snip.get_text().strip() if p_snip else ""

                            # Giải mã tracking redirect của Bing
                            real_href = href
                            if "bing.com/ck/a" in href:
                                p = parse_qs(urlparse(href).query)
                                if "u" in p:
                                    raw_u = p["u"][0]
                                    if raw_u.startswith("a1"):
                                        b64_part = raw_u[2:]
                                        b64_part += "=" * ((4 - len(b64_part) % 4) % 4)
                                        try:
                                            decoded_u = base64.b64decode(b64_part).decode("utf-8", errors="ignore")
                                            if decoded_u.startswith("http"):
                                                real_href = decoded_u
                                        except Exception:
                                            pass

                            if real_href.startswith("http"):
                                domain = urlparse(real_href).netloc.replace("www.", "")
                                if not any(b in domain.lower() for b in BLOCKED_DOMAINS + ["bing.com", "microsoft.com"]):
                                    results.append({
                                        "title": title,
                                        "href": real_href,
                                        "domain": domain,
                                        "body": snippet,
                                        "source": domain,
                                        "engine": "bing_html",
                                    })
                                    if len(results) >= max_results:
                                        break
        except Exception as e:
            logger.debug(f"[CrawlerService] Bing HTML search error: {e}")
        return results

    async def search_multi_engine(self, queries: list[str], max_per_query: int = 5) -> list[dict[str, Any]]:
        """
        Tìm kiếm phân tán đa công cụ (Multi-Engine Aggregation) trên toàn mạng Internet.
        Tổng hợp, loại bỏ trùng lặp và phân loại domain.
        """
        tasks = []
        for q in queries:
            tasks.append(self._search_ddg_lite(q, max_per_query))
            tasks.append(self._search_ddg_html(q, max_per_query))
            tasks.append(self._search_bing_html(q, max_per_query))

        batches = await asyncio.gather(*tasks, return_exceptions=True)
        aggregated: list[dict[str, Any]] = []
        seen_urls = set()

        for batch in batches:
            if isinstance(batch, list):
                for item in batch:
                    u = item.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        aggregated.append(item)

        return aggregated

    # =========================================================================
    # DEEP QUESTION MINING ENGINE (Bóc tách câu hỏi sâu từ HTML / Snippet)
    # =========================================================================

    def extract_tech_questions(self, text: str, source_title: str, source_url: str) -> list[dict[str, Any]]:
        """
        Bóc tách các câu hỏi kỹ thuật thực tế từ đoạn văn bản/HTML.
        Tự động phân loại 4 giai đoạn chuẩn OJT và gán rubric/expected concepts.
        """
        candidates: list[dict[str, Any]] = []
        lines = re.split(r'[\r\n]+|[•\t]+', text)

        p_numbered = re.compile(r'^(Câu\s*\d+|Q\d+|\d+[\.\)])\s*[:\.\-]?\s*(.+)', re.IGNORECASE)
        p_interrogative = re.compile(
            r'^(Hãy\s+|Bạn\s+hiểu\s+|Giải\s+thích\s+|Phân\s+biệt\s+|So\s+sánh\s+|Làm\s+sao|Làm\s+thế\s+nào\s+|Khi\s+nào\s+|Tại\s+sao\s+|Trình\s+bày\s+|Nêu\s+|Mô\s+tả\s+|Vấn\s+đề\s+)',
            re.IGNORECASE
        )

        for line in lines:
            cleaned = " ".join(line.strip().split())
            if len(cleaned) < 20 or len(cleaned) > 240:
                continue
            if any(nw in cleaned.lower() for nw in NOISE_KEYWORDS):
                continue

            is_q = False
            m_num = p_numbered.match(cleaned)
            if m_num:
                cleaned = m_num.group(2).strip()
                is_q = True
            elif cleaned.endswith("?") or p_interrogative.match(cleaned):
                is_q = True

            if is_q and any(tk in cleaned.lower() for tk in TECH_CORE_KEYWORDS):
                cleaned = re.sub(r'^[-\:\.\s]+', '', cleaned)
                if len(cleaned) >= 20 and not any(c["question"] == cleaned for c in candidates):
                    # Phân loại Stage & Rubric chuẩn OJT (§14, §23.2)
                    stage, rubric, difficulty, concepts = self._classify_question(cleaned)
                    candidates.append({
                        "question": cleaned,
                        "stage": stage,
                        "rubric_type": rubric,
                        "difficulty": difficulty,
                        "expected_concepts": concepts,
                        "source": source_title,
                        "url": source_url,
                    })

        return candidates

    def extract_questions_from_html(self, html_text: str, source_url: str, source_title: str) -> list[dict[str, Any]]:
        """Bóc tách sâu danh sách câu hỏi phỏng vấn từ cây cấu trúc DOM HTML bài viết."""
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form"]):
            tag.decompose()

        # Quét các thẻ tiêu đề câu hỏi, đoạn in đậm, danh sách mục
        elements = soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "li", "p", "a"])
        combined_text = "\n".join([el.get_text() for el in elements])
        return self.extract_tech_questions(combined_text, source_title, source_url)

    def _classify_question(self, question: str) -> tuple[str, str, int, list[str]]:
        """Phân loại giai đoạn phỏng vấn, rubric, độ khó và concepts từ nội dung câu hỏi."""
        q_lower = question.lower()

        # 1. HR & Động lực OJT
        if any(k in q_lower for k in ["giới thiệu", "động lực", "mục tiêu", "văn hóa", "tại sao chọn", "điểm mạnh", "điểm yếu", "định hướng", "5 năm"]):
            return "hr_motivation", "hr_motivation", 2, ["career_goals", "company_motivation"]

        # 2. Thẩm định dự án STAR (Google XYZ)
        if any(k in q_lower for k in ["dự án", "project", "vai trò", "star", "khó khăn", "đóng góp", "thành tích", "cv", "lỗi phát sinh"]):
            return "cv_project_defense", "star_framework", 3, ["star_framework", "project_ownership", "problem_solving"]

        # 3. Tình huống sự cố / Case Study
        if any(k in q_lower for k in ["sự cố", "tải cao", "deadlock", "tối ưu", "bảo mật", "scale", "production", "oom", "bottleneck", "concurrency", "out of memory"]):
            return "applied_scenario", "case_study", 4, ["incident_response", "system_design", "high_concurrency"]

        # 4. Kỹ thuật chuyên môn (Technical Core)
        extracted_concepts = [w for w in ["database", "sql", "index", "spring", "react", "oop", "cache", "redis", "kafka", "api", "transaction", "orm", "jvm"] if w in q_lower]
        return "technical_core", "technical_correctness", 3, extracted_concepts or ["core_technical_knowledge"]

    # =========================================================================
    # OPEN WEB SEARCH & CRAWL PIPELINE
    # =========================================================================

    async def search_interview_experiences(
        self,
        company: str,
        role: str,
        seniority: str = "intern",
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        """
        Khám phá và quét diện rộng câu hỏi phỏng vấn trên toàn bộ mạng Internet.
        Sinh ma trận truy vấn đa chiều (Company, Tech Stack, Tech Platforms, Real Incidents).
        """
        logger.info(f"[CrawlerService] Starting broad multi-engine search: company='{company}', role='{role}'")
        discovered_domains_set: set[str] = set()

        # 1. Sinh ma trận truy vấn mở rộng (Query Expansion Matrix)
        r_lower = role.lower()
        tech_terms = ""
        if "java" in r_lower or "backend" in r_lower:
            tech_terms = "Java Spring Boot Hibernate SQL"
        elif "react" in r_lower or "front" in r_lower:
            tech_terms = "ReactJS TypeScript Virtual DOM Redux"
        elif "go" in r_lower:
            tech_terms = "Golang Goroutine Channel Concurrency"
        elif ".net" in r_lower or "c#" in r_lower:
            tech_terms = "C# .NET Entity Framework SQL Server"
        else:
            tech_terms = role

        queries = [
            f"{company} {role} câu hỏi phỏng vấn review",
            f"{company} kinh nghiệm phỏng vấn {seniority} fresher",
            f"{tech_terms} câu hỏi phỏng vấn {seniority} fresher",
            f"site:viblo.asia OR site:topcv.vn {role} câu hỏi phỏng vấn",
            f"site:kungfutech.io.vn OR site:daynhauhoc.com phỏng vấn {company}",
        ]

        raw_results = await self.search_multi_engine(queries, max_per_query=5)

        for item in raw_results:
            d = item.get("domain", "")
            if d:
                discovered_domains_set.add(d)

        # 2. Google Search Grounding qua Gemini (nếu có key)
        live_questions: list[dict[str, Any]] = []
        if self._gemini_client:
            try:
                from google.genai import types
                loop = asyncio.get_event_loop()

                prompt = (
                    f"Bạn là chuyên gia thẩm định phỏng vấn IT. Hãy tìm kiếm trên Internet các bài viết chia sẻ, review kinh nghiệm và câu hỏi phỏng vấn thực tế gần đây cho vị trí {role} tại {company}.\n"
                    f"Yêu cầu: Không tạo câu hỏi giả định/mock test. Trích xuất câu hỏi cụ thể, thực tế mà ứng viên từng gặp.\n"
                    f"Trả về DUY NHẤT một mảng JSON thuần có cấu trúc:\n"
                    f"[\n"
                    f'  {{"question": "Nội dung câu hỏi phỏng vấn thực tế", "stage": "technical_core", "rubric_type": "technical_correctness", "difficulty": 3, "expected_concepts": ["concept1"], "source": "Tên nguồn hoặc website thực tế"}}\n'
                    f"]"
                )

                def run_grounding():
                    return self._gemini_client.models.generate_content(
                        model=getattr(self.settings, "gemini_flash_model", "gemini-2.5-flash"),
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                            temperature=0.2,
                        ),
                    )

                resp = await loop.run_in_executor(None, run_grounding)
                if resp and resp.candidates and resp.candidates[0].grounding_metadata:
                    gm = resp.candidates[0].grounding_metadata
                    if gm.grounding_chunks:
                        for c in gm.grounding_chunks:
                            if c.web:
                                w_title = c.web.title or ""
                                w_uri = c.web.uri or ""
                                parsed_domain = urlparse(w_uri).netloc.replace("www.", "")
                                domain = parsed_domain if parsed_domain and "vertexaisearch" not in parsed_domain else w_title.lower()
                                if domain:
                                    discovered_domains_set.add(domain)
                                if not any(r["href"] == w_uri for r in raw_results):
                                    raw_results.append({
                                        "title": w_title,
                                        "href": w_uri,
                                        "domain": domain,
                                        "body": f"Nguồn bài thảo luận từ {w_title}",
                                        "source": domain,
                                        "engine": "google_grounding",
                                    })

                    import json
                    t = resp.text.strip()
                    if "```json" in t:
                        t = t.split("```json")[1].split("```")[0].strip()
                    elif "```" in t:
                        t = t.split("```")[1].split("```")[0].strip()
                    parsed = json.loads(t)
                    if isinstance(parsed, list):
                        for pq in parsed:
                            if pq.get("question"):
                                live_questions.append(pq)
            except Exception as e:
                logger.debug(f"[CrawlerService] Google Grounding skipped: {e}")

        # 3. Trích xuất câu hỏi tức thì từ các Search Snippet (Bảo đảm luôn có câu hỏi ngay cả khi trang đích chống bot)
        for item in raw_results:
            snip = item.get("body", "")
            if snip:
                snippet_qs = self.extract_tech_questions(snip, item.get("title", ""), item.get("href", ""))
                for sq in snippet_qs:
                    if not any(lq["question"] == sq["question"] for lq in live_questions):
                        live_questions.append(sq)

        discovered_domains = sorted(list(discovered_domains_set))
        logger.info(f"[CrawlerService] Broad discovery complete: {len(raw_results)} URLs, {len(discovered_domains)} domains, {len(live_questions)} initial questions")
        return raw_results, discovered_domains, live_questions

    async def crawl_urls(
        self,
        web_results: list[dict[str, Any]],
        max_pages: int = 10,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Cào dữ liệu chuyên sâu và bóc tách câu hỏi từ các trang web đã phát hiện.
        - Cơ chế Anti-Bot WAF: Full Chrome Client-Hints, Domain-level Throttling & Jitter Delay.
        - Fallback: Nếu gặp 403, trích xuất dữ liệu từ Snippet & Meta Description thay vì bỏ cuộc.
        - Trả về: (crawled_pages, deep_extracted_questions)
        """
        target_urls = []
        seen_urls = set()

        for r in web_results:
            u = r.get("href") or r.get("url") or ""
            if u and u.startswith("http") and "google.com/search" not in u and u not in seen_urls:
                seen_urls.add(u)
                target_urls.append({
                    "url": u,
                    "title": r.get("title") or u,
                    "domain": r.get("domain") or urlparse(u).netloc.replace("www.", ""),
                    "search_snippet": r.get("body") or r.get("snippet") or "",
                })

        def _score_url(item: dict[str, Any]) -> int:
            score = 0
            u_low = item["url"].lower()
            t_low = item["title"].lower()
            for kw in ["cau-hoi", "phong-van", "interview", "review", "kinh-nghiem", "fresher", "intern"]:
                if kw in u_low: score += 4
                if kw in t_low: score += 4
            for p in ["viblo.asia", "topcv.vn", "itnavi.com.vn", "kungfutech", "jobsgo", "daynhauhoc", "voz.vn"]:
                if p in u_low: score += 3
            if item["url"].rstrip("/").count("/") <= 3: score -= 5
            return score

        target_urls.sort(key=_score_url, reverse=True)
        selected_targets = target_urls[:max_pages]
        semaphore = asyncio.Semaphore(self.max_concurrent)
        all_extracted_questions: list[dict[str, Any]] = []

        async def _fetch_one(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                url = item["url"]
                domain = item.get("domain") or urlparse(url).netloc.replace("www.", "")
                t0 = time.perf_counter()

                # Anti-bot jitter delay nhỏ để không kích hoạt WAF rate-limit
                await asyncio.sleep(random.uniform(0.1, 0.25))

                try:
                    headers = get_stealth_headers(referer=f"https://{domain}/")
                    async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True, verify=False) as client:
                        resp = await client.get(url)
                        latency = int((time.perf_counter() - t0) * 1000)

                        if resp.status_code == 200:
                            soup = BeautifulSoup(resp.text, "html.parser")
                            real_title = soup.title.string.strip() if (soup.title and soup.title.string) else item.get("title", url)

                            # Bóc tách sâu danh sách câu hỏi từ toàn bộ cây DOM bài viết
                            page_questions = self.extract_questions_from_html(resp.text, url, real_title)
                            all_extracted_questions.extend(page_questions)

                            for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
                                tag.decompose()
                            clean_text = " ".join(soup.get_text().split())
                            raw_content = clean_text[:400] if clean_text else resp.text[:400]

                            return {
                                "url": url,
                                "title": real_title,
                                "domain": domain,
                                "status_code": resp.status_code,
                                "content_type": resp.headers.get("content-type", "text/html"),
                                "byte_size": len(resp.content),
                                "latency_ms": latency,
                                "raw_content": raw_content,
                                "extracted_questions_count": len(page_questions),
                                "is_raw": True,
                            }
                        else:
                            # 403 / 429 Anti-Bot Fallback: Sử dụng Snippet Harvesting
                            raw_snippet = item.get("search_snippet", "")
                            snip_questions = self.extract_tech_questions(raw_snippet, item.get("title", url), url)
                            all_extracted_questions.extend(snip_questions)

                            return {
                                "url": url,
                                "title": item.get("title", url),
                                "domain": domain,
                                "status_code": resp.status_code,
                                "content_type": "text/html",
                                "byte_size": len(raw_snippet.encode("utf-8")),
                                "latency_ms": latency,
                                "raw_content": f"[ANTI-BOT {resp.status_code} WAF BYPASS: Harvested from Search Snippet] {raw_snippet}",
                                "extracted_questions_count": len(snip_questions),
                                "is_raw": True,
                            }
                except Exception as exc:
                    latency = int((time.perf_counter() - t0) * 1000)
                    raw_snippet = item.get("search_snippet", "")
                    snip_questions = self.extract_tech_questions(raw_snippet, item.get("title", url), url)
                    all_extracted_questions.extend(snip_questions)

                    return {
                        "url": url,
                        "title": item.get("title", url),
                        "domain": domain,
                        "status_code": 403 if "403" in str(exc) else 504 if "timeout" in str(exc).lower() else 500,
                        "content_type": "text/plain",
                        "byte_size": len(raw_snippet.encode("utf-8")),
                        "latency_ms": latency,
                        "raw_content": f"[ANTI-BOT NETWORK FALLBACK: Harvested from Snippet] {raw_snippet}",
                        "extracted_questions_count": len(snip_questions),
                        "is_raw": True,
                    }

        if not selected_targets:
            return [], []

        tasks = [_fetch_one(t) for t in selected_targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid_pages = [r for r in results if isinstance(r, dict)]

        # Lọc trùng lặp câu hỏi bóc tách được
        dedup_questions: list[dict[str, Any]] = []
        seen_q = set()
        for q in all_extracted_questions:
            q_text = q.get("question", "").strip()
            if q_text and q_text not in seen_q:
                seen_q.add(q_text)
                dedup_questions.append(q)

        logger.info(f"[CrawlerService] Crawled {len(valid_pages)} pages, extracted {len(dedup_questions)} deep questions from HTML & Snippets")
        return valid_pages, dedup_questions


# Singleton instance
_crawler_service: Optional[CrawlerService] = None


def get_crawler_service() -> CrawlerService:
    global _crawler_service
    if _crawler_service is None:
        _crawler_service = CrawlerService()
    return _crawler_service
