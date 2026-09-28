"""
CÓC ĐI LÀM — Controller Bridge (Laya -> TypeSafe AI Jev)
Mặt phẳng điều khiển System-1 đã được nâng cấp thay thế toàn bộ Laya bằng TypeSafe AI Jev.
Module này giữ nguyên các hàm và class alias để đảm bảo tương thích ngược 100%.
"""

from app.services.jev_controller import (
    JevController,
    get_jev_controller,
)

# Aliases
LayaController = JevController
get_laya_controller = get_jev_controller

__all__ = ["LayaController", "get_laya_controller", "JevController", "get_jev_controller"]
