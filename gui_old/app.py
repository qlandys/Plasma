from __future__ import annotations

import argparse
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from .terminal_window import TerminalWindow


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghost GUI")
    parser.add_argument("--symbol", default="BIOUSDT")
    parser.add_argument("--levels", type=int, default=120)
    parser.add_argument("--backend-path", type=Path, default=None)
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parents[1]
    backend_path = args.backend_path or guess_backend(base)

    app = QtWidgets.QApplication([])
    app.setFont(QtGui.QFont("Verdana", 9))
    icon_path = base / "img" / "logo" / "favicon.ico"
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))

    win = TerminalWindow(backend_path, [args.symbol], args.levels)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())



