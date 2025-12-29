from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets


class LadderHandle:
    """Обёртка над стаканом для плагинов.

    Плагин не работает напрямую с внутренними виджетами,
    а получает этот handle и через него добавляет кнопки,
    подписывается на события и т.д.
    """

    def __init__(
        self,
        api: "PluginApi",
        symbol: str,
        ladder_widget: Any,
        header_widget: QtWidgets.QWidget,
    ) -> None:
        self._api = api
        self._symbol = symbol
        self._ladder_widget = ladder_widget
        self._header_widget = header_widget

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def ladder(self) -> Any:
        """Исходный LadderWidget (DOM)."""
        return self._ladder_widget

    def add_header_button(
        self,
        icon_name: str,
        tooltip: str,
        callback: Callable[[], None],
    ) -> QtWidgets.QToolButton:
        """Добавляет кнопку в заголовок стакана."""
        btn = QtWidgets.QToolButton(self._header_widget)
        btn.setObjectName("DomHeaderToolButton")
        btn.setAutoRaise(True)
        # terminal._icon уже есть и используется по всему коду
        btn.setIcon(self._api.terminal._icon(icon_name))  # type: ignore[attr-defined]
        btn.setToolTip(tooltip)
        btn.setIconSize(QtCore.QSize(18, 18))
        btn.clicked.connect(callback)  # type: ignore[arg-type]

        layout = self._header_widget.layout()
        if isinstance(layout, QtWidgets.QBoxLayout):
            layout.addWidget(btn)
        return btn

    def add_bottom_panel(self, widget: QtWidgets.QWidget) -> None:
        """Добавляет панель в низ стакана."""
        layout = self._ladder_widget.layout()
        if isinstance(layout, QtWidgets.QBoxLayout):
            layout.addWidget(widget)


class PluginApi:
    """API объект, который ядро отдаёт плагинам.

    Пока очень простой: даёт доступ к окну терминала и логированию.
    Потом сюда можно добавить хуки для DOM, хоткеи и т.п.
    """

    def __init__(self, terminal_window: Any) -> None:
        self._terminal_window = terminal_window
        self._ladder_hooks: List[Callable[[LadderHandle], None]] = []
        self._ladder_handles: List[LadderHandle] = []
        self._ladder_click_hooks: List[Callable[[LadderHandle, int, float, str], None]] = []

    @property
    def terminal(self) -> Any:
        return self._terminal_window

    def log(self, message: str) -> None:
        # В дальнейшем можно заменить на нормальный логгер.
        print(f"[PLUGIN] {message}")

    # --- hotkeys ---------------------------------------------------------------

    def register_hotkey(
        self,
        plugin_id: str,
        action_id: str,
        default_sequence: str,
        callback: Callable[[], None],
    ) -> None:
        """Регистрирует горячую клавишу для действия плагина.

        Фактическая привязка и чтение настроек делается в окне терминала,
        сюда плагин просто передаёт желаемый дефолт.
        """
        terminal = self._terminal_window
        register = getattr(terminal, "_register_plugin_hotkey", None)
        if callable(register):
            register(plugin_id, action_id, default_sequence, callback)

    # --- ladder hooks ----------------------------------------------------------

    def register_ladder_hook(self, callback: Callable[[LadderHandle], None]) -> None:
        """Регистрирует callback, вызываемый для каждого стакана.

        callback(handle) будет вызван:
          * для уже существующих стаканов;
          * для всех новых, создаваемых после регистрации.
        """
        self._ladder_hooks.append(callback)
        for handle in self._ladder_handles:
            callback(handle)

    # внутренние методы, вызываются из ядра

    def _notify_ladder_created(self, handle: LadderHandle) -> None:
        self._ladder_handles.append(handle)
        for cb in self._ladder_hooks:
            cb(handle)

    # --- ladder click hooks ----------------------------------------------------

    def register_ladder_click_hook(
        self, callback: Callable[[LadderHandle, int, float, str], None]
    ) -> None:
        """Регистрирует callback для кликов по строкам стакана.

        callback(handle, row, price, side), где side: 'bid'/'ask'/'none'.
        """
        self._ladder_click_hooks.append(callback)

    def _notify_ladder_click(
        self, handle: LadderHandle, row: int, price: float, side: str
    ) -> None:
        for cb in self._ladder_click_hooks:
            cb(handle, row, price, side)


class PluginConfigStore:
    """Хранилище настроек плагинов (включая хоткеи)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    # --- low level -------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            text = self.path.read_text(encoding="utf-8")
            self._data = json.loads(text) or {}
        except Exception:
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, indent=2, ensure_ascii=False)
        self.path.write_text(text, encoding="utf-8")

    # --- public helpers --------------------------------------------------------

    def get_plugin(self, plugin_id: str) -> Dict[str, Any]:
        return self._data.get(plugin_id, {})

    def set_plugin_option(self, plugin_id: str, key: str, value: Any) -> None:
        plugin = self._data.setdefault(plugin_id, {})
        plugin[key] = value

    def get_hotkey(self, plugin_id: str, action_id: str, default: str) -> str:
        plugin = self._data.get(plugin_id, {})
        hotkeys = plugin.get("hotkeys", {})
        if not isinstance(hotkeys, dict):
            return default
        return str(hotkeys.get(action_id, default))

    def set_hotkey(self, plugin_id: str, action_id: str, sequence: str) -> None:
        plugin = self._data.setdefault(plugin_id, {})
        hotkeys = plugin.setdefault("hotkeys", {})
        hotkeys[action_id] = sequence


@dataclass
class PluginMeta:
    plugin_id: str
    name: str
    version: str = "0.1"
    description: str = ""
    author: str = ""
    path: Optional[Path] = None


@dataclass
class LoadedPlugin:
    meta: PluginMeta
    module: Any
    handle: Any = None
    enabled: bool = False


class PluginManager(QtCore.QObject):
    """Загрузчик и менеджер модов из каталога mods/."""

    plugins_changed = QtCore.Signal()

    def __init__(self, mods_dir: Path, api: PluginApi, parent=None) -> None:
        super().__init__(parent)
        self.mods_dir = mods_dir
        self.api = api
        self.plugins: Dict[str, LoadedPlugin] = {}
        self.mods_dir.mkdir(exist_ok=True)

        config_path = self.mods_dir.parent / "config" / "plugins.json"
        self.config = PluginConfigStore(config_path)

    # --- discovery -------------------------------------------------------------

    def discover(self) -> None:
        """Находит и загружает метаданные всех плагинов в каталоге mods/."""
        for entry in sorted(self.mods_dir.iterdir()):
            plugin_path: Optional[Path] = None
            plugin_id: Optional[str] = None

            if entry.is_file() and entry.suffix == ".py":
                plugin_path = entry
                plugin_id = entry.stem
            elif entry.is_dir():
                init_py = entry / "__init__.py"
                if init_py.exists():
                    plugin_path = init_py
                    plugin_id = entry.name

            if not plugin_path or not plugin_id:
                continue

            if plugin_id in self.plugins:
                continue

            mod = self._import_module(plugin_id, plugin_path)
            if not mod:
                continue

            meta = self._read_meta(plugin_id, plugin_path, mod)
            self.plugins[meta.plugin_id] = LoadedPlugin(meta=meta, module=mod)

        self.plugins_changed.emit()

    def _import_module(self, plugin_id: str, path: Path) -> Any:
        module_name = f"shah_mods_{plugin_id}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                self.api.log(f"Не удалось создать spec для плагина {plugin_id}")
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
            return module
        except Exception as exc:  # pragma: no cover - защитный код
            self.api.log(f"Ошибка загрузки плагина {plugin_id}: {exc}")
            return None

    def _read_meta(self, plugin_id: str, path: Path, module: Any) -> PluginMeta:
        data = getattr(module, "PLUGIN_META", {}) or {}
        if not isinstance(data, dict):
            data = {}

        pid = str(data.get("id") or plugin_id)
        name = str(data.get("name") or plugin_id)
        version = str(data.get("version") or "0.1")
        description = str(data.get("description") or "")
        author = str(data.get("author") or "")

        return PluginMeta(
            plugin_id=pid,
            name=name,
            version=version,
            description=description,
            author=author,
            path=path,
        )

    # --- enable / disable ------------------------------------------------------

    def enable_plugin(self, plugin_id: str) -> bool:
        plugin = self.plugins.get(plugin_id)
        if not plugin or plugin.enabled:
            return False

        register = getattr(plugin.module, "register", None)
        handle = None
        if callable(register):
            try:
                handle = register(self.api)
            except Exception as exc:  # pragma: no cover - защитный код
                self.api.log(f"Ошибка в register() плагина {plugin_id}: {exc}")
                return False

        plugin.handle = handle
        plugin.enabled = True
        self.plugins_changed.emit()
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        plugin = self.plugins.get(plugin_id)
        if not plugin or not plugin.enabled:
            return False

        # Плагин может определить unregister(api, handle) или unload(api, handle)
        unregister = getattr(plugin.module, "unregister", None)
        if callable(unregister):
            try:
                unregister(self.api, plugin.handle)
            except Exception as exc:  # pragma: no cover - защитный код
                self.api.log(f"Ошибка в unregister() плагина {plugin_id}: {exc}")
        else:
            unload = getattr(plugin.module, "unload", None)
            if callable(unload):
                try:
                    unload(self.api, plugin.handle)
                except Exception as exc:  # pragma: no cover
                    self.api.log(f"Ошибка в unload() плагина {plugin_id}: {exc}")

        plugin.enabled = False
        plugin.handle = None
        self.plugins_changed.emit()
        return True
