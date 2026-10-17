# Công cụ vận hành/thử thủ công — không thuộc luồng app

- `manual/interview_monitor.py`: xem log phiên trên backend đang chạy.
- `manual/live/`: thử hội thoại/WebSocket/E2E thật; có thể gọi provider và tiêu
  tốn quota. Chỉ chạy khi chủ động yêu cầu, không nằm trong pytest mặc định.
- `manual/legacy/`: script/crawler/adapter cũ giữ để tham khảo. Crawl tự động đã
  bị bỏ; workflow discovery cũ không còn là tính năng của app.
- `admin/`: setup PostgreSQL và deploy HF. Các lệnh này có tác động bên ngoài;
  việc refactor chỉ chuyển file, không chạy setup/deploy.

Ví dụ chạy từ root project sau khi đã cài dependencies và bật backend:

```powershell
python tools/manual/interview_monitor.py
python tools/manual/live/websocket_probe.py
```

Mỗi tool tự tìm backend source path, không phụ thuộc vị trí shell hiện tại.
Test tự động nằm trong `backend/tests/`; `python -m pytest -q` chạy được từ root
hoặc backend. Root `pytest.ini` giới hạn testpaths, không tự quét/chạy tools.
Mã nguồn `backend/scratch` đã được gom sang tools; không còn script `test_*.py`
rải ở backend root. Nếu máy còn thư mục cũ chỉ chứa `__pycache__`, đó là artifact
local bị Git ignore, không được production hoặc pytest import.

Deploy helper chỉ upload code backend, không tự public/upload ba JSON CV/JD.
Hosting phải được cấp dataset qua mount/private storage và cấu hình
`NORMALIZED_DATA_DIR` riêng. Refactor này không triển khai dịch vụ lên mạng.
