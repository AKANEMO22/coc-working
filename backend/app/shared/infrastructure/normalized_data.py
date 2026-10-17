"""Read-only JSON transport adapter; contains no matching or interview rules."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.shared.config import get_settings

logger = logging.getLogger(__name__)


class NormalizedDataStore:
    FILES = {
        "candidates": "candidates_clean.json",
        "jobs": "jobs_below_mid_clean.json",
        "frameworks": "interview_frameworks_clean.json",
    }

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or get_settings().normalized_data_dir).expanduser()
        self._cache: dict[str, tuple[int, list[dict[str, Any]]]] = {}

    @property
    def available(self) -> bool:
        return all((self.data_dir / name).is_file() for name in self.FILES.values())

    def read_records(self, kind: str) -> list[dict[str, Any]]:
        filename = self.FILES[kind]
        path = self.data_dir / filename
        try:
            mtime = path.stat().st_mtime_ns
            cached = self._cache.get(kind)
            if cached and cached[0] == mtime:
                return cached[1]
            with path.open("r", encoding="utf-8") as stream:
                records = json.load(stream)
            if not isinstance(records, list):
                raise ValueError(f"Expected a JSON array in {filename}")
            normalized = [record for record in records if isinstance(record, dict)]
            self._cache[kind] = (mtime, normalized)
            return normalized
        except FileNotFoundError:
            logger.warning("Normalized interview data is unavailable: %s", path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Could not load normalized interview data from %s: %s", path, exc)
        return []



@lru_cache(maxsize=8)
def get_normalized_data_store(data_dir: str | Path | None = None) -> NormalizedDataStore:
    return NormalizedDataStore(data_dir)
