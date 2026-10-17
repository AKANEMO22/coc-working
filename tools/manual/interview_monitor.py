"""
CÓC ĐI LÀM — Live CLI Monitor for Interview Turn & Audio Engine (§4, §8, §12)
Giám sát toàn bộ luồng phỏng vấn thời gian thực:
Candidate Input -> ASR Gate -> TypeSafe AI Jev Decision -> Rubric Eval -> Question Engine -> Neural TTS Output.
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
        ctypes.windll.kernel32.SetConsoleTitleW("Coc Di Lam - Live Interview & TTS Engine")
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
RED = "\033[91m"
BG_BLUE = "\033[44m"
BG_GREEN = "\033[42m"
BG_AMBER = "\033[48;5;214m"

STAGE_CONFIG = {
    "SESSION_INIT": (GREEN, "🟢 SESSION_INIT", "Khởi tạo phiên phỏng vấn mới"),
    "CANDIDATE_INPUT": (AMBER, "🎤 CANDIDATE_INPUT", "Nhận câu trả lời từ ứng viên"),
    "ASR_GATE": (CYAN, "🛡️  ASR_GATE", "Kiểm định an toàn và chất lượng âm thanh"),
    "RUBRIC_EVAL": (GREEN, "⚡ RUBRIC_EVAL", "Đánh giá bằng chứng và chấm điểm Rubric"),
    "JEV_DECISION": (MAGENTA, "🧠 JEV_DECISION", "TypeSafe AI Jev Controller điều phối luồng"),
    "QUESTION_ENGINE": (WHITE, "💬 QUESTION_ENGINE", "Bộ máy sinh & tuyển chọn câu hỏi"),
    "NEURAL_TTS": (BLUE, "🔊 NEURAL_TTS", "Tổng hợp giọng nói chuẩn người thật"),
    "USER_BARGE_IN": (RED, "🛑 USER_BARGE_IN", "Ứng viên ngắt lời phỏng vấn viên"),
    "SYSTEM_READY": (CYAN, "🔵 SYSTEM_READY", "Hệ thống sẵn sàng hoạt động"),
}

def format_interview_details(stage: str, details: dict):
    """Hiển thị chi tiết từng bước dạng cây phân cấp trực quan."""
    st = stage.upper()

    # 1. Ứng viên trả lời (Candidate Input)
    if st == "CANDIDATE_INPUT":
        transcript = details.get("final_transcript", "")
        words = details.get("word_count", 0)
        terms = details.get("term_candidates", [])
        verified = details.get("verified", False)
        print(f"             {AMBER}├─ 📝 Nội dung ghi âm ASR ({words} từ):{RESET} {WHITE}\"{transcript}\"{RESET}")
        if terms:
            terms_str = ", ".join(f"#{t}" for t in terms)
            print(f"             {AMBER}├─ 🏷️  Thuật ngữ chuyên ngành nhận diện:{RESET} {CYAN}{terms_str}{RESET}")
        print(f"             {AMBER}└─ 🎙️  Trạng thái xác thực:{RESET} {GREEN if verified else WHITE}{'Đã xác thực thủ công' if verified else 'Nhận diện tự động'}{RESET}")
        return

    # 2. Hàng rào kiểm định ASR Gate
    if st == "ASR_GATE":
        safe = details.get("transcript_safe", True)
        conf = details.get("confidence", 1.0)
        action = details.get("action", "proceed_to_eval")
        crit = details.get("has_critical_disagreement", False)
        safe_str = f"{GREEN}AN TOÀN (Safe){RESET}" if safe else f"{RED}CẦN XÁC MINH (Unsafe){RESET}"
        print(f"             {CYAN}├─ 🛡️  Kết quả kiểm định:{RESET} {safe_str} | Độ tin cậy ASR: {BOLD}{WHITE}{conf:.2f}{RESET}")
        print(f"             {CYAN}├─ ⚙️  Hành động tiếp theo:{RESET} {WHITE}{action}{RESET}")
        print(f"             {CYAN}└─ ⚠️  Xung đột thuật ngữ nghiêm trọng:{RESET} {RED if crit else GREEN}{'Có' if crit else 'Không'}{RESET}")
        return

    # 3. Đánh giá Rubric
    if st == "RUBRIC_EVAL":
        rubric = details.get("rubric_type", "technical_correctness")
        score = details.get("score", 0.0)
        conf = details.get("confidence", 1.0)
        latency = details.get("eval_latency_ms", 0)
        awarded = details.get("points_awarded", [])
        missed = details.get("points_missed", [])
        fast_path = details.get("is_fast_path", False)
        
        mode_str = f"{GREEN}⚡ Fast-Path Heuristic ({latency}ms){RESET}" if fast_path else f"{CYAN}Gemini Flash ({latency}ms){RESET}"
        print(f"             {GREEN}├─ 📊 Tiêu chí Rubric:{RESET} {BOLD}{WHITE}{rubric}{RESET} | Điểm số: {BOLD}{GREEN if score >= 7 else AMBER}{score:.1f}/10.0{RESET} ({mode_str})")
        if awarded:
            print(f"             {GREEN}├─ ✅ Điểm đạt được:{RESET}")
            for p in awarded[:3]:
                print(f"             {GREEN}│  • {WHITE}{p}{RESET}")
        if missed:
            print(f"             {AMBER}├─ ⚠️  Điểm còn thiếu / cần cải thiện:{RESET}")
            for m in missed[:2]:
                print(f"             {AMBER}│  • {WHITE}{m}{RESET}")
        print(f"             {GREEN}└─ 🎯 Độ tin cậy đánh giá:{RESET} {WHITE}{conf:.2f}{RESET}")
        return

    # 4. TypeSafe AI Jev Decision
    if st == "JEV_DECISION":
        action = details.get("next_action", "next_question")
        conf = details.get("confidence", 1.0)
        budget = details.get("remaining_budget", 0)
        topic = details.get("current_stage", "technical_core")
        print(f"             {MAGENTA}├─ 🧠 Quyết định của Controller:{RESET} {BOLD}{WHITE}[{action.upper()}]{RESET} (Tin cậy: {WHITE}{conf:.2f}{RESET})")
        print(f"             {MAGENTA}├─ 📂 Giai đoạn hiện tại:{RESET} {WHITE}{topic}{RESET}")
        print(f"             {MAGENTA}└─ ⏳ Ngân sách câu hỏi còn lại:{RESET} {WHITE}{budget} câu{RESET}")
        return

    # 5. Question Engine
    if st == "QUESTION_ENGINE":
        q_text = details.get("question_text", "")
        stage = details.get("stage_name", "")
        rubric = details.get("target_rubric", "")
        concepts = details.get("expected_concepts", [])
        print(f"             {WHITE}├─ 💬 Nội dung câu hỏi:{RESET} {BOLD}{CYAN}\"{q_text}\"{RESET}")
        print(f"             {WHITE}├─ 📌 Giai đoạn & Tiêu chí:{RESET} {WHITE}{stage} ({rubric}){RESET}")
        if concepts:
            c_str = ", ".join(concepts)
            print(f"             {WHITE}└─ 🎯 Khái niệm kỳ vọng đánh giá:{RESET} {WHITE}{c_str}{RESET}")
        else:
            print(f"             {WHITE}└─ 🎯 Nguồn câu hỏi:{RESET} {GREEN}Interview Blueprint & Adaptive Logic{RESET}")
        return

    # 6. Neural TTS Output
    if st == "NEURAL_TTS":
        voice = details.get("voice", "ElevenLabs Voice")
        words = details.get("word_count", 0)
        size_kb = details.get("audio_size_kb", 0)
        latency = details.get("latency_ms", 0)
        cache_hit = details.get("cache_hit", False)
        text_snip = details.get("text", "")
        source_str = f"{GREEN}Bộ đệm siêu tốc (LRU Cache){RESET}" if cache_hit else f"{BLUE}ElevenLabs TTS API{RESET}"
        print(f"             {BLUE}├─ 🔊 Giọng đọc:{RESET} {BOLD}{WHITE}{voice}{RESET} ({source_str})")
        print(f"             {BLUE}├─ ⚡ Thời gian tổng hợp:{RESET} {BOLD}{WHITE}{latency}ms{RESET} | Kích thước audio: {BOLD}{WHITE}{size_kb} KB{RESET} (MP3 {words} từ)")
        print(f"             {BLUE}└─ 📜 Trích đoạn văn bản đọc:{RESET} {WHITE}\"{text_snip[:90]}{'...' if len(text_snip) > 90 else ''}\"{RESET}")
        return

    # 7. User Barge-in
    if st == "USER_BARGE_IN":
        count = details.get("interruption_count", 1)
        print(f"             {RED}├─ 🛑 Hành động:{RESET} {BOLD}{RED}Cắt luồng phát âm thanh TTS ngay lập tức (Barge-in Safe){RESET}")
        print(f"             {RED}└─ 🔢 Tổng số lần ứng viên ngắt lời:{RESET} {WHITE}{count} lần{RESET}")
        return

    # 8. Session Init
    if st == "SESSION_INIT":
        student = details.get("student_id", "")
        company = details.get("company", "")
        role = details.get("role", "")
        stages_cnt = details.get("total_stages", 4)
        print(f"             {GREEN}├─ 🎓 Ứng viên MSSV:{RESET} {BOLD}{WHITE}{student}{RESET} | Doanh nghiệp mục tiêu: {BOLD}{WHITE}{company}{RESET}")
        print(f"             {GREEN}├─ 💼 Vị trí ứng tuyển:{RESET} {BOLD}{WHITE}{role}{RESET}")
        print(f"             {GREEN}└─ 📋 Khung đề Blueprint:{RESET} {WHITE}{stages_cnt} giai đoạn thi chuẩn OJT{RESET}")
        return

    # Fallback key-value
    for i, (k, v) in enumerate(details.items()):
        is_last = (i == len(details) - 1)
        prefix = "└─" if is_last else "├─"
        print(f"             {GRAY}{prefix} {k}:{RESET} {WHITE}{v}{RESET}")

def print_banner():
    print(f"\n{BOLD}{CYAN}========================================================================================{RESET}")
    print(f"{BOLD}{CYAN} 🎙️ CÓC ĐI LÀM — LIVE INTERVIEW TURN & AUDIO ENGINE (CMD MONITOR){RESET}")
    print(f"{GRAY} [Real-time Pipeline: Candidate Input -> ASR Gate -> Rubric Eval -> Jev -> Neural TTS]{RESET}")
    print(f"{BOLD}{CYAN}========================================================================================{RESET}\n")

def main():
    print_banner()
    api_url = "http://127.0.0.1:8000/api/v1/sessions/live-logs?limit=60"
    seen_ids = set()
    first_connect = True

    print(f"{GRAY}[*] Đang kết nối tới Backend API tại http://127.0.0.1:8000...{RESET}")

    while True:
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "InterviewTurnMonitor/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    if first_connect:
                        print(f"{GREEN}[✓] Đã kết nối thành công! Đang lắng nghe luồng phỏng vấn & âm thanh...{RESET}\n")
                        first_connect = False

                    data = json.loads(resp.read().decode("utf-8"))
                    logs = data.get("logs", [])

                    for item in logs:
                        log_id = item.get("id")
                        if log_id in seen_ids:
                            continue
                        seen_ids.add(log_id)

                        ts = item.get("timestamp", "")
                        stage = item.get("stage", "STAGE")
                        msg = item.get("message", "")
                        details = item.get("details", {})

                        color, badge, _ = STAGE_CONFIG.get(stage, (YELLOW, f"[{stage}]", ""))

                        print(f"{GRAY}{ts}{RESET}  {color}{BOLD}{badge:<20}{RESET}  {WHITE}{msg}{RESET}")

                        if details:
                            try:
                                format_interview_details(stage, details)
                            except Exception:
                                pass
                        print()

        except urllib.error.URLError:
            if first_connect:
                print(f"{GRAY}[...] Đang đợi Backend khởi động (thử lại sau 2 giây)...{RESET}", end="\r")
            time.sleep(2)
            continue
        except Exception:
            time.sleep(1)
            continue

        time.sleep(0.4)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{GRAY}[*] Đã tắt Interview Engine Monitor.{RESET}")
        sys.exit(0)
