"""The chosen framework, not a generic four-stage template, owns the plan."""

from app.domains.interview.api.sessions import _generate_blueprint
from app.domains.interview.catalog import get_interview_catalog
from app.shared.config import get_settings


def test_ai_blueprint_preserves_source_stage_order_and_weights():
    framework = get_interview_catalog().resolve_framework(framework_id="IF_AI")
    assert framework and len(framework["interview_stages"]) == 5
    plan = _generate_blueprint(
        session_id="test_blueprint", student_id="TEST", company="Demo",
        role="AI Intern", domain_pack="ai", framework=framework,
    )
    assert [stage.stage_name for stage in plan.stages] == [
        item["stage_name"] for item in framework["interview_stages"]
    ]
    assert [stage.description for stage in plan.stages] == [
        item["description"] for item in framework["interview_stages"]
    ]
    assert sum(stage.question_budget for stage in plan.stages) == get_settings().session_scored_question_budget
    assert plan.stages[0].rubric_type.value == "star_framework"
    assert plan.stages[-1].rubric_type.value == "hr_motivation"


def test_framework_without_stages_never_gets_old_four_stage_template():
    plan = _generate_blueprint(
        session_id="test_sparse", student_id="TEST", company="Demo",
        role="Engineer", domain_pack="it", framework={"position_id": "IF_SPARSE"},
    )
    assert len(plan.stages) == 1
    assert plan.stages[0].stage_name == "Role competency"
    assert plan.stages[0].question_budget == get_settings().session_scored_question_budget
