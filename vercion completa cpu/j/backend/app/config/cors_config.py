from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import Settings


def configure_cors(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
