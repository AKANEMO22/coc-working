# Dữ liệu phỏng vấn trong project

```text
data/
  normalized/
    candidates_clean.json          Hồ sơ sinh viên/ứng viên và CV
    jobs_below_mid_clean.json       Job/JD
    interview_frameworks_clean.json Khung năng lực, giai đoạn và rubric
  audit-manifest.json               Size, số record và SHA-256 của bản copy
```

Ba file JSON được copy nguyên byte từ nguồn normalized, không đổi schema/nội dung.
Bản gốc vẫn giữ nguyên. Backend đọc mặc định thư mục này; Docker mount read-only.
Không còn cần thư mục Downloads gốc để chạy app.

`normalized/` được Git ignore vì có thể chứa thông tin cá nhân trong CV.
Khi chuyển máy/deploy, cần copy riêng thư mục này; không public dataset bằng Git.
Manifest chỉ chứa metadata kiểm tra, không có tên, email, điện thoại hay nội dung CV.

Audit hiện xác nhận tính toàn vẹn bản copy và JSON đọc được, **không phải** kết luận
về chất lượng CV/JD hoặc độ đúng của ánh xạ chuyên môn/framework.
