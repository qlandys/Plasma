from __future__ import annotations

from typing import Dict, Tuple

from PySide6 import QtCore, QtWidgets


class SettingsWindow(QtWidgets.QDialog):
    """Окно настроек терминала (первая версия).

    Сейчас содержит только вкладку с настройками модов
    и их горячих клавиш.
    """

    def __init__(self, terminal, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._terminal = terminal
        self._plugin_manager = terminal.plugin_manager

        self.setWindowTitle("Ghost — Настройки")
        self.setObjectName("SettingsWindow")
        self.setModal(False)
        self.resize(700, 480)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_plugins_tab()

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)

        self.save_button = QtWidgets.QPushButton("Сохранить")
        self.save_button.clicked.connect(self._save_and_apply)
        buttons.addWidget(self.save_button)

        self.close_button = QtWidgets.QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)

        layout.addLayout(buttons)

    # --- plugins tab -----------------------------------------------------------

    def _build_plugins_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QtWidgets.QLabel(
            "Горячие клавиши модов.\n"
            "Измените сочетание и нажмите «Сохранить», чтобы применить."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        table = QtWidgets.QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Мод", "Действие", "Горячая клавиша"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.plugins_table = table
        layout.addWidget(table, 1)

        self.tabs.addTab(tab, "Моды")
        self._populate_plugins_tab()

    def _populate_plugins_tab(self) -> None:
        table = self.plugins_table
        table.setRowCount(0)

        meta_map: Dict[Tuple[str, str], Tuple[str, object]] = getattr(
            self._terminal, "_plugin_hotkey_meta", {}
        )
        if not meta_map:
            table.setRowCount(0)
            return

        for (plugin_id, action_id), (default_seq, _cb) in meta_map.items():
            plugin = self._plugin_manager.plugins.get(plugin_id)
            name = plugin.meta.name if plugin else plugin_id
            seq_str = self._plugin_manager.config.get_hotkey(
                plugin_id, action_id, default_seq
            )

            row = table.rowCount()
            table.insertRow(row)

            item_mod = QtWidgets.QTableWidgetItem(name)
            item_mod.setData(QtCore.Qt.UserRole, plugin_id)
            table.setItem(row, 0, item_mod)

            item_action = QtWidgets.QTableWidgetItem(action_id)
            item_action.setData(QtCore.Qt.UserRole, action_id)
            table.setItem(row, 1, item_action)

            edit = QtWidgets.QLineEdit(seq_str)
            table.setCellWidget(row, 2, edit)

    def _save_and_apply(self) -> None:
        table = self.plugins_table
        config = self._plugin_manager.config

        for row in range(table.rowCount()):
            mod_item = table.item(row, 0)
            action_item = table.item(row, 1)
            editor = table.cellWidget(row, 2)
            if (
                mod_item is None
                or action_item is None
                or not isinstance(editor, QtWidgets.QLineEdit)
            ):
                continue

            plugin_id = str(mod_item.data(QtCore.Qt.UserRole) or "")
            action_id = str(action_item.data(QtCore.Qt.UserRole) or "")
            seq = editor.text().strip()
            if not plugin_id or not action_id:
                continue

            config.set_hotkey(plugin_id, action_id, seq)

        config.save()
        # Пересоздаём QShortcut'ы на основе новых настроек.
        reload_hotkeys = getattr(self._terminal, "_reload_plugin_hotkeys_from_config", None)
        if callable(reload_hotkeys):
            reload_hotkeys()
