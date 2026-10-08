from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Optional

from app.enums import CheckStatus, FieldKey, FieldSource


@dataclass
class ExtractedField:
    value: Optional[str] = None
    confidence: float = 0.0
    bbox: Optional[list[float]] = None
    source: str = FieldSource.OCR.value
    writing: Optional[str] = None

    @property
    def present(self) -> bool:
        return bool(self.value and str(self.value).strip())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedField":
        return cls(**{k: data.get(k) for k in ("value", "confidence", "bbox", "source", "writing")})


@dataclass(eq=False)
class CheckRecord:
    id: Optional[int] = None
    file_name: str = ""
    file_path: str = ""
    page: int = 1
    file_hash: str = ""
    status: str = CheckStatus.REVISAR.value
    processed_at: str = ""
    processing_ms: int = 0
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    amount_words_value: Optional[Decimal] = None
    amount_match: Optional[bool] = None
    overall_confidence: float = 0.0
    observations: list[str] = field(default_factory=list)
    raw_text: str = ""
    preview_path: str = ""
    error: Optional[str] = None
    edited: bool = False
    deleted: bool = False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CheckRecord) and self.id is not None and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def get(self, key: FieldKey) -> ExtractedField:
        return self.fields.get(key.value) or ExtractedField()

    def value(self, key: FieldKey) -> Optional[str]:
        return self.get(key).value

    @property
    def amount(self) -> Optional[Decimal]:
        raw = self.value(FieldKey.MONTO)
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None
