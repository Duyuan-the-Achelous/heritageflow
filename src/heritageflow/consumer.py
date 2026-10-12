from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Any


logger = logging.getLogger("heritageflow.consumer")


class OutboxConsumer:
    def __init__(self, service: Any, *, interval_seconds: float = 0.25, batch_size: int = 100):
        self.service = service
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._stop = Event()
        self._thread = Thread(target=self._run, name="outbox-consumer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.service.process_outbox_batch(self.batch_size)
                if processed == 0:
                    self._stop.wait(self.interval_seconds)
            except Exception:
                logger.exception("outbox consumer batch failed")
                self._stop.wait(self.interval_seconds)
