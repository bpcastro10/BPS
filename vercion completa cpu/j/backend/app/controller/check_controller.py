import logging
import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import FileResponse

from app.controller.dto.check_dto import (
    CheckDetailDTO,
    CheckFieldsPatchDTO,
    CheckPageDTO,
    ErrorDTO,
    ReprocessResultDTO,
    ScanRequestDTO,
    ScanResultDTO,
    SummaryDTO,
)
from app.controller.mapper.check_mapper import CheckMapper
from app.exception import CheckNotFoundException
from app.repository.check_repository import CheckFilter
from app.service.check_service import CheckService
from app.service.excel_exporter import build_excel
from app.service.idempotency_store import IdempotencyStore

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Cheques"])
_ERRORS = {404: {"model": ErrorDTO}, 400: {"model": ErrorDTO}}


def get_service(request: Request) -> CheckService:
    return request.app.state.check_service


def get_idempotency(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency


def _filter(status_: Optional[str], search: Optional[str], date_from: Optional[str], date_to: Optional[str],
            include_deleted: bool, sort_by: str, order: str) -> CheckFilter:
    return CheckFilter(status=status_, search=search, date_from=date_from, date_to=date_to,
                       include_deleted=include_deleted, sort_by=sort_by, order=order)


@router.get("/checks", response_model=CheckPageDTO, summary="Listar cheques analizados",
            description="Lista paginada con filtros por estado, texto libre y rango de fechas; permite ordenar.")
def list_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500, alias="pageSize"),
    status_: Optional[Literal["COMPLETO", "REVISAR", "ERROR"]] = Query(None, alias="status"),
    search: Optional[str] = Query(None, max_length=100, description="Busca en beneficiario, banco, n° y archivo"),
    date_from: Optional[str] = Query(None, alias="dateFrom", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, alias="dateTo", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    include_deleted: bool = Query(False, alias="includeDeleted"),
    sort_by: Literal["processedAt", "fileName", "amount", "date", "payee", "bank", "checkNumber", "status",
                     "confidence"] = Query("processedAt", alias="sortBy"),
    order: Literal["asc", "desc"] = Query("desc"),
    service: CheckService = Depends(get_service),
) -> CheckPageDTO:
    flt = _filter(status_, search, date_from, date_to, include_deleted, sort_by, order)
    records, total = service.find_all(flt, page, page_size)
    return CheckPageDTO(items=[CheckMapper.to_dto(r) for r in records], total=total, page=page,
                        page_size=page_size, total_pages=max(math.ceil(total / page_size), 1))


@router.get("/checks/{check_id}", response_model=CheckDetailDTO, responses=_ERRORS, summary="Detalle de un cheque")
def get_check(check_id: int, service: CheckService = Depends(get_service)) -> CheckDetailDTO:
    return CheckMapper.to_detail_dto(service.find_by_id(check_id))


@router.get("/checks/{check_id}/image", response_class=FileResponse, responses=_ERRORS,
            summary="Imagen procesada del cheque")
def get_check_image(check_id: int, service: CheckService = Depends(get_service)) -> FileResponse:
    record = service.find_by_id(check_id)
    if not record.preview_path or not Path(record.preview_path).exists():
        raise CheckNotFoundException(check_id)
    return FileResponse(record.preview_path, media_type="image/jpeg")


@router.patch("/checks/{check_id}", response_model=CheckDetailDTO, responses=_ERRORS,
              summary="Corregir campos manualmente", description="Solo se actualizan los campos enviados.")
def patch_check(check_id: int, body: CheckFieldsPatchDTO, service: CheckService = Depends(get_service)) -> CheckDetailDTO:
    changes = body.model_dump(exclude_unset=True, exclude={"status"})
    return CheckMapper.to_detail_dto(service.update_fields(check_id, changes, body.status))


@router.delete("/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS,
               summary="Eliminar (borrado lógico)", description="Consultable luego con includeDeleted=true.")
def delete_check(check_id: int, service: CheckService = Depends(get_service)) -> Response:
    service.delete(check_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/checks/{check_id}/reprocessings", response_model=ReprocessResultDTO, status_code=202,
             responses=_ERRORS, summary="Volver a analizar un cheque")
def reprocess_check(check_id: int, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                    service: CheckService = Depends(get_service),
                    store: IdempotencyStore = Depends(get_idempotency)) -> ReprocessResultDTO:
    key = f"reprocess:{check_id}:{idempotency_key}" if idempotency_key else None
    return store.run_once(key, lambda: ReprocessResultDTO(check_id=check_id, enqueued=service.reprocess(check_id)))


@router.post("/scans", response_model=ScanResultDTO, status_code=202, summary="Escanear la carpeta ahora",
             description="Busca archivos nuevos en la carpeta de entrada. Idempotente por requestId / Idempotency-Key.")
def create_scan(request: Request, body: ScanRequestDTO = ScanRequestDTO(),
                idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                store: IdempotencyStore = Depends(get_idempotency)) -> ScanResultDTO:
    processing = request.app.state.processing
    key = body.request_id or idempotency_key

    def run() -> ScanResultDTO:
        enqueued = processing.scan() + processing.scan()
        return ScanResultDTO(enqueued=enqueued, queue_size=processing.status().queue_size)

    return store.run_once(f"scan:{key}" if key else None, run)


@router.get("/summary", response_model=SummaryDTO, summary="Resumen y estado del procesamiento")
def get_summary(request: Request) -> SummaryDTO:
    state = request.app.state
    totals = state.repository.summary()
    proc = state.processing.status()
    return SummaryDTO(
        total=totals["total"] or 0, completos=totals["completos"] or 0, revisar=totals["revisar"] or 0,
        errores=totals["errores"] or 0, total_amount=Decimal(totals["total_cents"] or 0) / Decimal(100),
        average_confidence=round(totals["avg_conf"] or 0, 3), watching=proc.watching, input_dir=proc.input_dir,
        queue_size=proc.queue_size, current_file=proc.current_file, last_scan=proc.last_scan,
        version=proc.version, engine_ready=proc.engine_ready,
        handwriting_model=state.handwriting.available,
        vlm_model=state.settings.ollama_model or None,
    )


@router.get("/exports/excel", response_class=Response, summary="Descargar Excel de cheques analizados",
            responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def export_excel(
    status_: Optional[Literal["COMPLETO", "REVISAR", "ERROR"]] = Query(None, alias="status"),
    search: Optional[str] = Query(None, max_length=100),
    date_from: Optional[str] = Query(None, alias="dateFrom"),
    date_to: Optional[str] = Query(None, alias="dateTo"),
    sort_by: str = Query("processedAt", alias="sortBy"),
    order: Literal["asc", "desc"] = Query("asc"),
    service: CheckService = Depends(get_service),
) -> Response:
    records, _ = service.find_all(_filter(status_, search, date_from, date_to, False, sort_by, order), 1, 0)
    content = build_excel(records)
    name = f"cheques_analizados_{datetime.now():%Y%m%d_%H%M}.xlsx"
    log.info("Exportando %d cheques a Excel", len(records))
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
