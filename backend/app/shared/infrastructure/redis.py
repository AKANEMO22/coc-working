"""
CÓC ĐI LÀM — Upstash Redis Client
Quản lý trạng thái phiên nóng (hot state), rate limiting, và bộ nhớ đệm.
"""

from upstash_redis import Redis
from app.shared.config import get_settings
from functools import lru_cache
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache()
def get_redis_client() -> Redis | None:
    """Tạo Upstash Redis client nếu có credentials."""
    settings = get_settings()
    if not settings.upstash_redis_url or not settings.upstash_redis_token:
        logger.info("Upstash Redis credentials not configured. Using in-memory fallback.")
        return None

    try:
        client = Redis(
            url=settings.upstash_redis_url,
            token=settings.upstash_redis_token,
        )
        logger.info("Upstash Redis client initialized successfully.")
        return client
    except Exception as e:
        logger.warning(f"Failed to connect to Upstash Redis: {e}. Falling back to in-memory store.")
        return None


from pathlib import Path
from app.shared.paths import BACKEND_ROOT

# Local disk cache directory for sessions persistence across uvicorn reloads
CACHE_DIR = BACKEND_ROOT / ".cache" / "sessions"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Global in-memory storage fallback
_in_memory_store: dict[str, Any] = {}
_in_memory_lists: dict[str, list[str]] = {}


class RedisSessionManager:
    """Quản lý trạng thái phiên phỏng vấn nóng trong Redis hoặc In-Memory Fallback."""

    def __init__(self, client: Redis | None = None):
        self.client = client if client is not None else get_redis_client()
        self.session_ttl = 7200  # 2 giờ TTL cho hot state

    # --- Hot Session State (§7.2) ---

    def get_hot_state(self, session_id: str) -> dict | None:
        """Đọc trạng thái nóng của phiên đang diễn ra."""
        key = f"session:{session_id}:hot_state"
        if self.client:
            try:
                data = self.client.get(key)
                if data:
                    return json.loads(data) if isinstance(data, str) else data
                return None
            except Exception as e:
                logger.warning(f"Redis get failed: {e}. Checking memory store.")
        data = _in_memory_store.get(key)
        if data:
            return json.loads(data) if isinstance(data, str) else data

        # Check disk cache if in-memory store missed (e.g. uvicorn reloaded)
        file_path = CACHE_DIR / f"{session_id}_hot_state.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                    _in_memory_store[key] = json.dumps(disk_data, ensure_ascii=False)
                    return disk_data
            except Exception as e:
                logger.warning(f"Disk cache read failed: {e}")

        return None

    def set_hot_state(self, session_id: str, state: dict) -> None:
        """Ghi/cập nhật trạng thái nóng của phiên."""
        key = f"session:{session_id}:hot_state"
        serialized = json.dumps(state, ensure_ascii=False)
        _in_memory_store[key] = serialized

        # Write to disk cache
        file_path = CACHE_DIR / f"{session_id}_hot_state.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Disk cache write failed: {e}")

        if self.client:
            try:
                self.client.set(key, serialized, ex=self.session_ttl)
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")

    def update_hot_state_field(self, session_id: str, field: str, value: Any) -> None:
        """Cập nhật một trường cụ thể trong hot state."""
        state = self.get_hot_state(session_id)
        if state:
            state[field] = value
            self.set_hot_state(session_id, state)

    def delete_hot_state(self, session_id: str) -> None:
        """Xóa hot state khi phiên kết thúc."""
        key = f"session:{session_id}:hot_state"
        _in_memory_store.pop(key, None)
        if self.client:
            try:
                self.client.delete(key)
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")

    # --- Turn Buffer ---

    def push_turn_buffer(self, session_id: str, partial_data: dict) -> None:
        """Đẩy partial transcript vào buffer."""
        key = f"session:{session_id}:turn_buffer"
        serialized = json.dumps(partial_data, ensure_ascii=False)
        _in_memory_lists.setdefault(key, []).append(serialized)
        if self.client:
            try:
                self.client.rpush(key, serialized)
                self.client.expire(key, self.session_ttl)
            except Exception as e:
                logger.warning(f"Redis push buffer failed: {e}")

    def get_turn_buffer(self, session_id: str) -> list[dict]:
        """Đọc toàn bộ turn buffer."""
        key = f"session:{session_id}:turn_buffer"
        if self.client:
            try:
                data = self.client.lrange(key, 0, -1)
                if data:
                    return [json.loads(item) if isinstance(item, str) else item for item in data]
            except Exception as e:
                logger.warning(f"Redis get buffer failed: {e}")
        data = _in_memory_lists.get(key, [])
        return [json.loads(item) if isinstance(item, str) else item for item in data]

    def clear_turn_buffer(self, session_id: str) -> None:
        """Xóa turn buffer sau khi tạo Final Transcript."""
        key = f"session:{session_id}:turn_buffer"
        _in_memory_lists.pop(key, None)
        if self.client:
            try:
                self.client.delete(key)
            except Exception as e:
                logger.warning(f"Redis clear buffer failed: {e}")

    # --- Candidate Memory Cache (§7.3) ---

    def cache_candidate_memory(self, student_id: str, memory: dict, ttl: int = 3600) -> None:
        """Cache Compact Long-Term Candidate Memory cho phiên hiện tại."""
        key = f"candidate:{student_id}:memory_cache"
        serialized = json.dumps(memory, ensure_ascii=False)
        _in_memory_store[key] = serialized

        # Lưu disk cache cho đồng bộ đa tiến trình (uvicorn, test, background jobs)
        safe_key = "".join(c if c.isalnum() or c in "._-" else "_" for c in student_id)
        file_path = CACHE_DIR / f"{safe_key}_cand_mem.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Disk cache candidate memory write failed: {e}")

        if self.client:
            try:
                self.client.set(key, serialized, ex=ttl)
            except Exception as e:
                logger.warning(f"Redis cache memory failed: {e}")

    def get_cached_candidate_memory(self, student_id: str) -> dict | None:
        """Đọc cached memory cho phiên hiện tại."""
        key = f"candidate:{student_id}:memory_cache"
        if self.client:
            try:
                data = self.client.get(key)
                if data:
                    return json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                logger.warning(f"Redis get cached memory failed: {e}")

        data = _in_memory_store.get(key)
        if data:
            return json.loads(data) if isinstance(data, str) else data

        # Kiểm tra disk cache nếu in-memory rỗng
        safe_key = "".join(c if c.isalnum() or c in "._-" else "_" for c in student_id)
        file_path = CACHE_DIR / f"{safe_key}_cand_mem.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                    _in_memory_store[key] = json.dumps(disk_data, ensure_ascii=False)
                    return disk_data
            except Exception as e:
                logger.warning(f"Disk cache candidate memory read failed: {e}")

        return None

    # --- Rate Limiting ---

    def check_rate_limit(self, client_ip: str, max_requests: int = 10, window_sec: int = 60) -> bool:
        """
        Kiểm tra rate limit cho một IP.
        Returns True nếu request được phép, False nếu bị giới hạn.
        """
        key = f"ratelimit:{client_ip}"
        if self.client:
            try:
                current = self.client.get(key)
                if current is None:
                    self.client.set(key, 1, ex=window_sec)
                    return True
                count = int(current)
                if count >= max_requests:
                    return False
                self.client.incr(key)
                return True
            except Exception as e:
                logger.warning(f"Redis rate limit failed: {e}")
        # In-memory fallback for rate limiting
        count = _in_memory_store.get(key, 0)
        if count >= max_requests:
            return False
        _in_memory_store[key] = count + 1
        return True

    # --- Interview Blueprint Cache ---

    def cache_blueprint(self, session_id: str, blueprint: dict) -> None:
        """Cache Interview Blueprint cho phiên."""
        key = f"session:{session_id}:blueprint"
        serialized = json.dumps(blueprint, ensure_ascii=False)
        _in_memory_store[key] = serialized

        # Write to disk cache
        file_path = CACHE_DIR / f"{session_id}_blueprint.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(blueprint, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Disk cache blueprint write failed: {e}")

        if self.client:
            try:
                self.client.set(key, serialized, ex=self.session_ttl)
            except Exception as e:
                logger.warning(f"Redis cache blueprint failed: {e}")

    def get_blueprint(self, session_id: str) -> dict | None:
        """Đọc cached blueprint."""
        key = f"session:{session_id}:blueprint"
        if self.client:
            try:
                data = self.client.get(key)
                if data:
                    return json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                logger.warning(f"Redis get blueprint failed: {e}")
        data = _in_memory_store.get(key)
        if data:
            return json.loads(data) if isinstance(data, str) else data

        # Check disk cache
        file_path = CACHE_DIR / f"{session_id}_blueprint.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_bp = json.load(f)
                    _in_memory_store[key] = json.dumps(disk_bp, ensure_ascii=False)
                    return disk_bp
            except Exception as e:
                logger.warning(f"Disk cache blueprint read failed: {e}")

        return None

    # --- Turn Evaluations (§6, §14) ---

    def save_turn_evaluation(self, session_id: str, turn_data: dict) -> None:
        """Lưu kết quả đánh giá thực tế của một lượt phỏng vấn."""
        key = f"session:{session_id}:turns"
        serialized = json.dumps(turn_data, ensure_ascii=False)
        _in_memory_lists.setdefault(key, []).append(serialized)

        # Lưu cache file disk
        file_path = CACHE_DIR / f"{session_id}_turns.json"
        try:
            current_turns = []
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    current_turns = json.load(f)
            current_turns.append(turn_data)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(current_turns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Disk cache turns write failed: {e}")

        if self.client:
            try:
                self.client.rpush(key, serialized)
                self.client.expire(key, self.session_ttl)
            except Exception as e:
                logger.warning(f"Redis save turn evaluation failed: {e}")

    def get_turn_evaluations(self, session_id: str) -> list[dict]:
        """Truy xuất danh sách kết quả đánh giá các lượt phỏng vấn thực tế."""
        key = f"session:{session_id}:turns"
        if self.client:
            try:
                data = self.client.lrange(key, 0, -1)
                if data:
                    return [json.loads(item) if isinstance(item, str) else item for item in data]
            except Exception as e:
                logger.warning(f"Redis get turn evaluations failed: {e}")

        # In-memory store
        mem_data = _in_memory_lists.get(key)
        if mem_data:
            return [json.loads(item) if isinstance(item, str) else item for item in mem_data]

        # Check disk cache
        file_path = CACHE_DIR / f"{session_id}_turns.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_turns = json.load(f)
                    _in_memory_lists[key] = [json.dumps(t, ensure_ascii=False) for t in disk_turns]
                    return disk_turns
            except Exception as e:
                logger.warning(f"Disk cache turns read failed: {e}")

        return []

    # --- Generated Report Cache ---

    def cache_report(self, session_id: str, report: dict) -> None:
        """Cache báo cáo đánh giá đã tổng hợp."""
        key = f"session:{session_id}:report"
        serialized = json.dumps(report, ensure_ascii=False)
        _in_memory_store[key] = serialized

        file_path = CACHE_DIR / f"{session_id}_report.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Disk cache report write failed: {e}")

        if self.client:
            try:
                self.client.set(key, serialized, ex=self.session_ttl)
            except Exception as e:
                logger.warning(f"Redis cache report failed: {e}")

    def get_cached_report(self, session_id: str) -> dict | None:
        """Đọc báo cáo đánh giá từ cache."""
        key = f"session:{session_id}:report"
        if self.client:
            try:
                data = self.client.get(key)
                if data:
                    return json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                logger.warning(f"Redis get report failed: {e}")

        data = _in_memory_store.get(key)
        if data:
            return json.loads(data) if isinstance(data, str) else data

        file_path = CACHE_DIR / f"{session_id}_report.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_report = json.load(f)
                    _in_memory_store[key] = json.dumps(disk_report, ensure_ascii=False)
                    return disk_report
            except Exception as e:
                logger.warning(f"Disk cache report read failed: {e}")

        return None

