import sys
import os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import httpx
from bs4 import BeautifulSoup
from app.services.crawler_service import get_crawler_service

async def main():
    crawler = get_crawler_service()
    raw_res, domains, questions = await crawler.search_interview_experiences("FPT Software", "Java Backend")
    
    print(f"=== MCP SEARCH DISCOVERED {len(raw_res)} RESULTS ===")
    for i, r in enumerate(raw_res[:5]):
        print(f"[{i+1}] Title: {r.get('title')}")
        print(f"    URL: {r.get('href')}")
        print(f"    Domain: {r.get('domain')}")
        print(f"    RAW SNIPPET: {r.get('body')}")
        print("-" * 50)
    
    # Test a live link from the results
    target_link = None
    for r in raw_res:
        u = r.get("href", "")
        if u and u.startswith("http") and "google.com" not in u:
            target_link = u
            break
            
    if not target_link:
        print("No valid target link found!")
        return

    print(f"\n=== TESTING LIVE HTTP REQUEST TO DISCOVERED LINK ===")
    print(f"Testing URL: {target_link}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0, verify=False) as client:
        try:
            resp = await client.get(target_link)
            print(f"HTTP Status: {resp.status_code}")
            print(f"Final URL after redirects: {resp.url}")
            print(f"Content-Type: {resp.headers.get('content-type')}")
            print(f"Payload Size: {len(resp.content):,} bytes")
            
            soup = BeautifulSoup(resp.text, "html.parser")
            page_title = soup.title.string.strip() if soup.title and soup.title.string else "N/A"
            print(f"Extracted Page Title: {page_title}")
            
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
                tag.decompose()
            clean_text = " ".join(soup.get_text().split())
            print(f"\nRAW PAGE CONTENT (First 600 chars):\n{clean_text[:600]}")
            
            if resp.status_code == 200:
                print("\n>>> RESULT: SUCCESS (200 OK - Link is live and accessible!) <<<")
            else:
                print(f"\n>>> RESULT: Status code {resp.status_code} <<<")
        except Exception as e:
            print(f"Request failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
