"""Almacén en memoria de claves de idempotencia (header Idempotency-Key) para operaciones POST."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def run_once(self, key: Optional[str], action: Callable[[], Any]) -> Any:
        if not key:
            return action()
        now = time.time()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if now - v[0] < self._ttl}
            if key in self._items:
                return self._items[key][1]
            result = action()
            self._items[key] = (now, result)
            return result
