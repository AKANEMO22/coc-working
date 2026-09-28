---
title: Coc Di Lam AI Backend
emoji: 🐸
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# 🐸 CÓC ĐI LÀM — AI Mock Interview & CV Lab Cloud Backend

Backend FastAPI tích hợp mô hình **TypeSafe AI Jev (Typed Decisions)** và **Google Gemini Evaluator** phục vụ hệ thống phỏng vấn thoại 1-1 thời gian thực và phòng lab tối ưu CV cho sinh viên Đại học FPT.

### Endpoints
- Swagger API Docs: `/docs`
- Health check: `/health`
- WebSocket Turn Manager: `/ws/interview/{session_id}`
- CV Lab: `/api/v1/cv/`
- Sessions & Blueprint: `/api/v1/sessions/`
- Questions Bank: `/api/v1/questions/`
