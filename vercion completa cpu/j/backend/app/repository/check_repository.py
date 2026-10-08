"""Persistencia local en SQLite. Guarda los resultados y la huella (hash) de cada archivo procesado."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.enums import FieldKey
from app.model import CheckRecord, ExtractedField

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name          TEXT NOT NULL,
    file_path          TEXT NOT NULL,
    page               INTEGER NOT NULL DEFAULT 1,
    file_hash          TEXT NOT NULL,
    status             TEXT NOT NULL,
    processed_at       TEXT NOT NULL,
    processing_ms      INTEGER NOT NULL DEFAULT 0,
    bank               TEXT,
    check_number       TEXT,
    check_date         TEXT,
    payee              TEXT,
    amount_cents       INTEGER,
    amount_words_value TEXT,
    amount_match       INTEGER,
    overall_confidence REAL NOT NULL DEFAULT 0,
    fields_json        TEXT NOT NULL,
    observations_json  TEXT NOT NULL,
    raw_text           TEXT,
    preview_path       TEXT,
    error              TEXT,
    edited             INTEGER NOT NULL DEFAULT 0,
    deleted            INTEGER NOT NULL DEFAULT 0,
    UNIQUE (file_hash, page)
);
CREATE INDEX IF NOT EXISTS idx_checks_status ON checks(status);
CREATE INDEX IF NOT EXISTS idx_checks_hash ON checks(file_hash);
"""

SORTABLE_COLUMNS = {
    "processedAt": "processed_at",
    "fileName": "file_name",
    "amount": "amount_cents",
    "date": "check_date",
    "payee": "payee",
    "bank": "bank",
    "checkNumber": "check_number",
    "status": "status",
    "confidence": "overall_confidence",
}


@dataclass
class CheckFilter:
    status: Optional[str] = None
    search: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    include_deleted: bool = False
    sort_by: str = "processedAt"
    order: str = "desc"


class CheckRepository:
    def __init__(self, db_path: Path):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def exists_by_hash(self, file_hash: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM checks WHERE file_hash = ? LIMIT 1", (file_hash,)).fetchone()
        return row is not None

    def save(self, record: CheckRecord) -> CheckRecord:
        values = self._to_row(record)
        with self._lock:
            if record.id is None:
                existing = self._conn.execute(
                    "SELECT id FROM checks WHERE file_hash = ? AND page = ?", (record.file_hash, record.page)
                ).fetchone()
                record.id = existing["id"] if existing else None
            if record.id is None:
                columns = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                cursor = self._conn.execute(f"INSERT INTO checks ({columns}) VALUES ({placeholders})", tuple(values.values()))
                record.id = cursor.lastrowid
            else:
                assignments = ", ".join(f"{col} = ?" for col in values)
                self._conn.execute(f"UPDATE checks SET {assignments} WHERE id = ?", (*values.values(), record.id))
            self._conn.commit()
        return record

    def find_by_id(self, check_id: int) -> Optional[CheckRecord]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
        return self._from_row(row) if row else None

    def find_all(self, flt: CheckFilter, page: int = 1, page_size: int = 0) -> tuple[list[CheckRecord], int]:
        where, params = self._where(flt)
        column = SORTABLE_COLUMNS.get(flt.sort_by, "processed_at")
        direction = "ASC" if flt.order.lower() == "asc" else "DESC"
        sql = f"SELECT * FROM checks {where} ORDER BY {column} IS NULL, {column} {direction}, id {direction}"
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) FROM checks {where}", params).fetchone()[0]
            if page_size > 0:
                sql += " LIMIT ? OFFSET ?"
                rows = self._conn.execute(sql, (*params, page_size, (page - 1) * page_size)).fetchall()
            else:
                rows = self._conn.execute(sql, params).fetchall()
        return [self._from_row(r) for r in rows], total

    def summary(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) total,
                          SUM(CASE WHEN status='COMPLETO' THEN 1 ELSE 0 END) completos,
                          SUM(CASE WHEN status='REVISAR' THEN 1 ELSE 0 END) revisar,
                          SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) errores,
                          COALESCE(SUM(amount_cents), 0) total_cents,
                          COALESCE(AVG(overall_confidence), 0) avg_conf
                   FROM checks WHERE deleted = 0"""
            ).fetchone()
        return dict(row)

    @staticmethod
    def _where(flt: CheckFilter) -> tuple[str, tuple]:
        clauses, params = [], []
        if not flt.include_deleted:
            clauses.append("deleted = 0")
        if flt.status:
            clauses.append("status = ?")
            params.append(flt.status.upper())
        if flt.search:
            like = f"%{flt.search.strip()}%"
            clauses.append("(payee LIKE ? OR bank LIKE ? OR check_number LIKE ? OR file_name LIKE ? OR raw_text LIKE ?)")
            params.extend([like] * 5)
        if flt.date_from:
            clauses.append("check_date >= ?")
            params.append(flt.date_from)
        if flt.date_to:
            clauses.append("check_date <= ?")
            params.append(flt.date_to)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)

    @staticmethod
    def _to_row(r: CheckRecord) -> dict:
        amount = r.amount
        return {
            "file_name": r.file_name,
            "file_path": r.file_path,
            "page": r.page,
            "file_hash": r.file_hash,
            "status": r.status,
            "processed_at": r.processed_at,
            "processing_ms": r.processing_ms,
            "bank": r.value(FieldKey.BANCO),
            "check_number": r.value(FieldKey.NUMERO_CHEQUE),
            "check_date": r.value(FieldKey.FECHA),
            "payee": r.value(FieldKey.BENEFICIARIO),
            "amount_cents": int(amount * 100) if amount is not None else None,
            "amount_words_value": str(r.amount_words_value) if r.amount_words_value is not None else None,
            "amount_match": None if r.amount_match is None else int(r.amount_match),
            "overall_confidence": r.overall_confidence,
            "fields_json": json.dumps({k: f.to_dict() for k, f in r.fields.items()}, ensure_ascii=False),
            "observations_json": json.dumps(r.observations, ensure_ascii=False),
            "raw_text": r.raw_text,
            "preview_path": r.preview_path,
            "error": r.error,
            "edited": int(r.edited),
            "deleted": int(r.deleted),
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CheckRecord:
        fields = {k: ExtractedField.from_dict(v) for k, v in json.loads(row["fields_json"]).items()}
        return CheckRecord(
            id=row["id"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            page=row["page"],
            file_hash=row["file_hash"],
            status=row["status"],
            processed_at=row["processed_at"],
            processing_ms=row["processing_ms"],
            fields=fields,
            amount_words_value=Decimal(row["amount_words_value"]) if row["amount_words_value"] else None,
            amount_match=None if row["amount_match"] is None else bool(row["amount_match"]),
            overall_confidence=row["overall_confidence"],
            observations=json.loads(row["observations_json"]),
            raw_text=row["raw_text"] or "",
            preview_path=row["preview_path"] or "",
            error=row["error"],
            edited=bool(row["edited"]),
            deleted=bool(row["deleted"]),
        )
