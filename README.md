# CÓC ĐI LÀM — Nền Tảng Phỏng Vấn OJT Thực Chiến 🐸

Hệ thống luyện phỏng vấn thực chiến chuyên sâu bằng giọng nói kết hợp kiểm toán CV & phân tích khoảng cách năng lực (JD Gap Analysis), được thiết kế chuyên biệt cho sinh viên Đại học FPT bước vào kỳ thực tập doanh nghiệp (OJT).

---

## 🏗️ Kiến Trúc Hệ Thống (End-to-End Production)

```
cóc working/
├── docs/
│   └── schemas/                          # 9 JSON Schema files chuẩn hóa hợp đồng dữ liệu
├── backend/                              # FastAPI Python 3.11+
│   ├── app/
│   │   ├── api/v1/                       # REST API (cv, sessions, questions)
│   │   ├── core/                         # config, database (Supabase), redis (Upstash + Fallback)
│   │   ├── models/                       # Pydantic schemas, DB models
│   │   ├── services/                     # Hard Policy, Laya Controller, Evidence Evaluator, CV Analyzer, etc.
│   │   └── websocket/                    # Interview Turn Manager WebSocket
│   └── requirements.txt
└── frontend/                             # Next.js 15 (App Router) + TypeScript + Tailwind CSS
    └── src/
        ├── app/                          # Home, CV Lab (Phân hệ 1), Interview Room (Phân hệ 2), Report
        ├── components/                   # AudioVisualizer, ControlBar, TranscriptBox, CVUploader, etc.
        ├── hooks/                        # useAudioRecorder, useInterviewSocket
        ├── lib/                          # EdgeRuntime, ModelCache (IndexedDB), TechnicalTermRecovery
        └── workers/                      # VAD Worker, Whisper STT Worker, Piper TTS Worker
```

---

## 🚀 Hướng Dẫn Khởi Chạy (Local Development)

### 1. Khởi động Backend (FastAPI)
```bash
cd backend
# Cài đặt thư viện
pip install -r requirements.txt

# Khởi chạy server
uvicorn app.main:app --reload --port 8000
```
- API Docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- WebSocket Endpoint: `ws://localhost:8000/ws/interview/{session_id}`

### 2. Khởi động Frontend (Next.js 15)
```bash
cd frontend
# Cài đặt node_modules
npm install

# Khởi chạy dev server
npm run dev
```
- Truy cập trình duyệt: `http://localhost:3000`

---

## 🔑 Cấu Hình Môi Trường (.env)
Xem file `.env.example` trong thư mục `backend/` và `frontend/`:
- `GOOGLE_GEMINI_API_KEY`: API key cho Gemini 2.0 Flash (Evaluator) và Pro.
- `SUPABASE_URL` & `SUPABASE_SERVICE_ROLE_KEY`: Kết nối cơ sở dữ liệu PostgreSQL.
- `UPSTASH_REDIS_URL` & `UPSTASH_REDIS_TOKEN`: Hot state cache (hệ thống có sẵn in-memory store fallback tự động).
