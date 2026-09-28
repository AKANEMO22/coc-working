import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services.conversational_service import get_conversational_service


async def main():
    service = get_conversational_service()

    print("--- 1. OPENING QUESTION ---")
    opening = service.format_opening_question(
        company="FPT Software",
        role="Java Backend Intern",
        seed_question="Em hãy chia sẻ ngắn gọn về lý do chọn ứng tuyển vị trí Java Backend Intern tại FPT Software và kỳ vọng học hỏi được gì trong kỳ OJT?",
    )
    print(opening)

    print("\n--- 2. TRANSITION TURN 1 -> TURN 2 (HR to Project Defense) ---")
    ans_turn1 = "Dạ em chào anh/chị, em chọn ứng tuyển vào FPT Software vì em mong muốn được cọ xát trong các dự án quy mô lớn, phát triển hệ thống Java Spring Boot và rèn luyện kỹ năng làm việc nhóm theo mô hình Agile/Scrum."
    eval1 = {
        "score": 8.0,
        "points_awarded": ["Khai thác tốt tinh thần cầu tiến và mong muốn tham gia OJT tại FPT Software"],
        "points_missed": [],
    }
    bridge1 = await service.bridge_turn_dialog(
        last_question=opening,
        candidate_answer=ans_turn1,
        evaluation=eval1,
        next_action="switch_topic",
        prev_stage="hr_motivation",
        next_stage="cv_project_defense",
        raw_question="Spring-boot-starter-parent là gì?",
        role="Java Backend Intern",
        company="FPT Software",
    )
    print(bridge1)

    print("\n--- 3. TRANSITION TURN 2 -> TURN 3 (Project Defense to Technical Core) ---")
    ans_turn2 = "Trong dự án tốt nghiệp E-commerce, em xử lý bài toán flash sale bằng Redis Lua Script và Kafka để ngăn chặn overselling và tránh deadlock trên DB."
    eval2 = {
        "score": 8.5,
        "points_awarded": ["Khai thác tốt giải pháp phân tán Redis và Kafka để giải quyết race condition"],
        "points_missed": [],
    }
    bridge2 = await service.bridge_turn_dialog(
        last_question="Spring-boot-starter-parent là gì?",
        candidate_answer=ans_turn2,
        evaluation=eval2,
        next_action="switch_topic",
        prev_stage="cv_project_defense",
        next_stage="technical_core",
        raw_question="Vấn đề N+1 Query trong Spring Data JPA là gì?",
        role="Java Backend Intern",
        company="FPT Software",
    )
    print(bridge2)

    print("\n--- 4. TRANSITION TECHNICAL CORE (Dig Deeper) ---")
    ans_turn3 = "N+1 Query là khi query 1 list cha và mỗi record con lại sinh ra 1 câu select riêng. Em giải quyết bằng Fetch Join hoặc EntityGraph."
    eval3 = {
        "score": 9.0,
        "points_awarded": ["Nêu đúng nguyên nhân và giải pháp Fetch Join và EntityGraph"],
        "points_missed": [],
    }
    bridge3 = await service.bridge_turn_dialog(
        last_question="Vấn đề N+1 Query trong Spring Data JPA là gì?",
        candidate_answer=ans_turn3,
        evaluation=eval3,
        next_action="dig_deeper",
        prev_stage="technical_core",
        next_stage="technical_core",
        raw_question="Sự khác biệt giữa @Transactional(readOnly = true) và transaction thông thường?",
        role="Java Backend Intern",
        company="FPT Software",
    )
    print(bridge3)


if __name__ == "__main__":
    asyncio.run(main())
