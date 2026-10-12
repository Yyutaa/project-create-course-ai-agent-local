from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.config_routes import router as config_router
from app.api.course_routes import router as course_router
from app.api.fact_routes import router as fact_router
from app.api.run_routes import artifact_router, router as run_router
from app.api.system_routes import router as system_router
from app.catalog import EXAMPLE_COURSE_ROOT


app = FastAPI(title="AI Course Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5176", "http://127.0.0.1:5176"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOCAL_ORIGINS = {"http://localhost:5176", "http://127.0.0.1:5176"}
LOCAL_HOSTS = {"localhost:5176", "127.0.0.1:5176", "localhost:8002", "127.0.0.1:8002"}


@app.exception_handler(RequestValidationError)
async def redact_v0_validation(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/v0/"):
        details = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse({"detail": details}, status_code=422)
    return await request_validation_exception_handler(request, error)


@app.middleware("http")
async def local_write_guard(request: Request, call_next):
    if request.url.path.startswith("/api/v0/") and request.method in {
        "POST", "PUT", "PATCH", "DELETE"
    }:
        if (request.headers.get("host") not in LOCAL_HOSTS
                or request.headers.get("origin") not in LOCAL_ORIGINS):
            return JSONResponse({"detail": "本机页面来源验证失败"}, status_code=403)
        if (request.url.path == "/api/v0/llm-config" and request.method == "PUT"
                and request.headers.get("content-type", "").split(";", 1)[0].lower()
                != "application/json"):
            return JSONResponse({"detail": "配置写入仅接受 JSON"}, status_code=415)
    return await call_next(request)


app.include_router(system_router)
app.include_router(course_router)
app.include_router(fact_router)
app.include_router(config_router)
app.include_router(run_router)
app.include_router(artifact_router)
if EXAMPLE_COURSE_ROOT.is_dir():
    app.mount(
        "/course-example",
        StaticFiles(directory=EXAMPLE_COURSE_ROOT, html=True),
        name="course-example",
    )


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8002, reload=False)
