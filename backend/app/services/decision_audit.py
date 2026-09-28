"""
CÓC ĐI LÀM — Decision Audit Service (§16)
Audit typed decisions/evaluations: model_version, policy_version, schema_version, confidence.
"""

from app.models.schemas import AuditRecord, EventType, ValidationStatus
from app.core.config import get_settings
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DecisionAudit:
    """Ghi audit record cho mọi typed decision và evaluation (§16)."""

    def __init__(self):
        self.settings = get_settings()

    def create_audit_record(
        self,
        event_type: EventType,
        session_id: str,
        turn_id: str,
        model_version: str,
        confidence: float,
        input_refs: list[str],
        validation_status: ValidationStatus = ValidationStatus.VALID,
    ) -> AuditRecord:
        """Tạo audit record."""
        record = AuditRecord(
            event_type=event_type,
            session_id=session_id,
            turn_id=turn_id,
            model_version=model_version,
            policy_version=self.settings.policy_version,
            schema_version=self.settings.schema_version,
            confidence=confidence,
            input_refs=input_refs,
            validation_status=validation_status,
            created_at=datetime.utcnow(),
        )
        logger.info(
            f"Audit: {event_type.value} | session={session_id} | turn={turn_id} | "
            f"model={model_version} | conf={confidence:.2f} | status={validation_status.value}"
        )
        return record


def get_decision_audit() -> DecisionAudit:
    return DecisionAudit()
