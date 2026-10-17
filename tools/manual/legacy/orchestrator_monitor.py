"""
CÓC ĐI LÀM — Live CLI Monitor for Model Orchestrator & Tool Calling Engine (§3, §8)
Hiển thị dòng log trực quan, chi tiết từng đường link, câu hỏi và tiến trình gọi Tool.
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

import sys
import os
import time
import json
import urllib.request
import urllib.error

# Thiết lập encoding UTF-8 và ANSI màu trên Windows CMD
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    os.system("")  # Kích hoạt ANSI escape sequence
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("Coc Di Lam - Model Orchestrator & Tool Calling Engine")
    except Exception:
        pass
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

# Mã màu ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
WHITE = "\033[97m"
GRAY = "\033[90m"
AMBER = "\033[38;5;214m"

def get_tool_color(tool_name: str, level: str) -> tuple[str, str]:
    """Trả về mã màu cho badge và khung log dựa theo tool_name."""
    name = (tool_name or level or "").upper()
    if "EXTRACT" in name or "SCRAP" in name:
        return CYAN, "WEB_CONTENT_EXTRACTOR"
    if "NLP" in name or "STRUCTURER" in name:
        return CYAN, "NLP_QUESTION_STRUCTURER"
    if "INGEST" in name or "BANK" in name:
        return MAGENTA, "QUESTION_BANK_INGEST"
    if "ORCHESTRATOR" in name or "SUCCESS" in name:
        return GREEN, "MODEL_ORCHESTRATOR"
    if "VAULT" in name or "MATCHER" in name:
        return AMBER, "CURATED_VAULT_MATCHER"
    if "MCP" in name or "SEARCH" in name:
        return BLUE, "MCP_WEB_SEARCH"
    return YELLOW, name or "TOOL_CALL"

def format_details(tool_name: str, level: str, details: dict):
    """Hiển thị chi tiết log dạng cây phân cấp rõ ràng, dễ đọc."""
    tool = (tool_name or level or "").lower()

    # 1. Web Content Extractor (Hiển thị dữ liệu THÔ NGUYÊN BẢN (100% RAW) trích xuất trực tiếp từ máy chủ web)
    if "extracted_pages" in details:
        pages = details.get("extracted_pages", [])
        print(f"             {CYAN}📄 [RAW WEB SCRAPER] Dữ liệu thô thu thập trực tiếp từ mạng Internet ({len(pages)} trang web):{RESET}")
        for i, p in enumerate(pages):
            is_last = (i == len(pages) - 1)
            prefix = "└─" if is_last else "├─"
            sub_prefix = "   " if is_last else "│  "
            title = p.get("title", "Trang web")
            url = p.get("url", "")
            domain = p.get("domain", "")
            status = p.get("status_code", 0)
            bytes_len = p.get("byte_size", 0)
            latency = p.get("latency_ms", 0)
            raw_text = p.get("raw_content") or p.get("harvested_content") or ""
            search_snip = p.get("search_snippet", "")

            if status == 200:
                status_str = f"{GREEN}Status 200 OK{RESET}"
            elif status in [401, 403]:
                status_str = f"{YELLOW}Status {status} [Cloudflare/Bot Blocked]{RESET}"
            elif status > 0:
                status_str = f"{MAGENTA}Status {status}{RESET}"
            else:
                status_str = f"{YELLOW}Status [Connection Error / Timeout]{RESET}"

            domain_str = f" {GRAY}({domain}){RESET}" if domain else ""
            print(f"             {CYAN}{prefix} [{i+1}] {WHITE}{title}{RESET}{domain_str}")
            print(f"             {CYAN}{sub_prefix}  📡 Phản hồi máy chủ: {status_str} | Kích thước: {WHITE}{bytes_len:,} bytes{RESET} | Độ trễ mạng: {WHITE}{latency}ms{RESET}")
            if url:
                print(f"             {CYAN}{sub_prefix}  🔗 URL gốc: {GREEN}{url}{RESET}")
            if raw_text:
                print(f"             {CYAN}{sub_prefix}  📄 {YELLOW}[RAW HTTP BODY CONTENT - Dữ liệu thô máy chủ web trả về]:{RESET}")
                print(f"             {CYAN}{sub_prefix}     {WHITE}\"{raw_text}\"{RESET}")
            if search_snip and search_snip != raw_text and not search_snip.startswith("Nguồn bài thảo luận từ"):
                print(f"             {CYAN}{sub_prefix}  🔍 {MAGENTA}[RAW SEARCH SNIPPET - Đoạn trích Search Engine]:{RESET}")
                print(f"             {CYAN}{sub_prefix}     {GRAY}\"{search_snip}\"{RESET}")
        return

    # 2. MCP Web Search Response (Hiển thị truy vấn, tên miền và link bài viết thật)
    if "sources" in details or "dynamic_search_queries" in details or "samples" in details or "discovered_domains" in details:
        queries = details.get("dynamic_search_queries", [])
        if queries:
            print(f"             {CYAN}├─ 🔍 Truy vấn tìm kiếm sinh bởi AI:{RESET}")
            for q in queries:
                print(f"             {CYAN}│  • \"{WHITE}{q}{CYAN}\"{RESET}")

        domains = details.get("discovered_domains", [])
        if domains:
            domain_str = ", ".join(domains[:8])
            print(f"             {CYAN}├─ 🌐 Tên miền phát hiện trên Internet:{RESET} {WHITE}{domain_str}{RESET}")

        sources = details.get("sources", []) or details.get("samples", [])
        if sources:
            print(f"             {CYAN}└─ 📑 Danh sách link bài viết thảo luận thực tế ({len(sources)} nguồn):{RESET}")
            for i, s in enumerate(sources):
                is_last = (i == len(sources) - 1)
                prefix = "└─" if is_last else "├─"
                sub_prefix = "   " if is_last else "│  "
                title = s.get("title") or s.get("domain") or "Bài chia sẻ kinh nghiệm phỏng vấn"
                url = s.get("url") or s.get("href") or ""
                domain = s.get("domain") or ""
                snippet = s.get("snippet") or s.get("body") or ""
                domain_tag = f" {GRAY}({domain}){RESET}" if domain else ""
                print(f"             {GREEN}   {prefix} [{i+1}] {WHITE}{title}{RESET}{domain_tag}")
                if url:
                    print(f"             {GREEN}   {sub_prefix}   🔗 Link truy cập: {CYAN}{url}{RESET}")
                if snippet:
                    clean_snip = snippet.strip()
                    print(f"             {GREEN}   {sub_prefix}   📄 {YELLOW}[RAW SEARCH SNIPPET - Dữ liệu thô từ Search Engine]:{RESET}")
                    print(f"             {GREEN}   {sub_prefix}      {WHITE}\"{clean_snip}\"{RESET}")
        else:
            print(f"             {GRAY}└─ (Đang rà quét qua các kênh cộng đồng IT){RESET}")
        return

    # 2. Curated Knowledge Vault Matcher (Hiển thị các câu hỏi kiểm định chuẩn kèm nguồn và link chi tiết)
    if "vault_questions" in details:
        vqs = details.get("vault_questions", [])
        company = details.get("company_vault") or details.get("company") or "Doanh nghiệp"
        target_role = details.get("target_role", "")
        role_label = f" — Vị trí: {WHITE}{target_role}{AMBER}" if target_role else ""
        print(f"             {AMBER}🏛️  Kho tri thức kiểm định {company}{role_label} ({len(vqs)} câu hỏi chuẩn hóa):{RESET}")
        for i, vq in enumerate(vqs):
            is_last = (i == len(vqs) - 1)
            prefix = "└─" if is_last else "├─"
            sub_prefix = "   " if is_last else "│  "
            q_text = vq.get("question", "")
            stage = vq.get("stage", "technical_core")
            concepts = ", ".join(vq.get("concepts", []))
            source = vq.get("source") or "Curated Knowledge Vault"
            url = vq.get("url") or vq.get("source_url") or ""

            print(f"             {AMBER}{prefix} [Q{i+1}|{stage}] {WHITE}{q_text}{RESET}")
            if concepts:
                print(f"             {AMBER}{sub_prefix}  🏷️  Tags: {GRAY}#{concepts.replace(', ', ' #')}{RESET}")
            print(f"             {AMBER}{sub_prefix}  🏛️  Nguồn thẩm định: {CYAN}{source}{RESET}")
            if url:
                print(f"             {AMBER}{sub_prefix}  🔗 Link tra cứu:    {GREEN}{url}{RESET}")
        return

    # 3. NLP Question Structurer (Hiển thị tổng hợp bộ đề hoàn chỉnh có link nguồn)
    if "questions_list" in details:
        q_list = details.get("questions_list", [])
        summary = details.get("summary", "")
        print(f"             {MAGENTA}🎯  Ngân hàng đề phỏng vấn hoàn chỉnh ({len(q_list)} câu hỏi có nhãn Rubric):{RESET}")
        if summary:
            print(f"             {GRAY}   [{summary}]{RESET}")
        for i, q in enumerate(q_list):
            is_last = (i == len(q_list) - 1)
            prefix = "└─" if is_last else "├─"
            sub_prefix = "   " if is_last else "│  "
            src = q.get("source", "Knowledge Vault")
            url = q.get("url") or q.get("source_url", "")
            q_text = q.get("question", "")
            stage = q.get("stage", "core")
            print(f"             {MAGENTA}{prefix} [Câu {i+1}|{stage}] {WHITE}{q_text}{RESET}")
            print(f"             {MAGENTA}{sub_prefix}  🔗 Nguồn trích xuất: {CYAN}{src}{RESET}")
            if url:
                print(f"             {MAGENTA}{sub_prefix}  🌐 Link bài viết:    {GREEN}{url}{RESET}")
        return

    # 4. Ingest Cache Details
    if "cache_key" in details:
        print(f"             {MAGENTA}├─ 💾 Redis Key:{RESET} {WHITE}{details.get('cache_key')}{RESET}")
        print(f"             {MAGENTA}└─ ⏳ TTL:{RESET} {WHITE}7200 giây (2 giờ){RESET}")
        return

    # 5. Pipeline Summary
    if "total_ingested" in details and "latency_ms" in details:
        latency = details.get("latency_ms", 0)
        total = details.get("total_ingested", 0)
        print(f"             {GREEN}⚡ Kết quả:{RESET} Đã nạp {BOLD}{WHITE}{total}{RESET} câu hỏi vào phòng thi | Độ trễ pipeline: {WHITE}{latency}ms{RESET}")
        return

    # 6. Fallback Key-Value gọn gàng
    items = list(details.items())
    for i, (k, v) in enumerate(items):
        is_last = (i == len(items) - 1)
        prefix = "└─" if is_last else "├─"
        if isinstance(v, list):
            v_str = ", ".join(str(x) for x in v[:4])
            if len(v) > 4:
                v_str += f" (+{len(v)-4} items)"
        elif isinstance(v, dict):
            v_str = json.dumps(v, ensure_ascii=False)
        else:
            v_str = str(v)
        print(f"             {GRAY}{prefix} {k}:{RESET} {WHITE}{v_str}{RESET}")

def print_banner():
    print(f"\n{BOLD}{GREEN}========================================================================================{RESET}")
    print(f"{BOLD}{GREEN} 🤖 CÓC ĐI LÀM — MODEL ORCHESTRATOR & TOOL CALLING ENGINE (LIVE CMD MONITOR){RESET}")
    print(f"{GRAY} [System-1 Active] [MCP Web Search Live Stream] [Question Bank Ingestion Pipeline]{RESET}")
    print(f"{BOLD}{GREEN}========================================================================================{RESET}\n")

def main():
    print_banner()
    api_url = "http://127.0.0.1:8000/api/v1/questions/orchestrator-logs?limit=50"
    seen_ids = set()
    first_connect = True

    print(f"{GRAY}[*] Đang kết nối tới Backend API tại http://127.0.0.1:8000...{RESET}")

    while True:
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Orchestrator-CLI/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                logs = data.get("logs", [])

                if first_connect:
                    print(f"{BOLD}{GREEN}[✓] Đã kết nối thành công! Đang lắng nghe hoạt động Tool Calls & Web Search...{RESET}\n")
                    first_connect = False

                for item in logs:
                    log_id = item.get("id")
                    if log_id in seen_ids:
                        continue
                    seen_ids.add(log_id)

                    ts = item.get("timestamp", "")
                    level = item.get("level", "INFO")
                    tool = item.get("tool_name", "")
                    msg = item.get("message", "")
                    details = item.get("details", {})

                    color, badge_name = get_tool_color(tool, level)

                    # Dòng header của log
                    print(f"{GRAY}{ts}{RESET}  {BOLD}{color}[{badge_name}]{RESET}  {WHITE}{msg}{RESET}")

                    # Hiển thị chi tiết rõ ràng
                    if details and isinstance(details, dict) and len(details) > 0:
                        format_details(tool, level, details)
                    print()

        except urllib.error.URLError:
            if first_connect:
                print(f"{GRAY}[...] Đang đợi Backend uvicorn khởi động trên cổng 8000...{RESET}", end="\r")
        except Exception:
            pass

        time.sleep(1.0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{GRAY}[*] Monitor dừng.{RESET}")
