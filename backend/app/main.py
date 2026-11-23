from contextlib import aclosing, asynccontextmanager
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.concurrency import run_in_threadpool

from backend.app.api.routers.dashboard import router as dashboard_router
from backend.app.api.routers.auth import router as auth_router
from backend.app.api.routers.copilot import router as copilot_router

from backend.app.api.routers.delivery_expectations import router as delivery_expectations_router
from backend.app.api.routers.integrations import router as integrations_router
from backend.app.api.routers.reconciliation import router as reconciliation_router
from backend.app.database import dispose_engine
from backend.app.monitoring import api_metrics, dependencies
from backend.app.realtime import DashboardSignal
from backend.app.telemetry import RequestTelemetry, configure_logging
from backend.app.security import COOKIE, identity, protected_by_default, viewer


if logging.getLogger("uvicorn").handlers:
    configure_logging("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dashboard_signal = DashboardSignal()
    try:
        yield
    finally:
        await app.state.dashboard_signal.close()
        dispose_engine()


app = FastAPI(title="OpsBridge API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(protected_by_default)])
app.add_middleware(RequestTelemetry)
app.include_router(auth_router)
for router in (integrations_router, delivery_expectations_router, dashboard_router, copilot_router, reconciliation_router):
    app.include_router(router, dependencies=[Depends(viewer)])


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, exception):
    errors = [{"loc": error["loc"], "type": error["type"], "msg": "Invalid request field."}
              for error in exception.errors()]
    return JSONResponse({"detail": errors}, status_code=422)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "opsbridge-api"}


@app.get("/ready")
def readiness():
    states = dependencies()
    ready = states["database"] == states["schema"] == "ready" and states["broker"] != "unavailable"
    return JSONResponse({"status": "ready" if ready else "unavailable", "dependencies": states},
                        status_code=200 if ready else 503)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(api_metrics(), headers={"Content-Type": CONTENT_TYPE_LATEST})


@app.get("/dashboard/stream")
async def dashboard_stream(request: Request, _principal=Depends(viewer)):
    async def guarded():
        from time import monotonic

        check_at = monotonic() + 10
        async with aclosing(app.state.dashboard_signal.stream()) as stream:
            async for message in stream:
                if monotonic() >= check_at:
                    if await run_in_threadpool(identity, request.cookies.get(COOKIE)) is None:
                        yield "event: session-expired\ndata: {}\n\n"
                        return
                    check_at = monotonic() + 10
                yield message

    return StreamingResponse(guarded(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
