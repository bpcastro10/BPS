"""Casos de uso sobre los cheques analizados: consulta, corrección manual, borrado lógico y reproceso."""
from __future__ import annotations

import logging
from typing import Optional

from app.enums import CheckStatus, FieldKey, FieldSource
from app.exception import CheckNotFoundException, InvalidFieldException
from app.model import CheckRecord, ExtractedField
from app.repository.check_repository import CheckFilter, CheckRepository
from app.service.analysis.amount_words import parse_amount_words
from app.service.analysis.text_utils import find_date, parse_amount
from app.service.processing_service import ProcessingService

log = logging.getLogger(__name__)


class CheckService:
    def __init__(self, repository: CheckRepository, processing: ProcessingService):
        self._repo = repository
        self._processing = processing

    def find_all(self, flt: CheckFilter, page: int, page_size: int) -> tuple[list[CheckRecord], int]:
        return self._repo.find_all(flt, page, page_size)

    def find_by_id(self, check_id: int) -> CheckRecord:
        record = self._repo.find_by_id(check_id)
        if record is None:
            raise CheckNotFoundException(check_id)
        return record

    def update_fields(self, check_id: int, changes: dict[str, Optional[str]], status: Optional[str]) -> CheckRecord:
        record = self.find_by_id(check_id)
        for key, value in changes.items():
            value = self._validate(key, value)
            current = record.fields.get(key, ExtractedField())
            record.fields[key] = ExtractedField(value=value, confidence=1.0, bbox=current.bbox,
                                                source=FieldSource.MANUAL.value, writing=current.writing)
        if FieldKey.MONTO_LETRAS.value in changes or FieldKey.MONTO.value in changes:
            words = parse_amount_words(record.value(FieldKey.MONTO_LETRAS) or "")
            record.amount_words_value = words.value if words else None
            record.amount_match = (record.amount == words.value) if (words and record.amount is not None) else None
        record.status = status or CheckStatus.COMPLETO.value
        record.edited = True
        if record.status == CheckStatus.COMPLETO.value:
            record.observations = [o for o in record.observations if o.startswith("Corregido")] + ["Corregido manualmente."]
        self._repo.save(record)
        self._processing.mark_changed()
        log.info("Cheque %s corregido manualmente: %s", check_id, ", ".join(changes))
        return record

    def delete(self, check_id: int) -> None:
        record = self.find_by_id(check_id)
        record.deleted = True
        self._repo.save(record)
        self._processing.mark_changed()
        log.info("Cheque %s marcado como eliminado", check_id)

    def reprocess(self, check_id: int) -> bool:
        return self._processing.reprocess(self.find_by_id(check_id))

    @staticmethod
    def _validate(key: str, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        value = str(value).strip()
        if key == FieldKey.MONTO.value:
            amount = parse_amount(value)
            if amount is None:
                raise InvalidFieldException(key, value)
            return str(amount)
        if key == FieldKey.FECHA.value:
            found = find_date(value)
            if not found:
                raise InvalidFieldException(key, value)
            return found[1].isoformat()
        return value
