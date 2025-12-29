from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


PLUGIN_META = {
    "id": "ladder_clicker",
    "name": "Ladder Clicker (demo)",
    "version": "0.1",
    "description": "Пример мода: добавляет простейший кликер для стакана.",
    "author": "Ghost",
}


class ClickerController(QtCore.QObject):
    """Очень простой кликер для демонстрации API.

    Никаких глобальных кликов по системе — только события
    внутри виджета стакана.
    """

    def __init__(self, ladder_handle, parent=None):
        super().__init__(parent)
        self.ladder_handle = ladder_handle
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)  # полный цикл 1 секунда
        self.timer.timeout.connect(self._on_timeout)
        self._pressed = False

    def toggle(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.ladder_handle._api.log(f"clicker OFF for {self.ladder_handle.symbol}")
        else:
            self.timer.start()
            self._pressed = False
            self.ladder_handle._api.log(f"clicker ON for {self.ladder_handle.symbol}")

    def _on_timeout(self) -> None:
        view = getattr(self.ladder_handle.ladder, "view", None)
        if view is None or not isinstance(view, QtWidgets.QWidget):
            return

        # Кликаем примерно по центру виджета стакана.
        rect = view.rect()
        pos = rect.center()
        global_pos = view.mapToGlobal(pos)

        button = QtCore.Qt.LeftButton
        if not self._pressed:
            event_type = QtCore.QEvent.MouseButtonPress
            self._pressed = True
        else:
            event_type = QtCore.QEvent.MouseButtonRelease
            self._pressed = False

        ev = QtGui.QMouseEvent(
            event_type,
            pos,
            global_pos,
            button,
            button,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(view, ev)


def register(api) -> Any:
    api.log("ladder_clicker loaded")

    controllers: dict[str, ClickerController] = {}

    def on_ladder_created(handle):
        # Для каждого стакана создаём контроллер и кнопку в заголовке.
        controller = ClickerController(handle, parent=handle.ladder)
        controllers[handle.symbol] = controller

        def on_button_clicked() -> None:
            controller.toggle()

        handle.add_header_button(
            icon_name="keyboard",
            tooltip="Demo clicker (включить/выключить)",
            callback=on_button_clicked,
        )

    api.register_ladder_hook(on_ladder_created)

    # Горячая клавиша для включения/выключения кликера на всех стаканах.
    def toggle_all() -> None:
        for controller in controllers.values():
            controller.toggle()

    api.register_hotkey(
        plugin_id=PLUGIN_META["id"],
        action_id="toggle_clicker",
        default_sequence="Ctrl+Shift+C",
        callback=toggle_all,
    )

    return {"controllers": controllers}


def unregister(api, handle) -> None:
    api.log("ladder_clicker unloaded")
    data = handle or {}
    for controller in data.get("controllers", {}).values():
        controller.timer.stop()
