"""Compatibility import for the organized interview dialogue package."""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

from app.domains.interview.services.dialogue import (
    InterviewDialogueOrchestrator as ConversationalService,
    get_interview_dialogue,
)


def get_conversational_service() -> ConversationalService:
    return get_interview_dialogue()


__all__ = ["ConversationalService", "get_conversational_service"]
