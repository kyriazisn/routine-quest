import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.routers import auth, device, parent


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(
        title="Routine Quest API",
        version="0.1.0",
        docs_url="/docs" if s.env != "prod" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.env != "prod" else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.public_app_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(auth.router)
    app.include_router(parent.router)
    app.include_router(device.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
        return {"status": "ok"}

    return app


app = create_app()
