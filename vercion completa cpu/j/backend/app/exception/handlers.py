import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.controller.dto.check_dto import ErrorDTO
from app.exception.check_exceptions import CheckAppException

log = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CheckAppException)
    async def handle_app_exception(request: Request, exc: CheckAppException) -> JSONResponse:
        log.warning("%s %s -> %s", request.method, request.url.path, exc.message)
        body = ErrorDTO(status=exc.status_code, error=type(exc).__name__, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())
