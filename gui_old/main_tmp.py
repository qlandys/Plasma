import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets


class BackendReader(QtCore.QThread):
    ladderReceived = QtCore.Signal(dict)
    logReceived = QtCore.Signal(str)

    def __init__(self, backend_path: Path, symbol: str, levels: int, parent=None):
        super().__init__(parent)
        self._backend_path = backend_path
        self._symbol = symbol
        self._levels = levels
        self._proc: Optional[subprocess.Popen] = None

    def run(self):
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

        # stderr reader
        def pump_stderr():
            for line in self._proc.stderr:
                line = line.rstrip()
                if line:
                    self.logReceived.emit(line)

        stderr_thread = QtCore.QThread()
        stderr_worker = QtCore.QObject()
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

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class LadderModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[dict] = []
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0
        self.tick_size: float = 0.0

    def update_from_payload(self, payload: dict):
        self.beginResetModel()
        self.rows = payload.get("rows", [])
        self.best_bid = float(payload.get("bestBid", 0.0))
        self.best_ask = float(payload.get("bestAsk", 0.0))
        self.tick_size = float(payload.get("tickSize", 0.0))
        self.endResetModel()

    @staticmethod
    def _format_notional(value: float) -> str:
        if value <= 0:
            return ""
        if value >= 1000:
            return f"{value:,.0f}".replace(",", "")
        if value >= 1:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    # QAbstractTableModel API

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        return 3

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None

        row = self.rows[index.row()]
        price = float(row.get("price", 0.0))
        bid_qty = float(row.get("bid", 0.0))
        ask_qty = float(row.get("ask", 0.0))

        bid_notional = bid_qty * price
        ask_notional = ask_qty * price

        is_best_bid = price == self.best_bid
        is_best_ask = price == self.best_ask

        if role == QtCore.Qt.DisplayRole:
            if index.column() == 0:
                return self._format_notional(ask_notional)
            if index.column() == 1:
                return f"{price:.6f}"
            if index.column() == 2:
                return self._format_notional(bid_notional)

        if role == QtCore.Qt.TextAlignmentRole:
            if index.column() == 1:
                return QtCore.Qt.AlignCenter
            if index.column() == 0:
                return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter

        if role == QtCore.Qt.BackgroundRole:
            # heat-map по денежному объёму
            if index.column() == 0 and ask_notional > 0:
                return self._heat_color(ask_notional, side="ask", highlight=is_best_ask)
            if index.column() == 2 and bid_notional > 0:
                return self._heat_color(bid_notional, side="bid", highlight=is_best_bid)
            if index.column() == 1 and (is_best_bid or is_best_ask):
                return QtGui.QColor("#303030")

        if role == QtCore.Qt.ForegroundRole:
            if index.column() == 1:
                return QtGui.QColor("#c0c0c0")
            return QtGui.QColor("#f0f0f0")

        return None

    def _heat_color(self, value: float, side: str, highlight: bool) -> QtGui.QBrush:
        if value <= 0:
            return QtGui.QBrush(QtCore.Qt.transparent)

        import math

        strength = min(1.0, math.log10(1.0 + value) / 3.0)
        base = QtGui.QColor(200, 80, 90) if side == "ask" else QtGui.QColor(50, 160, 90)
        if highlight:
            strength = 1.0
        color = QtGui.QColor(base)
        color.setAlphaF(0.15 + 0.75 * strength)
        return QtGui.QBrush(color)


class LadderView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setVisible(False)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setFrameStyle(QtWidgets.QFrame.NoFrame)
        self.verticalHeader().setDefaultSectionSize(18)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.setStyleSheet(
            "QTableView { background: #1b1b1b; color: #f0f0f0; font: 10pt 'Consolas'; }"
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, backend_path: Path, symbol: str, levels: int):
        super().__init__()
        self.backend_path = backend_path
        self.symbol = symbol.upper()
        self.levels = levels

        self.setWindowTitle(f"{self.symbol} Ladder - Mexc")
        self.resize(260, 720)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.status_label = QtWidgets.QLabel("Initializing…")
        self.status_label.setStyleSheet("color: #60c0ff; font: 9pt 'Consolas';")
        layout.addWidget(self.status_label)

        self.model = LadderModel(self)
        self.view = LadderView(self)
        self.view.setModel(self.model)
        layout.addWidget(self.view, 1)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setFixedHeight(100)
        self.log.setStyleSheet(
            "QPlainTextEdit { background: #111; color: #999; font: 8pt 'Consolas'; }"
        )
        layout.addWidget(self.log)

        self.backend_thread = BackendReader(backend_path, self.symbol, levels)
        self.backend_thread.ladderReceived.connect(self._on_ladder)
        self.backend_thread.logReceived.connect(self._append_log)
        self.backend_thread.start()

    @QtCore.Slot(dict)
    def _on_ladder(self, payload: dict):
        # Preserve scroll position so the ladder does not jump.
        scroll_value = self.view.verticalScrollBar().value()
        self.model.update_from_payload(payload)
        self.view.verticalScrollBar().setValue(scroll_value)

        spread = payload.get("bestAsk", 0) - payload.get("bestBid", 0)
        self.status_label.setText(
            f"{self.symbol}  |  bid {payload.get('bestBid', 0):,.5f} / "
            f"ask {payload.get('bestAsk', 0):,.5f}  |  spread {spread:.5f}"
        )

    @QtCore.Slot(str)
    def _append_log(self, text: str):
        self.log.appendPlainText(text)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.backend_thread.stop()
        self.backend_thread.wait(2000)
        super().closeEvent(event)


def guess_backend(base: Path) -> Path:
    candidates = [
        base / "build" / "Release" / "orderbook_backend.exe",
        base / "build" / "orderbook_backend.exe",
        base / "orderbook_backend.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Mexc ladder GUI (PySide6)")
    parser.add_argument("--symbol", default="BIOUSDT")
    parser.add_argument("--levels", type=int, default=120)
    parser.add_argument("--backend-path", type=Path, default=None)
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]
    backend_path = args.backend_path or guess_backend(base)

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(backend_path, args.symbol, args.levels)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

