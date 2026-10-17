"""Offline model double for flow tests; never a production speech/question fallback."""

import json
from types import SimpleNamespace

import pytest

import app.shared.infrastructure.redis as redis_core
from app.shared.config import get_settings
from app.domains.interview.services.laya_controller import get_laya_controller
from app.domains.interview.services.questions import QuestionService, get_question_service
from app.domains.interview.services.dialogue import get_interview_dialogue


@pytest.fixture(autouse=True)
def isolated_session_cache(monkeypatch, tmp_path):
    # Model-double sessions must not persist into the user's real dev sessions.
    monkeypatch.setattr(redis_core, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(redis_core, "_in_memory_store", {})
    monkeypatch.setattr(redis_core, "_in_memory_lists", {})
    monkeypatch.setattr(redis_core, "get_redis_client", lambda: None)
    # Unit/E2E suites stay fully offline. The opt-in live Laya smoke is run
    # manually against the already downloaded local checkpoint.
    monkeypatch.setattr(get_settings(), "laya_enabled", False)
    monkeypatch.setattr(get_settings(), "preload_local_speech", False)
    monkeypatch.setattr(get_laya_controller(), "enabled", False)


class RecordingQuestionModel:
    def __init__(self):
        self.calls = []
        self.enabled = True
        self.fixed_text = None
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "prompt": contents})
        if not self.enabled:
            raise RuntimeError("test model is unavailable")
        context = json.loads(contents.split("Ngữ cảnh phiên:\n", 1)[1])
        self.calls[-1]["context"] = context
        stage = context["stage"]["stage_name"]
        outputs = {
            "hr_motivation": "Bạn kỳ vọng tận dụng kinh nghiệm của mình để giải quyết yêu cầu quan trọng nhất trong JD này như thế nào?",
            "cv_project_defense": "Chọn một quyết định thiết kế bạn trực tiếp thực hiện trong dự án; số liệu nào chứng minh lựa chọn đó hiệu quả hơn phương án khác?",
            "technical_core": "Nếu cần thay đổi cơ chế lưu dữ liệu trong sản phẩm hiện có, bạn sẽ kiểm tra tính tương thích của các chức năng bằng cách nào?",
            "applied_scenario": "Khi một dịch vụ phụ thuộc trả kết quả không ổn định, bạn sẽ sắp xếp ưu tiên kiểm tra và giảm ảnh hưởng đến người dùng ra sao?",
        }
        text = self.fixed_text or outputs.get(
            stage,
            "Trong giai đoạn này, bạn có thể nêu một quyết định thực tế liên quan đến yêu cầu của JD và bằng chứng cho kết quả của nó không?",
        )
        if not self.fixed_text and text in context.get("already_asked", []):
            text = "Với một tình huống khác trong JD, bạn sẽ kiểm tra rủi ro kỹ thuật và xác minh kết quả triển khai như thế nào?"
        return SimpleNamespace(text=json.dumps({"question_text": text, "expected_concepts": ["project_evidence"]}))


@pytest.fixture
def generated_model(monkeypatch):
    model = RecordingQuestionModel()
    monkeypatch.setattr(redis_core, "get_redis_client", lambda: None)
    monkeypatch.setattr(QuestionService, "_quota_cooldown_until", 0)
    monkeypatch.setattr(get_question_service(), "gemini_client", model)
    monkeypatch.setattr(get_interview_dialogue(), "client", None)
    return model
