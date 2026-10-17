# Backend phỏng vấn Cóc Đi Làm

Đây là một FastAPI chia theo domain trong `app/domains/`. `app/main.py` ghép các router; không có service triển khai độc lập. Kiến trúc và luồng CV/JD → câu hỏi → giọng nói → rubric ở [README gốc](../README.md).

| Domain | Trách nhiệm |
|---|---|
| `candidate` | Đọc CV/JD đã chuẩn hóa; tạo `CandidateSessionContext` |
| `interview` | Chọn khung từ JD, dựng blueprint, WebSocket, Laya, Hard Policy, Gemini, rubric/report |
| `speech` | Qwen3-ASR nhận WAV ở `/api/v1/stt/transcribe`; VieNeu TTS trả WAV ở `/api/v1/tts/synthesize` và `/api/v1/tts/synthesize-aligned` |
| `shared` | Settings, contracts, cache/session storage, observability |

`GET /health` cho biết backend và Laya đã tải hay chưa. `GET /api/v1/tts/voices` trả voice preset và cấu hình TTS đang dùng. `GET /api/v1/sessions/live-logs` cung cấp timing của câu hỏi, Laya và các bước phỏng vấn. Các route debug chỉ mở khi backend chạy development local.

Cấu hình tại `backend/.env` theo `backend/.env.example`. Giọng mặc định là VieNeu `Hải Đăng`; đổi `VIENEU_VOICE` rồi khởi động lại backend. Mặc định Qwen3-ASR và VieNeu dùng CUDA/VRAM, còn Laya chạy CPU/RAM (`LAYA_DEVICE=cpu`, `LAYA_FAST=false`). Các biến `VIENEU_DEVICE`, `VIENEU_MAX_BATCH_SIZE`, `VIENEU_MAX_STREAMS`, `VIENEU_TEMPERATURE`, `VIENEU_TOP_K`, `VIENEU_TOP_P`, `STT_DEVICE`, `LAYA_DEVICE`, `LAYA_FAST` cho phép tự chỉnh thiết bị và độ trễ. Gemini cần `GOOGLE_GEMINI_API_KEY`; ba model giọng/decision chạy local, không cần key speech.

`PRELOAD_LOCAL_SPEECH=true` bắt đầu tải VieNeu và Qwen3-ASR ngay sau khi backend lên, giảm độ trễ của câu nói đầu. Khi ASR gate không chắc, backend giữ bản nháp, nhờ Gemini viết lời hỏi lại, rồi so hai lượt nhận dạng trước khi ghi câu trả lời; giao diện không bắt xác nhận bằng nút. Silero chạy local trong browser; khi worker chưa sẵn sàng, energy VAD local tự chốt nhịp nói.

Mỗi WAV micro chỉ tồn tại trong bộ nhớ browser và file tạm ở backend trong lúc Qwen nhận dạng; file tạm được xóa trong `finally`. VieNeu sinh WAV và mốc hiển thị chữ **ước lượng** theo tổng thời lượng audio vì model không trả mốc từng âm tiết.

Chạy regression từ root: `python -m pytest backend/tests -q`. Kiểm tra model/route thật: `python tools/preflight_local_models.py`. Benchmark hai phiên đầy đủ: `python tools/benchmarks/benchmark_interview_local_two_runs.py --live --runs 2` (gọi Gemini API thật).
