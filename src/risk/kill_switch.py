from __future__ import annotations

from pathlib import Path
from threading import Lock


class KillSwitch:
    def __init__(self, initial_state: bool, kill_file: str) -> None:
        self._manual = initial_state
        self._file_path = Path(kill_file)
        self._lock = Lock()

    def is_active(self) -> bool:
        with self._lock:
            if self._manual:
                return True
        return self._file_path.exists()

    def trigger(self) -> None:
        with self._lock:
            self._manual = True

    def clear(self) -> None:
        with self._lock:
            self._manual = False
