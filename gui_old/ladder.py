from __future__ import annotations

import time
from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from .backend import BackendReader


class LadderModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[dict] = []
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0
        self.tick_size: float = 0.0

        # Pre-create colors/brushes to avoid allocating
        # them on every paint call.
        self._color_dim = QtGui.QColor("#606060")
        self._color_default = QtGui.QColor("#f0f0f0")
        self._color_ask_fg = QtGui.QColor(255, 180, 190)
        self._color_bid_fg = QtGui.QColor(170, 255, 190)
        self._color_best = QtGui.QColor("#303030")

        self._transparent_brush = QtGui.QBrush(QtCore.Qt.transparent)
        ask = QtGui.QColor(180, 40, 50)
        bid = QtGui.QColor(40, 140, 70)
        self._heat_brush = {
            ("ask", False): QtGui.QBrush(ask),
            ("ask", True): QtGui.QBrush(ask.lighter(120)),
            ("bid", False): QtGui.QBrush(bid),
            ("bid", True): QtGui.QBrush(bid.lighter(120)),
        }

    def update_from_payload(self, payload: dict) -> None:
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

    @staticmethod
    def _format_price(price: float) -> str:
        if price <= 0:
            return ""
        if price >= 1.0:
            return f"{price:,.2f}".rstrip("0").rstrip(".")

        s = f"{price:.8f}"
        if "." not in s:
            return s
        int_part, frac_part = s.split(".")
        if int_part != "0":
            return f"{price:.6f}".rstrip("0").rstrip(".")

        zeros = 0
        for ch in frac_part:
            if ch == "0":
                zeros += 1
            else:
                break

        digits = frac_part[zeros : zeros + 4]
        if not digits:
            digits = "0"
        digits = digits.ljust(4, "0")
        return f"({zeros}){digits}"

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self.rows)

    def row_for_mid(self) -> int:
        if not self.rows:
            return -1
        if self.best_bid > 0 and self.best_ask > 0:
            target = 0.5 * (self.best_bid + self.best_ask)
        else:
            target = self.best_bid or self.best_ask or 0.0
        best_idx = -1
        best_diff = float("inf")
        for i, row in enumerate(self.rows):
            price = float(row.get("price", 0.0))
            diff = abs(price - target)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # type: ignore[override]
        return 2

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
                return ""
            if index.column() == 1:
                side_notional = ask_notional if ask_notional > 0 else bid_notional
                vol_text = self._format_notional(side_notional)
                price_text = self._format_price(price)
                if vol_text:
                    return f"{vol_text}  {price_text}"
                return price_text

        if role == QtCore.Qt.TextAlignmentRole:
            if index.column() == 1:
                return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            if index.column() == 0:
                return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter

        if role == QtCore.Qt.BackgroundRole:
            side = None
            value = 0.0
            if ask_notional > 0 or bid_notional > 0:
                if ask_notional >= bid_notional:
                    side = "ask"
                    value = ask_notional
                else:
                    side = "bid"
                    value = bid_notional

            if side is not None and index.column() == 1 and value > 0:
                highlight = (side == "ask" and is_best_ask) or (side == "bid" and is_best_bid)
                return self._heat_color(value, side=side, highlight=highlight)

            if index.column() == 1 and (is_best_bid or is_best_ask):
                return self._color_best

        if role == QtCore.Qt.ForegroundRole:
            if index.column() == 0:
                return self._color_dim

            side = None
            if ask_notional > 0 or bid_notional > 0:
                if ask_notional >= bid_notional:
                    side = "ask"
                else:
                    side = "bid"

            if side == "ask":
                return self._color_ask_fg
            if side == "bid":
                return self._color_bid_fg
            return self._color_default

        return None

    def _heat_color(self, value: float, side: str, highlight: bool) -> QtGui.QBrush:
        if value <= 0:
            return self._transparent_brush

        return self._heat_brush.get((side, highlight), self._transparent_brush)


class LadderView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setVisible(False)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setFrameStyle(QtWidgets.QFrame.NoFrame)
        self.verticalHeader().setDefaultSectionSize(14)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        self.setColumnWidth(0, 70)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.setStyleSheet(
            "QTableView { background: #202020; color: #f0f0f0; }"
            "QTableView::item { padding: 0px 3px; border: 0px; }"
        )
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        # Keep individual ladder reasonably narrow so many ladders
        # do not force the main window to huge minimum width.
        return QtCore.QSize(220, 400)

    def minimumSizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(120, 200)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Shift:
            model = self.model()
            if isinstance(model, LadderModel):
                row = model.row_for_mid()
                if row >= 0:
                    sb = self.verticalScrollBar()
                    row_height = self.verticalHeader().defaultSectionSize()
                    visible_rows = max(1, self.viewport().height() // row_height)
                    center_value = max(0, min(row - visible_rows // 2, sb.maximum()))
                    sb.setValue(center_value)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        index = self.indexAt(event.pos())
        parent = self.parent()
        if index.isValid() and hasattr(parent, "_on_view_click"):
            try:
                parent._on_view_click(index, event)  # type: ignore[attr-defined]
            except Exception:
                pass
        super().mousePressEvent(event)


class LadderWidget(QtWidgets.QWidget):
    logMessage = QtCore.Signal(str)
    rowClicked = QtCore.Signal(int, float, float, float)

    def __init__(self, backend_path: Path, symbol: str, levels: int, parent=None):
        super().__init__(parent)
        self.backend_path = backend_path
        self.symbol = symbol.upper()
        self.levels = levels
        self._pending_payload: dict | None = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.status_label = QtWidgets.QLabel("Initializing…")
        self.status_label.setObjectName("LadderStatusLabel")
        self.status_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.status_label.setStyleSheet("color: #52e7ff; padding: 0px;")
        layout.addWidget(self.status_label)

        self.model = LadderModel(self)
        self.view = LadderView(self)
        self.view.setModel(self.model)
        self.view.setFocus()
        layout.addWidget(self.view, 1)

        self.backend_thread = BackendReader(backend_path, self.symbol, levels)
        self.backend_thread.ladderReceived.connect(self._on_ladder)
        self.backend_thread.logReceived.connect(self._on_log)
        self.backend_thread.start()

    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        # Reasonable default column width so many ladders
        # do not force the main window to huge minimum width.
        return QtCore.QSize(260, 420)

    def minimumSizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        # Allow columns to shrink quite a lot if space is tight.
        return QtCore.QSize(140, 240)

    @QtCore.Slot(dict)
    def _on_ladder(self, payload: dict) -> None:
        # Just remember the latest payload; the timer will
        # apply it on the GUI thread at a controlled rate.
        self._pending_payload = payload

    @QtCore.Slot()
    def _flush_pending_payload(self) -> None:
        payload = self._pending_payload
        if not payload:
            return
        self._pending_payload = None
        scroll_value = self.view.verticalScrollBar().value()
        self.model.update_from_payload(payload)
        self.view.verticalScrollBar().setValue(scroll_value)

        # Only show ping in the status label, the rest
        # (symbol, bid/ask, spread) is not needed here.
        ping_text = "ping -- ms"
        ts = payload.get("timestamp")
        if isinstance(ts, (int, float)):
            ping_ms = max(0, int(time.time() * 1000 - ts))
            ping_text = f"ping {ping_ms} ms"

        self.status_label.setText(ping_text)

    def _on_view_click(self, index: QtCore.QModelIndex, event: QtGui.QMouseEvent | None = None) -> None:
        if not index.isValid():
            return
        row = index.row()
        if not (0 <= row < len(self.model.rows)):
            return
        row_data = self.model.rows[row]
        price = float(row_data.get("price", 0.0))
        bid = float(row_data.get("bid", 0.0))
        ask = float(row_data.get("ask", 0.0))
        self.rowClicked.emit(row, price, bid, ask)

    @QtCore.Slot()
    def flush_pending(self) -> None:
        """Called from the main window's global ladder timer."""
        self._flush_pending_payload()

    @QtCore.Slot(str)
    def _on_log(self, text: str) -> None:
        self.logMessage.emit(f"[{self.symbol}] {text}")

    def shutdown(self) -> None:
        self.backend_thread.stop()
        self.backend_thread.wait(2000)
