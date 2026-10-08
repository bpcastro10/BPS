import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config.cors_config import configure_cors
from app.config.logging_config import configure_logging
from app.config.settings import get_settings
from app.controller.check_controller import router as check_router
from app.exception.handlers import register_exception_handlers
from app.repository.check_repository import CheckRepository
from app.service.analysis.check_analyzer import CheckAnalyzer
from app.service.analysis.handwriting_recognizer import HandwritingRecognizer
from app.service.analysis.ocr_engine import OcrEngine
from app.service.analysis.vlm_refiner import VlmRefiner
from app.service.check_service import CheckService
from app.service.idempotency_store import IdempotencyStore
from app.service.processing_service import ProcessingService

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    repository = CheckRepository(settings.db_path)
    ocr = OcrEngine()
    handwriting = HandwritingRecognizer(settings.handwriting_model, settings.handwriting_enabled)
    analyzer = CheckAnalyzer(settings, ocr, handwriting,
                             VlmRefiner(settings.ollama_url, settings.ollama_model, settings.vlm_mode))
    processing = ProcessingService(settings, repository, analyzer, ocr)

    app.state.settings = settings
    app.state.handwriting = handwriting
    app.state.repository = repository
    app.state.processing = processing
    app.state.check_service = CheckService(repository, processing)
    app.state.idempotency = IdempotencyStore()

    processing.start()
    handwriting.preload_async()
    log.info("Aplicación lista en http://%s:%s", settings.host, settings.port)
    yield
    processing.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="API de Análisis de Cheques",
        version="1.0.0",
        description="Extrae datos impresos y manuscritos de cheques de forma 100% local.",
        lifespan=lifespan,
    )
    configure_cors(app, settings)
    register_exception_handlers(app)
    app.include_router(check_router)
    if settings.frontend_dir.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
