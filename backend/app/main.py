"""
CÓC ĐI LÀM — FastAPI Main Application
Khởi tạo ứng dụng FastAPI, CORS, WebSocket và REST API routes.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import get_settings
from app.api.v1 import cv, sessions, questions, tts
from app.websocket.interview_turn_ws import router as ws_router

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời ứng dụng: startup/shutdown."""
    settings = get_settings()
    logger.info("=" * 60)
    logger.info("🐸 CÓC ĐI LÀM — Backend Server Starting")
    logger.info(f"   Environment: {settings.app_env}")
    logger.info(f"   TypeSafe Jev Enabled: {settings.typesafe_enabled} (model={settings.typesafe_model})")
    logger.info(f"   Policy Version: {settings.policy_version}")
    logger.info("=" * 60)

    # Khởi tạo services tại startup
    try:
        from app.core.database import get_supabase_client
        get_supabase_client()
        logger.info("✅ Supabase client ready")
    except Exception as e:
        logger.warning(f"⚠️ Supabase not configured: {e}")

    try:
        from app.core.redis import get_redis_client
        get_redis_client()
        logger.info("✅ Upstash Redis client ready")
    except Exception as e:
        logger.warning(f"⚠️ Redis not configured: {e}")

    if settings.typesafe_enabled:
        try:
            from app.services.jev_controller import get_jev_controller
            controller = get_jev_controller()
            if controller.is_available:
                logger.info(f"✅ TypeSafe AI Jev Controller ready (model={settings.typesafe_model})")
            else:
                logger.warning("⚠️ TypeSafe AI Jev API key missing or disabled, using deterministic fallback")
        except Exception as e:
            logger.warning(f"⚠️ TypeSafe AI Jev controller error, using deterministic fallback: {e}")

    yield

    # Shutdown
    logger.info("🐸 CÓC ĐI LÀM — Backend Server Shutting Down")


def create_app() -> FastAPI:
    """Factory function tạo FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title="Cóc Đi Làm API",
        description="Backend API cho hệ thống phỏng vấn OJT thực chiến bằng giọng nói",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST API routes
    app.include_router(cv.router, prefix="/api/v1/cv", tags=["CV & JD Lab"])
    app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Interview Sessions"])
    app.include_router(questions.router, prefix="/api/v1/questions", tags=["Question Bank"])
    app.include_router(tts.router, prefix="/api/v1/tts", tags=["Neural TTS"])

    # WebSocket route
    app.include_router(ws_router, tags=["Interview WebSocket"])

    @app.get("/health", tags=["System"])
    @app.get("/api/v1/health", tags=["System"])
    async def health_check():
        from app.services.jev_controller import get_jev_controller
        jev = get_jev_controller()
        return {
            "status": "healthy",
            "service": "coc-di-lam-backend",
            "version": "1.0.0",
            "auth_profile": settings.auth_profile,
            "controller": "typesafe-jev",
            "typesafe_jev_ready": jev.is_available,
            "jev_model": settings.typesafe_model,
        }

    return app


app = create_app()
