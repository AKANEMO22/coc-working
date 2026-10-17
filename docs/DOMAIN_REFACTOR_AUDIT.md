# Domain refactor — audit kết quả

## Phạm vi

- Một backend FastAPI, một composition root `backend/app/main.py`.
- Chuyển source theo domain `candidate`, `interview`, `speech` và shared adapters.
- 51 file đã được di chuyển; nội dung được đối chiếu SHA-256 ngay khi move,
  sau đó import/facade được chỉnh có chủ đích.
- Không chạy DB setup, deploy helper, crawler hoặc test provider live.

## Ranh giới chính

- Candidate sở hữu CV/JD/profile memory; interview chỉ nhận snapshot có kiểu
  `CandidateSessionContext` qua facade, không truy cập profile cache trực tiếp.
- Interview sở hữu framework/rubric, session/WS, generation/evaluation/report.
- Speech sở hữu TTS API/cache; STT vẫn ở browser.
- Shared không import domain; app không import tools/legacy.
- Facade exports/imports được kiểm tra bằng architecture tests.

## Kiểm tra đã chạy

- **31 tests passed**, chạy được từ root và backend với `python -m pytest -q`.
- REST OpenAPI paths, operation contracts và component schemas bằng baseline
  trước khi move; WebSocket URL giữ nguyên.
- Frontend production build thành công.
- Docker Compose config hợp lệ, vẫn chỉ có backend + frontend. Map backend
  host 8000 → container 7860, khớp Dockerfile hiện có.
- Ba JSON có SHA-256 không đổi so với `data/audit-manifest.json`;
  record counts vẫn là **300 candidates / 395 jobs / 25 frameworks**.
- Dataset, backend `.env` và session cache paths được neo vào source; đường dẫn
  `backend/.cache/sessions` giữ nguyên, không xóa session history.

## Giới hạn

- E2E regression dùng provider/model doubles được khai báo rõ. Đây không phải
  chứng nhận chất lượng câu hỏi Gemini, microphone browser hay ElevenLabs live.
- Mã nguồn thư mục cũ đã chuyển hết. Một số thư mục local cũ chỉ còn
  `__pycache__` (và scratch rỗng); môi trường chặn thao tác dọn cache nên chưa xóa.
  Các artifact này bị Git ignore, không là source hoặc dependency của app.
- Đây là modular monolith, **chưa** có deploy/service/data isolation như
  microservices. Xem `backend/app/domains/README.md` về bước tách sau.

Nếu backend cũ đang chạy, cần khởi động lại process để nạp đường dẫn module mới.
