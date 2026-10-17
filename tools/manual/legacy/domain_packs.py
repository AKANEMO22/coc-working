"""
CÓC ĐI LÀM — Multi-Domain Framework (§20)
Cơ chế đóng gói và nạp các gói tri thức chuyên ngành (Domain Knowledge Packs).
Hỗ trợ:
- IT Software Pack (Công nghệ thông tin & Kỹ thuật phần mềm)
- Business & Digital Marketing Pack (Kinh doanh số & Marketing)
- FinTech & Finance Pack (Tài chính & Công nghệ tài chính)
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class DomainPack(BaseModel):
    domain_id: str
    display_name: str
    description: str
    target_roles: List[str]
    core_competencies: List[str]
    rubric_priorities: Dict[str, float]
    technical_lexicon: List[str]
    seed_topics: List[str]


DOMAIN_PACKS: Dict[str, DomainPack] = {
    "it_software": DomainPack(
        domain_id="it_software",
        display_name="Công nghệ Thông tin & Phần mềm (IT Software)",
        description="Dành cho các vị trí lập trình viên Backend, Frontend, Fullstack, Mobile, DevOps, QA/QC.",
        target_roles=[
            "Java Backend Intern",
            "React Frontend Intern",
            ".NET Developer Intern",
            "Backend Go Intern",
            "Mobile Developer Intern",
            "QA Engineer Intern",
            "Data Analyst Intern",
        ],
        core_competencies=[
            "Data Structures & Algorithms",
            "Database Design (SQL/NoSQL) & Indexing",
            "RESTful API & GraphQL Protocol",
            "System Architecture & Microservices",
            "Clean Code & SOLID Principles",
            "CI/CD, Docker & Containerization",
            "Git Workflow & Code Review",
        ],
        rubric_priorities={
            "technical_correctness": 0.45,
            "star_framework": 0.25,
            "case_study": 0.20,
            "hr_motivation": 0.10,
        },
        technical_lexicon=[
            "React", "Node.js", "Docker", "Kubernetes", "PostgreSQL",
            "MongoDB", "Redis", "Kafka", "RESTful", "OAuth 2.0",
            "Microservices", "CI/CD", "AWS", "FastAPI", "Spring Boot",
        ],
        seed_topics=[
            "Tối ưu truy vấn cơ sở dữ liệu và xử lý deadlock",
            "Thiết kế kiến trúc chịu tải phân tán",
            "Xử lý lỗi ngoại lệ và tính năng tự hồi phục",
        ],
    ),
    "business_marketing": DomainPack(
        domain_id="business_marketing",
        display_name="Kinh tế, Digital Marketing & Quản trị Kinh doanh",
        description="Dành cho các vị trí Marketing Intern, Business Analyst, Growth, Sales B2B.",
        target_roles=[
            "Digital Marketing Intern",
            "Business Development Intern",
            "Business Analyst Intern",
            "Content Strategy Intern",
        ],
        core_competencies=[
            "Customer Acquisition Cost (CAC) & LTV",
            "Conversion Rate Optimization (CRO)",
            "Marketing Funnel & Retention Analysis",
            "Market Research & Competitor Analysis",
            "Requirement Elicitation & BRD/SRS",
        ],
        rubric_priorities={
            "star_framework": 0.35,
            "case_study": 0.30,
            "hr_motivation": 0.20,
            "technical_correctness": 0.15,
        },
        technical_lexicon=[
            "CAC", "LTV", "CRO", "ROAS", "SEO", "SEM", "Funnel", "B2B", "Churn Rate",
        ],
        seed_topics=[
            "Chiến lược tăng trưởng người dùng với ngân sách hạn chế",
            "Phân tích hành vi khách hàng và tối ưu hóa tỷ lệ chuyển đổi",
        ],
    ),
    "fintech_finance": DomainPack(
        domain_id="fintech_finance",
        display_name="Tài chính & FinTech",
        description="Dành cho các vị trí Financial Analyst Intern, Risk Management, Payment Operations.",
        target_roles=[
            "Financial Analyst Intern",
            "Risk Operations Intern",
            "Fintech Product Intern",
        ],
        core_competencies=[
            "Financial Modeling & DCF Valuation",
            "Risk Management & Fraud Detection",
            "Payment Gateway & Settlement Accounting",
            "Compliance & Regulatory Frameworks",
        ],
        rubric_priorities={
            "technical_correctness": 0.40,
            "case_study": 0.30,
            "star_framework": 0.20,
            "hr_motivation": 0.10,
        },
        technical_lexicon=[
            "DCF", "EBITDA", "KYC", "AML", "Payment Gateway", "Reconciliation",
        ],
        seed_topics=[
            "Kiểm soát rủi ro thanh toán và phát hiện giao dịch gian lận",
            "Mô hình hóa dòng tiền dự án đầu tư",
        ],
    ),
}


class DomainPackService:
    """Quản lý các domain packs trong hệ thống."""

    def get_pack(self, domain_id: str) -> DomainPack:
        return DOMAIN_PACKS.get(domain_id, DOMAIN_PACKS["it_software"])

    def list_packs(self) -> List[DomainPack]:
        return list(DOMAIN_PACKS.values())

    def get_pack_for_role(self, role_name: str) -> DomainPack:
        role_lower = role_name.lower()
        for pack in DOMAIN_PACKS.values():
            for r in pack.target_roles:
                if r.lower() in role_lower or role_lower in r.lower():
                    return pack
        return DOMAIN_PACKS["it_software"]


_domain_service = None


def get_domain_pack_service() -> DomainPackService:
    global _domain_service
    if _domain_service is None:
        _domain_service = DomainPackService()
    return _domain_service
