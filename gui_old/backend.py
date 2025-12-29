from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore


class BackendReader(QtCore.QThread):
    ladderReceived = QtCore.Signal(dict)
    logReceived = QtCore.Signal(str)

    def __init__(self, backend_path: Path, symbol: str, levels: int, parent=None):
        super().__init__(parent)
        self._backend_path = backend_path
        self._symbol = symbol
        self._levels = levels
        self._proc: Optional[subprocess.Popen] = None

    def run(self) -> None:
        cmd: List[str] = [
            str(self._backend_path),
            "--symbol",
            self._symbol,
            "--ladder-levels",
            str(self._levels),
        ]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.logReceived.emit(f"failed to start backend: {exc}")
            return

        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        def pump_stderr() -> None:
            for line in self._proc.stderr:
                line = line.rstrip()
                if line:
                    self.logReceived.emit(line)

        stderr_thread = QtCore.QThread()
        stderr_thread.run = pump_stderr  # type: ignore[attr-defined]
        stderr_thread.start()

        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self.logReceived.emit(f"unparsable backend line: {line[:160]}")
                continue

            if payload.get("type") == "ladder":
                self.ladderReceived.emit(payload)
            else:
                self.logReceived.emit(line)

        self._proc.wait()

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()

