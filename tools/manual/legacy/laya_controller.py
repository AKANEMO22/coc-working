"""
CÓC ĐI LÀM — Controller Bridge (Laya -> TypeSafe AI Jev)
Mặt phẳng điều khiển System-1 đã được nâng cấp thay thế toàn bộ Laya bằng TypeSafe AI Jev.
Module này giữ nguyên các hàm và class alias để đảm bảo tương thích ngược 100%.
"""

# Manual tool bootstrap: no imports or network runs from the production app.
import sys
from pathlib import Path
_WORKSPACE = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app" / "main.py").is_file())
sys.path[:0] = [str(_WORKSPACE), str(_WORKSPACE / "backend")]

from app.domains.interview.services.jev_controller import (
    JevController,
    get_jev_controller,
)

# Aliases
LayaController = JevController
get_laya_controller = get_jev_controller

__all__ = ["LayaController", "get_laya_controller", "JevController", "get_jev_controller"]
