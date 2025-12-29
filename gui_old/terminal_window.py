from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from .ladder import LadderWidget
from .plugins import PluginApi, PluginManager, LadderHandle
from .settings_window import SettingsWindow
from .plugins_window import PluginsWindow


class NavToolButton(QtWidgets.QToolButton):
    """Side toolbar button with hover tint."""

    def __init__(self, icon_loader, icon_name: str, parent=None):
        super().__init__(parent)
        self._icon_loader = icon_loader
        self._icon_name = icon_name
        self._icon_idle = self._icon_loader(icon_name, "#c0c0c0")
        self._icon_hover = self._icon_loader(icon_name, "#ffffff")

        self.setObjectName("SideToolButton")
        self.setAutoRaise(True)
        self.setIcon(self._icon_idle)
        self.setIconSize(QtCore.QSize(24, 24))

    def enterEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        self.setIcon(self._icon_hover)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        self.setIcon(self._icon_idle)
        super().leaveEvent(event)


class TerminalWindow(QtWidgets.QMainWindow):
    def __init__(self, backend_path: Path, symbols: List[str], levels: int):
        super().__init__()
        self.setObjectName("TerminalWindow")
        self.backend_path = backend_path
        self.symbols = [s.upper() for s in symbols] or ["BIOUSDT"]
        self.levels = levels

        self.ladders: List[LadderWidget] = []
        self._tabs: List[Dict[str, Any]] = []
        self._next_tab_number = 1
        self._next_tab_id = 1
        self._tab_indicator_anim: Optional[QtCore.QPropertyAnimation] = None
        self._plugins_window: Optional[PluginsWindow] = None
        self._settings_window: Optional[SettingsWindow] = None

        base = Path(__file__).resolve().parents[1]
        self.base_path = base
        self.logo_path = base / "img" / "logo" / "favicon-32x32.png"
        self.icons_dir = base / "img" / "icons"

        # Plugin system: API + manager for mods/ directory.
        self.plugin_api = PluginApi(self)
        self.plugin_manager = PluginManager(self.base_path / "mods", self.plugin_api, parent=self)
        self.plugin_manager.discover()
        self._plugin_shortcuts: Dict[tuple[str, str], QtWidgets.QShortcut] = {}
        self._plugin_hotkey_meta: Dict[
            tuple[str, str], tuple[str, Callable[[], None]]
        ] = {}
        self._ladder_handle_by_widget: Dict[LadderWidget, LadderHandle] = {}

        self.setWindowTitle("Ghost")
        self.resize(1600, 900)
        self.setMinimumSize(800, 400)

        if self.logo_path.exists():
            icon = QtGui.QIcon(str(self.logo_path))
            self.setWindowIcon(icon)

        central = QtWidgets.QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)

        self._build_top_bar(root_layout)
        self._build_main_area(root_layout)
        self._apply_style()
        self._start_time_timer()
        self._start_ladder_timer()

    # --- icons -------------------------------------------------------------------

    def _icon(self, name: str, color: str = "#ffffff") -> QtGui.QIcon:
        path = self.icons_dir / f"{name}.svg"
        if not path.exists():
            return QtGui.QIcon()

        base_icon = QtGui.QIcon(str(path))
        base_pixmap = base_icon.pixmap(32, 32)
        if base_pixmap.isNull():
            return base_icon

        tinted = QtGui.QPixmap(base_pixmap.size())
        tinted.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(tinted)
        painter.drawPixmap(0, 0, base_pixmap)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QtGui.QColor(color))
        painter.end()

        icon = QtGui.QIcon()
        icon.addPixmap(tinted)
        return icon

    # --- layout ------------------------------------------------------------------

    def _build_top_bar(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        top = QtWidgets.QFrame()
        top.setObjectName("TopBar")
        layout = QtWidgets.QHBoxLayout(top)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        left = QtWidgets.QHBoxLayout()
        left.setSpacing(8)

        logo_label = QtWidgets.QLabel()
        logo_label.setObjectName("LogoLabel")
        logo_label.setFixedSize(28, 28)
        if self.logo_path.exists():
            pixmap = QtGui.QPixmap(str(self.logo_path)).scaled(
                28,
                28,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            logo_label.setPixmap(pixmap)
        left.addWidget(logo_label)

        # workspace tabs container
        self.workspace_tabs = QtWidgets.QTabBar()
        self.workspace_tabs.setObjectName("WorkspaceTabs")
        self.workspace_tabs.setExpanding(False)
        self.workspace_tabs.setTabsClosable(True)
        self.workspace_tabs.setMovable(True)
        self.workspace_tabs.setElideMode(QtCore.Qt.ElideRight)
        self.workspace_tabs.currentChanged.connect(self._on_tab_changed)
        self.workspace_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        left.addWidget(self.workspace_tabs)

        self.tab_indicator = QtWidgets.QFrame(self.workspace_tabs)
        self.tab_indicator.setObjectName("WorkspaceTabIndicator")
        self.tab_indicator.setFixedHeight(2)
        self.tab_indicator.hide()

        # + button with menu (new tab / new ladder)
        self.add_tab_button = QtWidgets.QToolButton()
        self.add_tab_button.setObjectName("AddTabButton")
        self.add_tab_button.setText("+")
        self.add_tab_button.setAutoRaise(True)
        self.add_tab_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)

        add_menu = QtWidgets.QMenu(self.add_tab_button)
        self._action_new_tab = add_menu.addAction("Новая вкладка")
        self._action_new_ladder = add_menu.addAction("Новый стакан")
        self._action_new_tab.triggered.connect(self._on_new_tab_requested)
        self._action_new_ladder.triggered.connect(self._on_new_ladder_requested)
        self.add_tab_button.setMenu(add_menu)
        left.addWidget(self.add_tab_button)

        left.addStretch(1)

        layout.addLayout(left, 1)

        right = QtWidgets.QHBoxLayout()
        right.setSpacing(16)

        self.connection_indicator = QtWidgets.QLabel("LIVE")
        self.connection_indicator.setObjectName("ConnectionIndicator")
        right.addWidget(self.connection_indicator)

        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setObjectName("TopBarToolButton")
        self.settings_button.setIcon(self._icon("settings"))
        self.settings_button.setIconSize(QtCore.QSize(18, 18))
        self.settings_button.setAutoRaise(True)
        self.settings_button.clicked.connect(self._open_settings_window)
        right.addWidget(self.settings_button)

        self.theme_button = QtWidgets.QToolButton()
        self.theme_button.setObjectName("TopBarToolButton")
        self.theme_button.setIcon(self._icon("moon-stars"))
        self.theme_button.setIconSize(QtCore.QSize(18, 18))
        self.theme_button.setAutoRaise(True)
        right.addWidget(self.theme_button)

        self.time_label = QtWidgets.QLabel()
        self.time_label.setObjectName("TimeLabel")
        right.addWidget(self.time_label)

        layout.addLayout(right)
        parent_layout.addWidget(top)

    def _build_navbar(self, parent: QtWidgets.QWidget) -> QtWidgets.QFrame:
        """Side icon toolbar."""
        bar = QtWidgets.QFrame(parent)
        bar.setObjectName("SideToolbar")
        bar.setFixedWidth(44)
        bar.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)

        layout = QtWidgets.QVBoxLayout(bar)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)
        layout.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)

        def add_btn(icon_name: str, tooltip: str) -> NavToolButton:
            btn = NavToolButton(self._icon, icon_name, parent=bar)
            btn.setToolTip(tooltip)
            layout.addWidget(btn)
            return btn

        add_btn("home", "Главная / DOM")
        add_btn("radar-2", "Радар")
        add_btn("layout-dashboard", "Панели")
        add_btn("history", "История")

        # Extensions / mods manager (like VSCode marketplace)
        self.plugins_button = add_btn("bolt", "Моды (расширения)")
        self.plugins_button.clicked.connect(self._open_plugins_window)

        layout.addStretch(1)
        add_btn("settings", "Настройки")

        return bar

    def _build_main_area(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        main = QtWidgets.QFrame()
        main.setObjectName("MainArea")
        layout = QtWidgets.QHBoxLayout(main)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        navbar = self._build_navbar(main)
        layout.addWidget(navbar)

        self.workspace_stack = QtWidgets.QStackedWidget()
        self.workspace_stack.setObjectName("WorkspaceStack")
        layout.addWidget(self.workspace_stack, 1)

        parent_layout.addWidget(main, 1)

        self._create_workspace_tab()

    # --- tabs / workspaces ------------------------------------------------------

    def _create_workspace_tab(self) -> None:
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        workspace = QtWidgets.QFrame()
        workspace.setObjectName("Workspace")
        ws_layout = QtWidgets.QVBoxLayout(workspace)
        ws_layout.setContentsMargins(12, 8, 12, 8)
        ws_layout.setSpacing(8)

        columns_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        columns_splitter.setObjectName("DomColumns")
        columns_splitter.setChildrenCollapsible(False)

        tab: Dict[str, Any] = {
            "id": tab_id,
            "workspace": workspace,
            "columns": columns_splitter,
            "ladders": [],
        }
        self._tabs.append(tab)

        for symbol in self.symbols:
            col = self._create_dom_column(symbol, tab)
            columns_splitter.addWidget(col)

        ws_layout.addWidget(columns_splitter, 1)

        stack_index = self.workspace_stack.addWidget(workspace)

        title = f"Вкладка {self._next_tab_number}"
        self._next_tab_number += 1
        tab_index = self.workspace_tabs.addTab(title)
        self.workspace_tabs.setTabData(tab_index, tab_id)

        self.workspace_tabs.setCurrentIndex(tab_index)
        self.workspace_stack.setCurrentIndex(stack_index)

        self._rebalance_columns(columns_splitter)
        self._update_tab_indicator(animated=False)

    def _rebalance_columns(self, splitter: QtWidgets.QSplitter) -> None:
        count = splitter.count()
        if count <= 0:
            return
        total_width = splitter.size().width() or count * 100
        size = max(50, total_width // count)
        splitter.setSizes([size] * count)

    def _current_tab(self) -> Optional[Dict[str, Any]]:
        index = self.workspace_tabs.currentIndex()
        if index < 0:
            return None
        tab_id = self.workspace_tabs.tabData(index)
        for tab in self._tabs:
            if tab.get("id") == tab_id:
                return tab
        return None

    def _find_tab_stack_index(self, tab_id: int) -> int:
        for i, tab in enumerate(self._tabs):
            if tab.get("id") == tab_id:
                return i
        return -1

    def _on_new_tab_requested(self) -> None:
        self._create_workspace_tab()

    def _on_new_ladder_requested(self) -> None:
        tab = self._current_tab()
        if not tab:
            return

        default_symbol = self.symbols[0] if self.symbols else "BIOUSDT"
        symbol, ok = QtWidgets.QInputDialog.getText(
            self,
            "Новый стакан",
            "Символ:",
            text=default_symbol,
        )
        if not ok:
            return
        symbol = symbol.strip().upper()
        if not symbol:
            return

        column = self._create_dom_column(symbol, tab)
        splitter: QtWidgets.QSplitter = tab["columns"]
        splitter.addWidget(column)
        self._rebalance_columns(splitter)

    def _on_tab_changed(self, index: int) -> None:
        if index < 0:
            self._update_tab_indicator(animated=False)
            return
        tab_id = self.workspace_tabs.tabData(index)
        stack_index = self._find_tab_stack_index(tab_id)
        if stack_index >= 0:
            self.workspace_stack.setCurrentIndex(stack_index)
        self._update_tab_indicator(animated=True)

    def _on_tab_close_requested(self, index: int) -> None:
        if self.workspace_tabs.count() <= 1:
            return

        tab_id = self.workspace_tabs.tabData(index)
        stack_index = self._find_tab_stack_index(tab_id)
        if stack_index < 0:
            return

        tab = self._tabs.pop(stack_index)

        for ladder in tab.get("ladders", []):
            ladder.shutdown()
            if ladder in self.ladders:
                self.ladders.remove(ladder)

        widget = self.workspace_stack.widget(stack_index)
        if widget is not None:
            self.workspace_stack.removeWidget(widget)
            widget.deleteLater()

        self.workspace_tabs.removeTab(index)

        if self.workspace_tabs.count():
            new_index = min(index, self.workspace_tabs.count() - 1)
            self.workspace_tabs.setCurrentIndex(new_index)
        else:
            self.workspace_stack.setCurrentIndex(-1)

        self._update_tab_indicator(animated=False)

    def _update_tab_indicator(self, animated: bool) -> None:
        if self.tab_indicator is None or self.workspace_tabs is None:
            return

        index = self.workspace_tabs.currentIndex()
        if index < 0:
            self.tab_indicator.hide()
            return

        tab_rect = self.workspace_tabs.tabRect(index)
        if not tab_rect.isValid():
            self.tab_indicator.hide()
            return

        height = self.tab_indicator.height() or 2
        y = tab_rect.bottom() - height + 1
        target = QtCore.QRect(tab_rect.left(), y, tab_rect.width(), height)

        if not self.tab_indicator.isVisible():
            self.tab_indicator.setGeometry(target)
            self.tab_indicator.show()
            return

        if not animated:
            self.tab_indicator.setGeometry(target)
            return

        if (
            self._tab_indicator_anim is not None
            and self._tab_indicator_anim.state() == QtCore.QAbstractAnimation.Running
        ):
            self._tab_indicator_anim.stop()

        self._tab_indicator_anim = QtCore.QPropertyAnimation(
            self.tab_indicator, b"geometry", self
        )
        self._tab_indicator_anim.setDuration(160)
        self._tab_indicator_anim.setStartValue(self.tab_indicator.geometry())
        self._tab_indicator_anim.setEndValue(target)
        self._tab_indicator_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._tab_indicator_anim.start()

    # --- DOM columns ------------------------------------------------------------

    def _create_dom_column(self, symbol: str, tab: Dict[str, Any]) -> QtWidgets.QWidget:
        column = QtWidgets.QFrame()
        column.setObjectName("DomColumn")

        layout = QtWidgets.QVBoxLayout(column)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QtWidgets.QFrame()
        header.setObjectName("DomHeader")
        h_layout = QtWidgets.QHBoxLayout(header)
        h_layout.setContentsMargins(6, 2, 6, 2)
        h_layout.setSpacing(6)

        ticker_label = QtWidgets.QLabel(symbol.upper())
        ticker_label.setObjectName("DomTickerLabel")

        h_layout.addWidget(ticker_label)
        h_layout.addStretch(1)

        header_icons = [
            ("settings", "Настройки стакана"),
            ("pin", "Закрепить стакан"),
            ("link", "Связать со стаканом"),
            ("arrows-sort", "Перестроить DOM"),
        ]
        for icon_name, tooltip in header_icons:
            btn = QtWidgets.QToolButton()
            btn.setObjectName("DomHeaderToolButton")
            btn.setAutoRaise(True)
            btn.setIcon(self._icon(icon_name))
            btn.setToolTip(tooltip)
            btn.setIconSize(QtCore.QSize(18, 18))
            h_layout.addWidget(btn)

        layout.addWidget(header)

        ladder = LadderWidget(self.backend_path, symbol, self.levels, parent=self)
        ladder.setObjectName("DomLadder")
        self.ladders.append(ladder)
        tab.setdefault("ladders", []).append(ladder)
        layout.addWidget(ladder, 1)

        # Уведомляем систему плагинов о новом стакане.
        handle = LadderHandle(self.plugin_api, symbol.upper(), ladder, header)
        self.plugin_api._notify_ladder_created(handle)
        self._ladder_handle_by_widget[ladder] = handle

        ladder.rowClicked.connect(self._on_ladder_row_clicked)

        return column

    # --- style -------------------------------------------------------------------

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
QMainWindow#TerminalWindow {
    background-color: #151515;
}

QFrame#TopBar {
    background-color: #222222;
    border-bottom: 1px solid #333333;
}
QLabel#LogoLabel {
    border-radius: 6px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                     stop:0 #252525, stop:1 #151515);
}

QTabBar#WorkspaceTabs {
    background: transparent;
}
QTabBar#WorkspaceTabs::tab {
    color: #b0b0b0;
    padding: 6px 14px;
    margin-right: 2px;
    border: none;
    border-radius: 0px;
    background-color: #202020;
}
QTabBar#WorkspaceTabs::tab:selected {
    color: #ffffff;
    background-color: #262626;
}
QTabBar#WorkspaceTabs::tab:!selected:hover {
    color: #ffffff;
    background-color: #242424;
}
QTabBar#WorkspaceTabs::close-button {
    subcontrol-position: right;
    margin-left: 6px;
}

QFrame#WorkspaceTabIndicator {
    background-color: #3b7cff;
    border-radius: 0px;
}

QToolButton#AddTabButton {
    color: #d0d0d0;
    background-color: transparent;
    border: 1px solid #333333;
    border-radius: 0px;
    padding: 4px 8px;
}
QToolButton#AddTabButton::menu-indicator {
    image: none;
}
QToolButton#AddTabButton:hover {
    color: #ffffff;
    background-color: #262626;
}

QLabel#ConnectionIndicator {
    color: #ff0da6;
    font-weight: 600;
}
QLabel#TimeLabel {
    color: #a0a0a0;
}

QFrame#SideToolbar {
    background-color: #202020;
    border-right: 1px solid #333333;
}
QToolButton#SideToolButton {
    color: #c0c0c0;
    background: transparent;
    border-radius: 8px;
    padding: 8px 0;
}
QToolButton#SideToolButton:hover {
    color: #ffffff;
    background: transparent;
}
QToolButton#SideToolButton:pressed {
    background: transparent;
}

QFrame#Workspace {
    background-color: #181818;
}

QFrame#DomColumn {
    background-color: #202020;
    border-radius: 12px;
    border: 1px solid rgba(255,13,166,0.22);
}
QFrame#DomHeader {
    background-color: #262626;
    border-radius: 10px;
}
QLabel#DomTickerLabel {
    color: #ffffff;
    font-size: 10pt;
}
QLabel#DomChangeLabel {
    color: #52e7ff;
    font-size: 8pt;
}
QToolButton#DomHeaderToolButton {
    color: #ffffff;
    background: transparent;
    border: none;
    padding: 0 4px;
}
QToolButton#DomHeaderToolButton:hover {
    color: #ffffff;
}

QLabel#LadderStatusLabel {
    color: #52e7ff;
}
QTableView {
    background: #202020;
    color: #f0f0f0;
    gridline-color: transparent;
    border: none;
}
QTableView::item {
    padding: 0px 3px;
}

QDialog#PluginsWindow {
    background-color: #212121;
}
QLabel#PluginsTitle {
    color: #ffffff;
    font-weight: 600;
}
QLabel#PluginsHint {
    color: #a0a0a0;
}
QListWidget#PluginsList {
    background-color: #181818;
    border: 1px solid #333333;
    color: #f0f0f0;
}
            """
        )

    # --- misc --------------------------------------------------------------------

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_tab_indicator(animated=False)

    def _start_time_timer(self) -> None:
        self._time_timer = QtCore.QTimer(self)
        self._time_timer.timeout.connect(self._update_time_label)
        self._time_timer.start(1000)
        self._update_time_label()

    def _update_time_label(self) -> None:
        now = QtCore.QDateTime.currentDateTimeUtc()
        self.time_label.setText(now.toString("HH:mm:ss 'UTC'"))

    def _start_ladder_timer(self) -> None:
        # Single timer to drive all ladder UI updates at a fixed FPS.
        self._ladder_timer = QtCore.QTimer(self)
        target_fps = 60
        self._ladder_timer.setInterval(max(5, int(1000 / target_fps)))
        self._ladder_timer.timeout.connect(self._on_ladder_tick)
        self._ladder_timer.start()

    def _on_ladder_tick(self) -> None:
        # Let each ladder flush its last backend snapshot to the view.
        for ladder in list(self.ladders):
            if hasattr(ladder, "flush_pending"):
                ladder.flush_pending()

    # --- plugin helpers --------------------------------------------------------

    def _register_plugin_hotkey(
        self,
        plugin_id: str,
        action_id: str,
        default_sequence: str,
        callback: Callable[[], None],
    ) -> None:
        """Создаёт QShortcut для действия плагина с учётом настроек."""
        key = (plugin_id, action_id)
        # Запоминаем метаданные действия, чтобы можно было
        # пересоздать shortcut после изменения настроек.
        self._plugin_hotkey_meta[key] = (default_sequence, callback)

        # Если shortcut уже существовал — удаляем его.
        old_shortcut = self._plugin_shortcuts.pop(key, None)
        if old_shortcut is not None:
            old_shortcut.setParent(None)

        seq_str = self.plugin_manager.config.get_hotkey(
            plugin_id, action_id, default_sequence
        )
        if not seq_str:
            return

        sequence = QtGui.QKeySequence(seq_str)
        if sequence.isEmpty():
            return

        shortcut = QtWidgets.QShortcut(sequence, self)
        shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        shortcut.activated.connect(callback)  # type: ignore[arg-type]

        self._plugin_shortcuts[key] = shortcut

    def _reload_plugin_hotkeys_from_config(self) -> None:
        """Пересоздаёт все горячие клавиши модов из конфига."""
        for shortcut in self._plugin_shortcuts.values():
            shortcut.setParent(None)
        self._plugin_shortcuts.clear()

        for (plugin_id, action_id), (default_seq, callback) in self._plugin_hotkey_meta.items():
            self._register_plugin_hotkey(plugin_id, action_id, default_seq, callback)

    @QtCore.Slot(int, float, float, float)
    def _on_ladder_row_clicked(self, row: int, price: float, bid: float, ask: float) -> None:
        sender = self.sender()
        if not isinstance(sender, LadderWidget):
            return
        handle = self._ladder_handle_by_widget.get(sender)
        if handle is None:
            return
        side = "none"
        if ask > 0 or bid > 0:
            if ask >= bid:
                side = "ask"
            else:
                side = "bid"
        self.plugin_api._notify_ladder_click(handle, row, price, side)

    def _open_plugins_window(self) -> None:
        if self._plugins_window is None:
            self._plugins_window = PluginsWindow(self.plugin_manager, parent=self)
        self._plugins_window.show()
        self._plugins_window.raise_()
        self._plugins_window.activateWindow()

    def _open_settings_window(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self, parent=self)
        # Обновляем вкладку модов перед показом на случай, если
        # во время работы были загружены новые плагины.
        if hasattr(self._settings_window, "_populate_plugins_tab"):
            self._settings_window._populate_plugins_tab()  # type: ignore[attr-defined]
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        for ladder in self.ladders:
            ladder.shutdown()
        super().closeEvent(event)
