# Kịch bản kiểm thử E2E phỏng vấn bằng giọng nói

Tài liệu này kiểm tra partial transcript → Laya điều phối trực tiếp/hỏi lại → answer được giữ và chốt → câu hỏi tiếp theo; rubric chỉ chạy sau khi kết thúc phiên. Câu hỏi do Orchestrator sinh theo CV/JD/framework, nên các câu dưới đây là nhánh trả lời theo chủ đề, không phải câu hỏi hardcode cần chờ đúng nguyên văn.

## 0. Trước khi thử

1. Tại thư mục project, chạy: python dev_runner.py start.
2. Mở http://127.0.0.1:3000/interview.
3. Cho phép browser dùng microphone khi được hỏi. Nếu đã thấy thông tin ứng viên ở đầu trang thì giữ tài khoản đó; nếu chưa, đăng nhập MSSV/guest.
4. Không dùng nút Gửi câu trả lời mẫu (dev) khi đang kiểm thử STT. Nút dev gửi transcript mẫu trực tiếp vào WebSocket, bỏ qua microphone và nhận dạng giọng nói.
5. Mở thêm http://127.0.0.1:3000/debug hoặc nút Log phỏng vấn để quan sát luồng.

## 1. Kịch bản chính: Java Backend Intern, CV/JD cùng chuyên môn

Đây là cặp có trong normalized catalog và framework đã được ánh xạ chính xác.

### Chọn dữ liệu

1. Trong Lọc JD theo vị trí muốn luyện:
   - Chuyên môn: chọn Software Developer (Lập trình viên Phần mềm) nếu dropdown dùng nhãn canonical tổng quát.
   - Cấp độ: Intern.
2. Trong dropdown CV chọn:
   - CV_JAVA_002 · Backend Developer (Java / Spring Boot) · 1 dự án.
3. Trong dropdown JD chọn đúng dòng:
   - itv_0040 · JAVA BACKEND SPRING BOOT Intern · Intern · FPT IS.
4. Kiểm tra preview khung:
   - Backend Developer - Java, framework IF_BE_JAVA.
   - Không hiện cảnh báo CV khác chuyên môn.
5. Bấm Bắt đầu phiên phỏng vấn. Không cần bấm nút micro để bắt đầu nói; chờ phỏng vấn viên đọc xong, trạng thái Micro đang nghe xuất hiện.

> Nếu nhãn chuyên môn trong dropdown hơi rộng, hãy chọn JD theo đúng tên/job ID. Khung được xác định theo JD đã chọn; không suy ra từ tên bộ lọc hoặc thay JD khác.

### Lời đáp mẫu theo chủ đề

Nói một câu trả lời cho mỗi lượt hỏi, đừng đọc toàn bộ phần này thành một bài dài. Đây là nội dung giả lập để test; sửa các chi tiết dự án cho đúng trải nghiệm thật của bạn. Trong dữ liệu CV_JAVA_002, dự án chỉ có tên Banking Software, chưa có mô tả đóng góp chi tiết, nên không khẳng định số liệu/kết quả không có thật.

**A. Giới thiệu / động lực**

> “Em đang định hướng Java Backend và đã học Java, Spring Boot, SQL, Hibernate, MySQL và REST API. Em muốn thực tập để rèn cách xây API, kiểm thử và làm việc theo quy trình review. Trong CV em có project Banking Software; em muốn trao đổi rõ hơn phần em trực tiếp làm trong dự án.”

**B. Nếu hỏi sâu về dự án trong CV**

> “CV mẫu hiện ghi tên Banking Software nhưng chưa mô tả rõ phần đóng góp. Để mô phỏng buổi luyện tập, giả sử em phụ trách một API tra cứu tài khoản và lịch sử giao dịch bằng Spring Boot. Em sẽ tách controller/service/repository, validate request, xử lý lỗi rõ ràng và viết test cho các trường hợp hợp lệ lẫn dữ liệu thiếu. Đây là ví dụ test, không phải số liệu hay thành tích có sẵn trong CV.”

Nếu muốn câu trả lời sát hồ sơ thật hơn, thay đoạn giả lập trên bằng chức năng và phần việc bạn thực sự đã làm.

**C. Nếu hỏi OOP / Java collection**

> “Em dùng encapsulation để giữ trạng thái đối tượng qua access modifier và method, dùng interface để tách contract khỏi implementation. Với HashMap, thao tác tra cứu trung bình gần O(1), còn TreeMap giữ thứ tự theo key và thường có chi phí O(log n). Em sẽ chọn theo yêu cầu tra cứu hay cần thứ tự.”

**D. Nếu hỏi Spring Boot / REST**

> “Em thường để controller nhận request và trả response, service xử lý nghiệp vụ, repository làm việc với dữ liệu. Em validate DTO ở đầu vào, dùng status code phù hợp, và gom xử lý lỗi vào exception handler. Với thao tác ghi nhiều bảng, em đặt transaction ở service để các bước thành công hoặc rollback cùng nhau.”

**E. Nếu hỏi SQL / tính nhất quán**

> “Em sẽ tái hiện truy vấn chậm, xem execution plan, kiểm tra điều kiện lọc và index trước khi tối ưu. Với chuyển tiền, em cần transaction, kiểm tra số dư và ràng buộc dữ liệu để tránh ghi một nửa. Em cũng sẽ kiểm thử trường hợp hai request đồng thời, không chỉ test đường đi bình thường.”

**F. Nếu hỏi về Kafka / microservice (JD có yêu cầu nhưng CV chưa chứng minh kinh nghiệm)**

> “Em chưa triển khai Kafka trong production. Theo hiểu biết của em, Kafka phù hợp cho giao tiếp bất đồng bộ và event stream. Nếu dùng trong bài toán giao dịch, em cần nghĩ tới idempotency, retry, dead-letter và tính nhất quán giữa DB với message; em sẽ làm prototype nhỏ và kiểm thử lỗi trước khi khẳng định đã vận hành thực tế.”

**G. Nếu hỏi tình huống lỗi API chậm**

> “Em sẽ tái hiện bằng request cụ thể, xem log có correlation ID, đo thời gian ở từng tầng rồi kiểm tra truy vấn, số lần gọi dịch vụ và payload. Em ưu tiên xác định nguyên nhân trước khi thêm cache. Sau khi sửa, em thêm test hồi quy và so sánh latency trên cùng dữ liệu.”

**H. Nếu hỏi điểm chưa biết / tự đánh giá**

> “Phần đó em chưa có kinh nghiệm thực tế nên không muốn đoán. Em sẽ nêu giả định, tìm tài liệu hoặc hỏi người hướng dẫn, rồi kiểm tra bằng một ví dụ nhỏ. Mục tiêu của kỳ thực tập là em nhận feedback sớm và cải thiện theo từng vòng review.”

**I. Nếu hỏi ngược doanh nghiệp**

> “Trong 1–2 tháng đầu, thực tập sinh Java Backend thường được giao loại task nào? Team đánh giá tiến bộ qua code review, test hay mục tiêu nào?”

### Kiểm tra Laya / Orchestrator sau mỗi đáp án

1. Khi đang nói, thử tự sửa một ý mơ hồ (ví dụ: nói một phần về “Redis”, dừng ngắn rồi làm rõ cache hay queue). Laya có thể chọn `CLARIFY_NOW`/`ASK_REPEAT`; transcript đoạn đã nghe phải được giữ, orchestrator sinh một lời hỏi theo ngữ cảnh, không rubric và không chuyển sang câu mới.
2. Nói “để em suy nghĩ một chút” rồi dừng. Nếu Laya trả `WAIT_FOR_CANDIDATE`, mic phải tiếp tục mở, chưa gửi final transcript và không tự chuyển câu; có thể tiếp tục nói hoặc bấm **Chốt câu trả lời**.
3. Nếu cần, dùng câu trả lời nhiều đoạn: nói → dừng ngắn → nói tiếp. Sau khoảng VAD + grace window, transcript mới được chốt. Nút **Chốt câu trả lời** vẫn là lựa chọn chủ động; không phải nút bật micro.
4. Trong log kiểm tra `CANDIDATE_PAUSE_DETECTED`, `STREAM_CLARIFICATION_DECISION`, `STREAM_CLARIFICATION_DELIVERED`, `ASR_GATE`, `LIVE_ORCHESTRATION`, `QUESTION_ENGINE`. **Không được xuất hiện `RUBRIC_EVAL` ở giữa phiên.**
   Log **Latency theo các lượt** phải hiện P50/P95/max; theo dõi nhất là `ANSWER_TO_NEXT_QUESTION` và `VOICE_TURN_LATENCY` (thời gian từ lúc chốt đáp án tới âm thanh câu tiếp đầu tiên). P95 trên 8 giây được đánh dấu CHẬM.
5. Chờ câu hỏi tiếp theo. Orchestrator có thể hỏi follow-up, đổi độ khó hoặc chuyển stage dựa trên transcript đã xác nhận; câu hỏi mới không cần khớp câu mẫu trong script.
6. Sau khi kết thúc phiên, mới kiểm tra `FINAL_RUBRIC_COMPLETE`. Nếu Gemini/quota lỗi, báo cáo phải ở `PENDING_EVALUATION` và không hiển thị điểm 0/tạm; retry chỉ chạy khi bấm nút thử lại.

## 2. Kịch bản chuyển chuyên môn: AI Engineer Intern

Dùng kịch bản này để kiểm tra cơ chế CV khác framework và xác nhận có chủ ý:

1. Chuyên môn công việc: AI Engineer; cấp độ: Intern.
2. Chọn JD: itv_4024 · AI Engineer Intern.
3. Có thể chọn CV CV_AI_002 · Data Scientist / Machine Learning Engineer · 2 dự án.
4. CV này được ánh xạ sang IF_DS, còn JD trên ánh xạ sang IF_AI. Preview phải là AI Engineer / IF_AI, và giao diện phải yêu cầu xác nhận dùng CV khác chuyên môn. Tick Tôi muốn dùng CV này để luyện phỏng vấn chuyển chuyên môn trước khi bắt đầu.
5. Nếu hỏi về dự án, có thể trả lời theo dữ liệu CV: project handwriting recognition xử lý ảnh chữ viết tay thành text bằng object detection và tạo câu; bổ sung chính xác phần bạn muốn giả lập.
6. Nếu hỏi đánh giá mô hình, trả lời theo điều bạn biết: train/validation split, precision/recall/F1, confusion matrix, overfitting và cách so sánh với baseline. Đừng tự nhận đã triển khai production nếu chưa làm.

Kỳ vọng: framework/rubric và câu hỏi theo JD AI; CV chỉ cung cấp bằng chứng/ngữ cảnh. Không được tự đổi framework về Data Scientist hoặc âm thầm thay CV.

## 3. Ca âm tính: không có JD phù hợp

1. Chọn chuyên môn Frontend Developer, cấp độ Intern.
2. Catalog hiện không có JD Frontend Intern đã ánh xạ framework.
3. Kỳ vọng: hiện 0 JD phù hợp, nút bắt đầu bị khóa, không tự đưa JD khác ngành vào dropdown. Đổi sang cấp độ có dữ liệu hoặc chọn một chuyên môn có JD; không “chọn đại” một job để lách kiểm tra.

## 4. Các ca fallback / lỗi

- **Silero chưa tải hoặc lỗi ONNX:** energy VAD local tự động phát hiện nói/dừng cho lượt hiện tại; không cần bấm Chốt câu trả lời. Silero được dùng ở lượt sau khi đã sẵn sàng. Kiểm tra GET `/models/silero_vad.onnx` trả 200 và log chế độ VAD.
- **Từ chối quyền micro:** dùng ô nhập chữ để test Orchestrator; bật quyền micro trong browser rồi thử lại.
- **Không có transcript cuối:** không gửi lại cùng đáp án nhiều lần; dùng nút chốt một lần hoặc trả lời bằng chữ.
- **Gemini lỗi/quota:** kiểm tra log lỗi sinh câu hỏi. Không kỳ vọng câu mẫu thay thế; khi có retry, bấm thử sinh lại một lần.
- **TTS lỗi:** vẫn kiểm tra được transcript/evaluation bằng chữ; không gửi lại đáp án chỉ vì âm thanh không phát.

## Luồng dữ liệu cần xác nhận

Mic → Silero hoặc energy VAD local + pause grace → Qwen3-ASR partial transcript → WebSocket partial_transcript → Laya streaming decision → (nếu cần) client checkpoint stream_segment → Gemini/orchestrator sinh lời hỏi làm rõ → VieNeu TTS → resume cùng answer.

Nếu final transcript chưa rõ: ASR Gate giữ answer draft → Gemini tạo lời hỏi lại đúng ngữ cảnh → VieNeu nói → mic tự nghe lần hai → hai bản chép lời khớp thì tự chốt, không cần nút xác nhận. Theo dõi `ASR_AUTO_REPROMPT`, `ASR_REPEAT_CONSENSUS`, `VOICE_ASR_TIMING`.

Khi ứng viên chốt: WebSocket final_transcript → ASR Gate → lưu committed answer → Laya chọn câu tiếp mà không chấm rubric. Kết thúc session: Evidence Evaluator chấm các answer đã lưu → Report Service. Bài test này không dùng nút dev gửi transcript mẫu; test E2E tự động dùng model/provider doubles để không tiêu quota.
