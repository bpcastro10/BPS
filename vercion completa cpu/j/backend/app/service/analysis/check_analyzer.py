"""Orquesta el análisis completo de un cheque: imagen -> OCR -> campos -> validación -> registro."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config.settings import Settings
from app.enums import CheckStatus, FieldKey, FieldSource, WritingType
from app.model import CheckRecord, ExtractedField
from app.service.analysis.amount_words import WordsAmount, parse_amount_words
from app.service.analysis.field_extractor import ExtractionResult, FieldExtractor
from app.service.analysis.handwriting_recognizer import HandwritingRecognizer
from app.service.analysis.image_loader import crop_check, crop_norm, load_pages, normalize_size, rotate
from app.service.analysis.micr_reader import MicrResult, read_micr
from app.service.analysis.ocr_engine import Layout, OcrEngine, OcrToken, estimate_skew
from app.service.analysis.signature_detector import detect_signature
from app.service.analysis.text_utils import clean_value, find_amount, find_date, format_amount, normalize, parse_amount
from app.service.analysis.vlm_refiner import VlmRefiner
from app.service.analysis.writing_classifier import classify_writing

log = logging.getLogger(__name__)

REQUIRED = (FieldKey.MONTO, FieldKey.BENEFICIARIO, FieldKey.FECHA)
CONFIDENCE_FIELDS = (FieldKey.BANCO, FieldKey.NUMERO_CHEQUE, FieldKey.FECHA, FieldKey.BENEFICIARIO,
                     FieldKey.MONTO, FieldKey.MONTO_LETRAS)
WRITING_FIELDS = (FieldKey.BENEFICIARIO, FieldKey.MONTO, FieldKey.MONTO_LETRAS, FieldKey.FECHA, FieldKey.CIUDAD,
                  FieldKey.CONCEPTO, FieldKey.NUMERO_CHEQUE)
HANDWRITING_FIELDS = (FieldKey.BENEFICIARIO, FieldKey.MONTO_LETRAS, FieldKey.MONTO, FieldKey.FECHA, FieldKey.CONCEPTO)


class CheckAnalyzer:
    def __init__(self, settings: Settings, ocr: OcrEngine, handwriting: HandwritingRecognizer, vlm: VlmRefiner):
        self._settings = settings
        self._ocr = ocr
        self._handwriting = handwriting
        self._vlm = vlm
        self._extractor = FieldExtractor()

    def analyze_file(self, path: Path, file_hash: str) -> list[CheckRecord]:
        return [self.analyze_image(img, path, file_hash, page) for page, img in enumerate(load_pages(path), start=1)]

    def analyze_image(self, image: np.ndarray, path: Path, file_hash: str, page: int = 1) -> CheckRecord:
        started = time.perf_counter()
        img, tokens = self._prepare(image)
        layout = Layout(tokens)
        extraction = self._extractor.extract(layout)
        fields = extraction.fields

        micr = read_micr(img, self._ocr, tokens)
        self._merge_micr(fields, micr)

        signature = detect_signature(img, tokens)
        fields[FieldKey.FIRMA.value] = ExtractedField(
            value="Sí" if signature.present else "No", confidence=signature.confidence, bbox=signature.bbox,
            source=FieldSource.IMAGEN.value, writing=WritingType.MANUSCRITO.value if signature.present else None)

        for key in WRITING_FIELDS:
            f = fields.get(key.value)
            if f and f.present:
                f.writing = classify_writing(img, f.bbox, f.confidence)

        self._refine_handwriting(img, extraction)

        record = CheckRecord(file_name=path.name if page == 1 else f"{path.name} (pág. {page})",
                             file_path=str(path), page=page, file_hash=file_hash, fields=fields,
                             raw_text=layout.full_text() + (f"\n[MICR] {micr.raw}" if micr.raw else ""))
        self._finalize(record, extraction)

        if self._vlm.should_run(record.status != CheckStatus.COMPLETO.value or record.overall_confidence < self._settings.low_confidence):
            self._refine_with_vlm(img, record, extraction)

        record.preview_path = self._save_preview(img, file_hash, page)
        record.processed_at = datetime.now().isoformat(timespec="seconds")
        record.processing_ms = int((time.perf_counter() - started) * 1000)
        log.info("Cheque analizado: %s -> %s (%.0f%% conf, %d ms)", record.file_name, record.status,
                 record.overall_confidence * 100, record.processing_ms)
        return record

    # ------------------------------------------------------------------ preparación
    def _prepare(self, image: np.ndarray) -> tuple[np.ndarray, list[OcrToken]]:
        img = normalize_size(crop_check(image), self._settings.min_image_width, self._settings.max_image_width)
        tokens = self._ocr.read(img)
        skew = estimate_skew(tokens)
        if abs(skew) > 0.8:
            log.debug("Corrigiendo inclinación de %.2f°", skew)
            img = rotate(img, skew)
            tokens = self._ocr.read(img)
        if self._looks_upside_down(tokens):
            log.debug("Cheque invertido, rotando 180°")
            img = cv2.rotate(img, cv2.ROTATE_180)
            tokens = self._ocr.read(img)
        return img, tokens

    @staticmethod
    def _looks_upside_down(tokens: list[OcrToken]) -> bool:
        def micr_like(t: OcrToken) -> bool:
            compact = t.text.replace(" ", "")
            return len(compact) >= 8 and sum(c.isdigit() for c in compact) / len(compact) > 0.7

        top = [t for t in tokens if t.cy < 0.2 and micr_like(t)]
        bottom = [t for t in tokens if t.cy > 0.8 and micr_like(t)]
        return bool(top) and not bottom and sum(t.confidence for t in tokens) / max(len(tokens), 1) < 0.85

    # ------------------------------------------------------------------ MICR
    @staticmethod
    def _merge_micr(fields: dict[str, ExtractedField], micr: MicrResult) -> None:
        if micr.raw:
            fields[FieldKey.LINEA_MICR.value] = ExtractedField(value=micr.raw, confidence=round(micr.confidence, 3),
                                                               bbox=micr.bbox, source=FieldSource.MICR.value,
                                                               writing=WritingType.IMPRESO.value)
        if micr.routing:
            fields[FieldKey.CODIGO_RUTA.value] = ExtractedField(value=micr.routing, confidence=0.97, bbox=micr.bbox,
                                                                source=FieldSource.MICR.value)
        groups = {g.lstrip("0") for g in micr.groups}

        number = fields.get(FieldKey.NUMERO_CHEQUE.value, ExtractedField())
        if number.present and number.value.lstrip("0") in groups:
            number.confidence = max(number.confidence, 0.98)
        elif not number.present and micr.serial_candidates:
            fields[FieldKey.NUMERO_CHEQUE.value] = ExtractedField(value=micr.serial_candidates[0], confidence=0.6,
                                                                  bbox=micr.bbox, source=FieldSource.MICR.value)

        account = fields.get(FieldKey.CUENTA.value, ExtractedField())
        account_digits = "".join(c for c in (account.value or "") if c.isdigit()).lstrip("0")
        if account.present and account_digits and any(account_digits in g or g in account_digits for g in groups if len(g) >= 6):
            account.confidence = max(account.confidence, 0.98)
        elif not account.present and micr.account:
            fields[FieldKey.CUENTA.value] = ExtractedField(value=micr.account, confidence=0.75, bbox=micr.bbox,
                                                           source=FieldSource.MICR.value)

    # ------------------------------------------------------------------ manuscritos (TrOCR)
    def _refine_handwriting(self, img: np.ndarray, extraction: ExtractionResult) -> None:
        fields = extraction.fields
        pending = [k for k in HANDWRITING_FIELDS
                   if fields.get(k.value) and fields[k.value].bbox and fields[k.value].confidence < self._settings.low_confidence
                   and fields[k.value].writing == WritingType.MANUSCRITO.value]
        if not pending or not self._handwriting.available:
            return
        for key in pending:
            f = fields[key.value]
            result = self._handwriting.recognize(crop_norm(img, f.bbox, pad=0.006))
            if not result:
                continue
            text, conf = result
            if key == FieldKey.MONTO:
                parsed = find_amount(text)
                words_value = extraction.words_amount.value if extraction.words_amount else None
                if parsed and (conf > f.confidence or parsed[1] == words_value):
                    self._apply(f, str(parsed[1]), conf)
            elif key == FieldKey.MONTO_LETRAS:
                parsed_words = parse_amount_words(text)
                current = extraction.words_amount
                if parsed_words and conf > f.confidence and (current is None or parsed_words.recognized_ratio >= current.recognized_ratio):
                    self._apply(f, clean_value(text), conf)
                    extraction.words_amount = parsed_words
            elif key == FieldKey.FECHA:
                found = find_date(text)
                if found and conf > f.confidence:
                    self._apply(f, found[1].isoformat(), conf)
            elif conf > f.confidence:
                self._apply(f, clean_value(text), conf)

    @staticmethod
    def _apply(f: ExtractedField, value: str, conf: float) -> None:
        log.debug("Manuscrito refinado: '%s' -> '%s' (%.2f)", f.value, value, conf)
        f.value, f.confidence, f.source = value, round(conf, 3), FieldSource.MANUSCRITO_IA.value

    # ------------------------------------------------------------------ modelo de visión (Ollama)
    def _refine_with_vlm(self, img: np.ndarray, record: CheckRecord, extraction: ExtractionResult) -> None:
        data = self._vlm.extract(img)
        if not data:
            return
        for key, value in data.items():
            if not value:
                continue
            if key == "monto":
                amount = parse_amount(value)
                value = str(amount) if amount is not None else None
            elif key == "fecha":
                found = find_date(value)
                value = found[1].isoformat() if found else None
            if not value:
                continue
            f = record.fields.setdefault(key, ExtractedField())
            if f.present and normalize(f.value) == normalize(value):
                f.confidence = max(f.confidence, 0.95)
            elif not f.present or f.confidence < self._settings.low_confidence:
                f.value, f.confidence, f.source = value, 0.85, FieldSource.VLM.value
        words = record.fields.get(FieldKey.MONTO_LETRAS.value)
        if words and words.source == FieldSource.VLM.value:
            extraction.words_amount = parse_amount_words(words.value) or extraction.words_amount
        self._finalize(record, extraction)

    # ------------------------------------------------------------------ validación y estado
    def _finalize(self, record: CheckRecord, extraction: ExtractionResult) -> None:
        fields = record.fields
        observations: list[str] = []
        words: Optional[WordsAmount] = extraction.words_amount
        amount_field = fields.setdefault(FieldKey.MONTO.value, ExtractedField())
        words_field = fields.setdefault(FieldKey.MONTO_LETRAS.value, ExtractedField())
        numeric = parse_amount(amount_field.value) if amount_field.present else None

        match: Optional[bool] = None
        if numeric is None and words:
            amount_field.value, amount_field.confidence = str(words.value), round(0.75 * words.recognized_ratio, 3)
            amount_field.source = FieldSource.CALCULADO.value
            observations.append("Monto numérico no legible: se tomó del monto en letras.")
        elif numeric is not None and words:
            match = numeric == words.value
            if not match:
                alt = next((c for c in extraction.amount_candidates if c[2] == words.value), None)
                if alt:
                    amount_field.value, amount_field.bbox = str(alt[2]), alt[1].bbox
                    amount_field.confidence, match = round(alt[1].confidence, 3), True
            if match:
                amount_field.confidence = max(amount_field.confidence, 0.97)
                words_field.confidence = max(words_field.confidence, 0.95)
            else:
                observations.append(f"El monto en letras ({format_amount(words.value)}) no coincide con el numérico "
                                     f"({format_amount(numeric)}).")
        elif words_field.present and words is None:
            observations.append("No se pudo interpretar el monto en letras.")

        for key in REQUIRED:
            f = fields.get(key.value)
            if not f or not f.present:
                observations.append(f"No se detectó: {key.label}.")
            elif f.confidence < 0.6:
                observations.append(f"Baja confianza en {key.label} ({f.confidence:.0%}).")
        if fields.get(FieldKey.FIRMA.value, ExtractedField()).value != "Sí":
            observations.append("No se detectó firma.")

        confidences = []
        for key in CONFIDENCE_FIELDS:
            f = fields.get(key.value)
            if f and f.present:
                confidences.append(f.confidence)
            elif key in REQUIRED:
                confidences.append(0.0)
        record.overall_confidence = round(sum(confidences) / max(len(confidences), 1), 3)
        record.amount_words_value = words.value if words else None
        record.amount_match = match
        record.observations = observations
        record.status = CheckStatus.COMPLETO.value if not observations else CheckStatus.REVISAR.value

    # ------------------------------------------------------------------ vista previa
    def _save_preview(self, img: np.ndarray, file_hash: str, page: int) -> str:
        h, w = img.shape[:2]
        preview = cv2.resize(img, (1400, int(h * 1400 / w)), interpolation=cv2.INTER_AREA) if w > 1400 else img
        target = self._settings.previews_dir / f"{file_hash[:16]}_{page}.jpg"
        ok, buf = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            buf.tofile(str(target))
        return str(target)
