# Domain boundaries — một backend, không phải microservices

`app/main.py` là composition root: khởi tạo một FastAPI và ghép router của các
domain. URL REST/WebSocket và hợp đồng frontend được giữ nguyên.

## Quyền sở hữu

| Domain | Code/dữ liệu sở hữu | Giao diện công khai |
|---|---|---|
| `candidate` | CV/JD, parse/prep, profile memory, chọn sample và lược PII | `facade.load_session_context`, `persist_candidate_selection`, `sample_pair_metadata` |
| `interview` | Framework/rubric, session/blueprint, WS, Laya/Hard Policy, sinh câu hỏi, evaluator/report | `facade` cung cấp catalog/framework guidance cho phần chuẩn bị CV |
| `speech` | VieNeu TTS chạy local, Qwen3-ASR nhận WAV và chuyển lời nói thành văn bản | REST `/api/v1/tts/*`, `/api/v1/stt/transcribe` |

Browser gửi từng cửa sổ WAV khi đang nói và WAV cả lượt nói tới FastAPI để Qwen3-ASR chạy local. File tạm ở backend được xóa sau mỗi lần nhận dạng. VieNeu sinh WAV ở backend và trả về browser; không dùng API giọng nói bên ngoài.

## Quy tắc phụ thuộc

1. Domain được dùng implementation của chính nó và `app/shared`.
2. Gọi domain khác chỉ qua `facade.py`, không import API, service hay repository
   nội bộ của domain đó. Facade không trả raw CV/email/phone cho interview.
3. `shared` chỉ chứa contracts, settings/path, adapter storage và observability;
   không import domain. Loader JSON không có logic chọn ứng viên hay câu hỏi.
4. Candidate quản lý candidate memory; interview không đọc/ghi cache profile
   trực tiếp. Interview nhận `CandidateSessionContext` đã được chuẩn hóa.
5. Không import `tools/` vào app. Script legacy/live chỉ chạy khi người dùng gọi.
6. Framework là tiêu chí để model sinh câu mới. Không crawl và không dùng bank
   hay seed làm lời thoại dự phòng.

Các quy tắc import/cache được kiểm tra bằng tests trong `tests/architecture`.

## Ranh giới chuẩn bị cho việc tách sau

Facade hiện là lời gọi Python trong cùng process. Sau này có thể thay adapter
facade bằng HTTP/message và serialize contracts mà không làm frontend đổi URL.
Việc tách thật vẫn cần data ownership, authentication nội bộ, timeout/retry,
trace propagation và storage bền vững thay cho in-memory/disk fallback.
Không coi cấu trúc folder hiện tại là đã đạt microservices hoặc deploy độc lập.
