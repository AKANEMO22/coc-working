"""Source-anchored paths, independent of shell cwd and domain module depth."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
