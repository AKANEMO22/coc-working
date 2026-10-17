"""
CÓC ĐI LÀM — FastAPI Main Application
Khởi tạo ứng dụng FastAPI, CORS, WebSocket và REST API routes.
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
import time
import uuid

from app.shared.config import get_settings
from app.domains.candidate import api as cv
from app.domains.interview.api import sessions, questions
from app.domains.speech import api as tts
from app.domains.interview.websocket import router as ws_router
from app.shared.observability.traffic import (
    clear_traffic_events,
    get_traffic_events,
    record_traffic_event,
)

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _route_template_for_request(app: FastAPI, method: str, request_path: str) -> str:
    """Resolve a full mounted route path without retaining dynamic ID values."""
    actual_parts = request_path.strip("/").split("/") if request_path.strip("/") else []
    for template, operations in app.openapi().get("paths", {}).items():
        if method.lower() not in operations:
            continue
        template_parts = template.strip("/").split("/") if template.strip("/") else []
        if len(template_parts) != len(actual_parts):
            continue
        matches = all(
            part.startswith("{") and part.endswith("}") or part == actual
            for part, actual in zip(template_parts, actual_parts)
        )
        if matches:
            return template
    return "<unmatched route>"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời ứng dụng: startup/shutdown."""
    settings = get_settings()
    logger.info("=" * 60)
    logger.info("🐸 CÓC ĐI LÀM — Backend Server Starting")
    logger.info(f"   Environment: {settings.app_env}")
    decision_controller = (
        f"local Laya ({settings.laya_model_path}, device={settings.laya_device})"
        if settings.laya_enabled
        else "deterministic fallback (LAYA_ENABLED=false)"
    )
    logger.info("   Decision controller: %s", decision_controller)
    logger.info(f"   Policy Version: {settings.policy_version}")
    logger.info("=" * 60)

    # Khởi tạo services tại startup
    try:
        from app.shared.infrastructure.database import get_supabase_client
        get_supabase_client()
        logger.info("✅ Supabase client ready")
    except Exception as e:
        logger.warning(f"⚠️ Supabase not configured: {e}")

    try:
        from app.shared.infrastructure.redis import get_redis_client
        get_redis_client()
        logger.info("✅ Upstash Redis client ready")
    except Exception as e:
        logger.warning(f"⚠️ Redis not configured: {e}")

    if settings.laya_enabled:
        try:
            from app.domains.interview.services.laya_controller import get_laya_controller
            controller = await asyncio.to_thread(get_laya_controller)
            if await asyncio.to_thread(controller.load_model):
                logger.info("✅ Local Laya decision model ready (%s)", controller.model_version)
            else:
                logger.warning("⚠️ Laya model unavailable (%s); using deterministic fallback", controller.load_error or "disabled")
        except Exception as e:
            logger.warning(f"⚠️ Laya controller error, using deterministic fallback: {e}")
    else:
        logger.info("ℹ️ Laya disabled; interview decisions use the deterministic local fallback")

    speech_warmup_task = None
    if settings.preload_local_speech:
        async def warm_local_speech():
            for name, loader in (("VieNeu TTS", tts._get_vieneu_tts_model),
                                 ("Qwen3-ASR", tts._get_qwen_asr_model)):
                try:
                    await asyncio.to_thread(loader)
                    logger.info("✅ %s warmed before the candidate speaks", name)
                except Exception as exc:
                    logger.warning("⚠️ %s warmup failed: %s", name, type(exc).__name__)

        # Let HTTP health return while models warm in the background. The model
        # loaders own locks, so an early request safely waits for the same load.
        speech_warmup_task = asyncio.create_task(warm_local_speech())

    yield

    # Shutdown
    if speech_warmup_task and not speech_warmup_task.done():
        speech_warmup_task.cancel()
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
    # Traffic inspection is enabled only by the local development launchers (or
    # an explicit APP_ENV=development / APP_DEBUG=true configuration).
    app.state.debug_traffic_enabled = settings.app_env == "development" and settings.app_debug

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def capture_http_traffic(request: Request, call_next):
        if (
            not request.app.state.debug_traffic_enabled
            or request.url.path.startswith("/api/v1/debug/")
        ):
            return await call_next(request)

        trace_id = request.headers.get("x-trace-id", "")[:64] or uuid.uuid4().hex[:12]
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            path = _route_template_for_request(request.app, request.method, request.url.path)
            record_traffic_event(
                kind="http",
                direction="Browser → API",
                name=f"{request.method} {path}",
                method=request.method,
                path=path,
                status_code=500,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                trace_id=trace_id,
                error=type(exc).__name__,
            )
            raise

        # Prefer the route template (e.g. /sessions/{session_id}) over the
        # concrete URL so IDs are not copied into the debug trace.
        path = _route_template_for_request(request.app, request.method, request.url.path)
        response.headers["X-Trace-Id"] = trace_id
        record_traffic_event(
            kind="http",
            direction="Browser → API",
            name=f"{request.method} {path}",
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            trace_id=trace_id,
        )
        return response

    # REST API routes
    app.include_router(cv.router, prefix="/api/v1/cv", tags=["CV & JD Lab"])
    app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Interview Sessions"])
    app.include_router(questions.router, prefix="/api/v1/questions", tags=["Question Bank"])
    app.include_router(tts.router, prefix="/api/v1/tts", tags=["Local VieNeu TTS"])
    app.include_router(tts.stt_router, prefix="/api/v1/stt", tags=["Local Qwen3-ASR STT"])

    # WebSocket route
    app.include_router(ws_router, tags=["Interview WebSocket"])

    @app.get("/health", tags=["System"])
    @app.get("/api/v1/health", tags=["System"])
    async def health_check():
        from app.domains.interview.services.laya_controller import get_laya_controller
        laya = get_laya_controller()
        return {
            "status": "healthy",
            "service": "coc-di-lam-backend",
            "version": "1.0.0",
            "auth_profile": settings.auth_profile,
            "controller": "laya-local" if laya.is_available else "local-deterministic-fallback",
            "decision_mode": "laya_local" if laya.is_available else "local_deterministic_fallback",
            "laya_model_loaded": laya.is_available,
            "laya_model": laya.model_name if laya.is_available else None,
            "laya_model_revision": laya.model_revision if laya.is_available else None,
            "laya_device": laya.device if laya.is_available else None,
            "laya_backend": getattr(getattr(laya.client, "agent", None), "backend", None) if laya.is_available else None,
            "tts_model": settings.vieneu_model_id,
            "tts_device": settings.vieneu_device,
            "stt_model": settings.stt_model_id,
            "stt_device": settings.stt_device,
            "stt_model_loaded": tts._QWEN_MODEL is not None,
            "tts_model_loaded": tts._VIENEU_MODEL is not None,
            "question_model": settings.gemini_flash_model,
        }

    def require_local_debug_access(request: Request) -> None:
        client_host = request.client.host if request.client else ""
        if (
            not request.app.state.debug_traffic_enabled
            or client_host not in {"127.0.0.1", "::1", "testclient"}
        ):
            # Do not disclose the existence of debug routes outside local dev.
            raise HTTPException(status_code=404, detail="Not found")

    @app.get("/api/v1/debug/traffic", tags=["Development Debug"])
    async def debug_traffic(request: Request, limit: int = Query(default=100, ge=1, le=500)):
        require_local_debug_access(request)
        return {"enabled": True, "events": get_traffic_events(limit)}

    @app.delete("/api/v1/debug/traffic", tags=["Development Debug"])
    async def clear_debug_traffic(request: Request):
        require_local_debug_access(request)
        return {"cleared": clear_traffic_events()}

    @app.get("/api/v1/debug/routes", tags=["Development Debug"])
    async def debug_routes(request: Request):
        require_local_debug_access(request)
        routes = []
        # FastAPI can keep included routers lazy, so use its resolved OpenAPI
        # paths for HTTP endpoints instead of relying only on app.routes.
        for path, operations in request.app.openapi().get("paths", {}).items():
            if path.startswith("/api/"):
                for method, operation in operations.items():
                    if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                        routes.append({
                            "path": path,
                            "methods": [method.upper()],
                            "name": operation.get("operationId", ""),
                        })

        # WebSockets are not represented in OpenAPI.
        for route in ws_router.routes:
            path = getattr(route, "path", "")
            if path.startswith("/ws/"):
                routes.append({
                    "path": path,
                    "methods": ["WS"],
                    "name": getattr(route, "name", ""),
                })
        return {"enabled": True, "routes": routes}

    return app


app = create_app()
