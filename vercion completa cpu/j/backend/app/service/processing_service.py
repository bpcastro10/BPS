"""Cola de procesamiento en segundo plano y vigilancia de la carpeta de entrada (solo archivos nuevos)."""
from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config.settings import SUPPORTED_EXTENSIONS, Settings
from app.enums import CheckStatus
from app.model import CheckRecord
from app.repository.check_repository import CheckRepository
from app.service.analysis.check_analyzer import CheckAnalyzer
from app.service.analysis.ocr_engine import OcrEngine

log = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ProcessingStatus:
    watching: bool
    input_dir: str
    queue_size: int
    current_file: Optional[str]
    processed_session: int
    errors_session: int
    last_scan: Optional[str]
    version: int
    engine_ready: bool


class ProcessingService:
    def __init__(self, settings: Settings, repository: CheckRepository, analyzer: CheckAnalyzer, ocr: OcrEngine):
        self._settings = settings
        self._repo = repository
        self._analyzer = analyzer
        self._ocr = ocr
        self._queue: "queue.Queue[tuple[Path, str, Optional[int]]]" = queue.Queue()
        self._queued_hashes: set[str] = set()
        self._seen: dict[str, tuple[int, float]] = {}
        self._pending_size: dict[str, int] = {}
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._current: Optional[str] = None
        self._processed = 0
        self._errors = 0
        self._last_scan: Optional[str] = None
        self._version = 0
        self._engine_ready = False

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        threading.Thread(target=self._worker_loop, name="cheques-worker", daemon=True).start()
        threading.Thread(target=self._watch_loop, name="cheques-watcher", daemon=True).start()
        log.info("Vigilando la carpeta: %s", self._settings.input_dir)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ vigilancia de carpeta
    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception:
                log.exception("Error escaneando la carpeta de entrada")
            self._stop.wait(self._settings.poll_seconds)

    def scan(self) -> int:
        """Encola solo los archivos nuevos o modificados. Devuelve cuántos se encolaron."""
        with self._scan_lock:
            return self._scan_folder()

    def _scan_folder(self) -> int:
        enqueued = 0
        for path in sorted(self._settings.input_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS or path.name.startswith("~$"):
                continue
            key = str(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            signature = (stat.st_size, stat.st_mtime)
            if self._seen.get(key) == signature:
                continue
            if self._pending_size.get(key) != stat.st_size:
                self._pending_size[key] = stat.st_size
                continue
            self._pending_size.pop(key, None)
            self._seen[key] = signature
            if self._enqueue_if_new(path):
                enqueued += 1
        self._last_scan = datetime.now().isoformat(timespec="seconds")
        return enqueued

    def _enqueue_if_new(self, path: Path, force_id: Optional[int] = None) -> bool:
        try:
            digest = file_sha256(path)
        except OSError as exc:
            log.warning("No se pudo leer %s: %s", path.name, exc)
            return False
        with self._lock:
            if force_id is None and (digest in self._queued_hashes or self._repo.exists_by_hash(digest)):
                return False
            self._queued_hashes.add(digest)
        self._queue.put((path, digest, force_id))
        log.info("Nuevo archivo en cola: %s", path.name)
        return True

    def reprocess(self, record: CheckRecord) -> bool:
        path = Path(record.file_path)
        if not path.exists():
            return False
        return self._enqueue_if_new(path, force_id=record.id)

    # ------------------------------------------------------------ procesamiento
    def _worker_loop(self) -> None:
        try:
            self._ocr.warmup()
        except Exception:
            log.exception("No se pudo cargar el motor OCR")
        self._engine_ready = True
        while not self._stop.is_set():
            try:
                path, digest, force_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._current = path.name
            try:
                self._process(path, digest, force_id)
            finally:
                with self._lock:
                    self._queued_hashes.discard(digest)
                self._current = None
                self._queue.task_done()

    def _process(self, path: Path, digest: str, force_id: Optional[int]) -> None:
        try:
            records = self._analyzer.analyze_file(path, digest)
        except Exception as exc:
            log.exception("Error analizando %s", path.name)
            records = [CheckRecord(file_name=path.name, file_path=str(path), file_hash=digest,
                                   status=CheckStatus.ERROR.value, error=str(exc),
                                   processed_at=datetime.now().isoformat(timespec="seconds"),
                                   observations=[f"Error al procesar: {exc}"])]
            self._errors += 1
        for record in records:
            if force_id is not None and record.page == 1:
                record.id = force_id
            self._repo.save(record)
            self._processed += 1
        self._version += 1

    def mark_changed(self) -> None:
        self._version += 1

    def status(self) -> ProcessingStatus:
        return ProcessingStatus(
            watching=not self._stop.is_set(),
            input_dir=str(self._settings.input_dir),
            queue_size=self._queue.qsize() + (1 if self._current else 0),
            current_file=self._current,
            processed_session=self._processed,
            errors_session=self._errors,
            last_scan=self._last_scan,
            version=self._version,
            engine_ready=self._engine_ready,
        )
