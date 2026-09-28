import sys
import os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import httpx
from bs4 import BeautifulSoup
from app.services.orchestrator_service import get_orchestrator_service

async def main():
    print("=" * 70)
    print("TESTING FULL ORCHESTRATOR DISCOVERY & LIVE LINK ACCESSIBILITY")
    print("=" * 70)
    
    orchestrator = get_orchestrator_service()
    
    # 1. Run discovery for FPT Software / Java Backend
    print("\n>>> BƯỚC 1: Chạy execute_discovery_and_ingest...")
    result = await orchestrator.execute_discovery_and_ingest(
        company="FPT Software",
        role="Java Backend",
        student_id="TEST_USER_01"
    )
    
    questions = result.get("questions", [])
    print(f"\n>>> Hoàn thành! Đã nạp {len(questions)} câu hỏi vào ngân hàng đề thi.")
    
    print("\n" + "=" * 70)
    print("DANH SÁCH CÂU HỎI KÈM LINK THỰC TẾ ĐƯỢC GÁN:")
    print("=" * 70)
    
    tested_urls = []
    for idx, q in enumerate(questions):
        q_text = q.get("question")
        q_source = q.get("source")
        q_url = q.get("url")
        print(f"\n[Q{idx+1}] {q_text}")
        print(f"     Nguồn: {q_source}")
        print(f"     URL  : {q_url}")
        if q_url and q_url.startswith("http") and q_url not in tested_urls:
            tested_urls.append(q_url)
            
    print("\n" + "=" * 70)
    print(f"KIỂM TRA TRỰC TIẾP {min(3, len(tested_urls))} LINK BẰNG HTTP GET (XÁC MINH 200 OK & RAW CONTENT):")
    print("=" * 70)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0, verify=False) as client:
        for idx, test_url in enumerate(tested_urls[:3]):
            print(f"\n[{idx+1}] Kiểm tra: {test_url}")
            try:
                resp = await client.get(test_url)
                print(f"    📡 Status Code: {resp.status_code}")
                print(f"    📦 Payload: {len(resp.content):,} bytes")
                print(f"    📑 Content-Type: {resp.headers.get('content-type')}")
                
                soup = BeautifulSoup(resp.text, "html.parser")
                page_title = soup.title.string.strip() if soup.title and soup.title.string else "N/A"
                print(f"    🏷️  Tiêu đề trang: {page_title}")
                
                for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
                    tag.decompose()
                clean_text = " ".join(soup.get_text().split())
                print(f"    📄 Dữ liệu thô trích xuất từ trang web (RAW HTML Body 250 ký tự đầu):")
                print(f"       \"{clean_text[:250]}...\"")
                
                if resp.status_code == 200:
                    print(f"    ✅ KẾT QUẢ: 200 OK - Link sống 100%, không bị 404!")
                else:
                    print(f"    ⚠️ KẾT QUẢ: Mã phản hồi {resp.status_code}")
            except Exception as e:
                print(f"    ❌ Lỗi kết nối: {e}")

if __name__ == "__main__":
    asyncio.run(main())
