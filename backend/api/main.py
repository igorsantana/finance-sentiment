"""FastAPI entry point: wires routes, DB init, and the scheduler lifespan."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import dates, files, health, news, runs
from .scheduler import start_scheduler, stop_scheduler

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = FastAPI(
        title="Finance News API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(dates.router, prefix="/api", tags=["dates"])
    app.include_router(news.router, prefix="/api", tags=["news"])
    app.include_router(files.router, prefix="/api", tags=["files"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    return app


app = create_app()
