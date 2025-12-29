from __future__ import annotations

from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """
    Проксирует вызов в gui.app.main, но импортирует модуль лениво,
    чтобы не ловить warning при запуске `python -m gui.app`.
    """
    from .app import main as _main

    return _main(argv)


__all__ = ["main"]
