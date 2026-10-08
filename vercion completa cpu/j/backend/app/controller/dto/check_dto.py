from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FieldDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: Optional[str] = Field(None, description="Valor extraído")
    confidence: float = Field(0.0, ge=0, le=1, description="Confianza 0..1")
    bbox: Optional[list[float]] = Field(None, description="Caja normalizada [x0, y0, x1, y1]")
    source: str = Field("ocr", description="Origen: ocr, micr, trocr, vlm, imagen, calculado, manual")
    writing: Optional[str] = Field(None, description="Tipo de escritura estimado: impreso / manuscrito")


class CheckDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    status: str
    processed_at: str
    processing_ms: int
    overall_confidence: float
    amount_words_value: Optional[Decimal] = None
    amount_match: Optional[bool] = None
    observations: list[str] = []
    fields: dict[str, FieldDTO] = {}
    edited: bool = False
    deleted: bool = False
    image_url: str = ""


class CheckDetailDTO(CheckDTO):
    raw_text: str = ""
    file_path: str = ""
    error: Optional[str] = None


class CheckPageDTO(BaseModel):
    items: list[CheckDTO]
    total: int
    page: int
    page_size: int
    total_pages: int


class CheckFieldsPatchDTO(BaseModel):
    """Corrección manual de campos: solo se envían los que cambian."""

    banco: Optional[str] = Field(None, max_length=120)
    numero_cheque: Optional[str] = Field(None, max_length=30, pattern=r"^[0-9\- ]*$")
    ciudad: Optional[str] = Field(None, max_length=60)
    fecha: Optional[str] = Field(None, max_length=40, description="YYYY-MM-DD o DD/MM/YYYY")
    beneficiario: Optional[str] = Field(None, max_length=200)
    monto: Optional[str] = Field(None, max_length=30, pattern=r"^[0-9.,\s$]*$")
    monto_letras: Optional[str] = Field(None, max_length=300)
    moneda: Optional[str] = Field(None, max_length=10)
    cuenta: Optional[str] = Field(None, max_length=40)
    concepto: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern=r"^(COMPLETO|REVISAR)$")


class SummaryDTO(BaseModel):
    total: int
    completos: int
    revisar: int
    errores: int
    total_amount: Decimal
    average_confidence: float
    watching: bool
    input_dir: str
    queue_size: int
    current_file: Optional[str]
    last_scan: Optional[str]
    version: int
    engine_ready: bool
    handwriting_model: bool
    vlm_model: Optional[str]


class ScanRequestDTO(BaseModel):
    request_id: Optional[str] = Field(None, max_length=64, description="Identificador para idempotencia")


class ScanResultDTO(BaseModel):
    enqueued: int
    queue_size: int


class ReprocessResultDTO(BaseModel):
    check_id: int
    enqueued: bool


class ErrorDTO(BaseModel):
    status: int
    error: str
    message: str
