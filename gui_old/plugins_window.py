from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .plugins import PluginManager


class PluginsWindow(QtWidgets.QDialog):
    """Окно менеджера модов (первая версия).

    Показывает список плагинов из mods/ и позволяет
    включать/выключать их двойным кликом.
    """

    def __init__(self, manager: PluginManager, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager

        self.setWindowTitle("Ghost — Моды")
        self.setObjectName("PluginsWindow")
        self.setModal(False)
        self.resize(620, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Установленные моды")
        title.setObjectName("PluginsTitle")
        layout.addWidget(title)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("PluginsList")
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        hint = QtWidgets.QLabel(
            "Двойной клик по модулю — включить/выключить.\n"
            "Моды ищутся в каталоге 'mods' рядом с проектом."
        )
        hint.setObjectName("PluginsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)

        self.refresh_button = QtWidgets.QPushButton("Обновить список")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)

        layout.addLayout(buttons)

        self.manager.plugins_changed.connect(self.refresh)
        self.refresh()

    # --- UI helpers ------------------------------------------------------------

    def refresh(self) -> None:
        self.list_widget.clear()

        if not self.manager.plugins:
            self.list_widget.addItem("Папка 'mods' пуста. Добавьте моды в каталог 'mods/'.")
            self.list_widget.setEnabled(False)
            return

        self.list_widget.setEnabled(True)

        for plugin_id, plugin in sorted(
            self.manager.plugins.items(), key=lambda item: item[1].meta.name.lower()
        ):
            prefix = "✓ " if plugin.enabled else "  "
            meta = plugin.meta
            text = f"{prefix}{meta.name} [{meta.plugin_id}]"
            if meta.version:
                text += f" v{meta.version}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, meta.plugin_id)
            self.list_widget.addItem(item)

    def _on_item_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        plugin_id = item.data(QtCore.Qt.UserRole)
        if not plugin_id:
            return
        plugin = self.manager.plugins.get(plugin_id)
        if not plugin:
            return

        if plugin.enabled:
            self.manager.disable_plugin(plugin_id)
        else:
            self.manager.enable_plugin(plugin_id)
