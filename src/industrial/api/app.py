"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI
from industrial.api.routes import router
from industrial.infrastructure.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Industrial Equipment Data Analysis Platform",
        description="工业设备数据分析平台 - Clean Architecture (TOGAF)",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(router)

    @app.on_event("startup")
    def _startup():
        init_db()

    @app.get("/", include_in_schema=False)
    def root():
        return {"service": "industrial-analytics", "docs": "/docs"}

    return app


app = create_app()
