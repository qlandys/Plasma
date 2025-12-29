# app/pages/database_page.py
from __future__ import annotations
import json
import inspect
import re
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple
from PySide6.QtCore import (
    Qt, QTimer, QUrl, QSize, QPoint, QRect, QSettings,
    QEasingCurve, QPropertyAnimation, Signal, QEvent, Property
)
from PySide6.QtGui import (
    QIcon, QKeyEvent, QPainter, QColor, QPen, QMouseEvent, QWheelEvent, QFont,
    QStandardItemModel, QStandardItem, QPalette, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTabWidget, QTabBar, QMenu,
    QInputDialog, QMessageBox, QToolButton, QLineEdit,
    QFrame, QListWidget, QListWidgetItem, QAbstractItemView, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QGraphicsOpacityEffect,
    QGraphicsBlurEffect, QSizePolicy
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from qfluentwidgets import InfoBar, InfoBarPosition
# --- тема (цвета) ---
try:
    from app.theme import theme_color_hex as C, on_theme_changed
except Exception:
    def C(_key: str, default: str = "#202225") -> str:
        return default
    def on_theme_changed(_):
        return
def _rgba_hex(hex_color: str, a: float) -> str:
    """#RRGGBB -> rgba(r,g,b,a) with 0..1 alpha"""
    s = hex_color.strip()
    if s.startswith("#"): s = s[1:]
    if len(s) == 6:
        r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16)
        return f"rgba({r},{g},{b},{a:.3f})"
    return f"rgba(0,0,0,{a:.3f})"
# --- бэкенд парсера (заглушка окей) ---
try:
    from backend.parser import parse_coin_in_process
except Exception:
    def parse_coin_in_process(name: str, headless=True):
        return {"name": name.upper(), "spot": [], "futures": []}
# ---------------- backend (реальный или заглушка) ----------------
try:
    from backend.database_sqlite import Database, Coin
except Exception:
    @dataclass
    class Coin:
        name: str
        spot_exchanges: str
        futures_exchanges: str
        favorite: bool = False
        note: str = ""
    class Database:
        PROFILES_DIR = "profiles"
        def __init__(self, profile_name="default"): self.profile_name = profile_name
        def search_coins(self): return []
        def save_coin(self, *a, **k): pass
        def set_favorite(self, *a, **k): pass
        def close(self): pass
        def delete_profile(self): return True
        def rename_profile(self, *_a, **_k): pass
        @classmethod
        def list_profiles(cls): return ["default"]
# ---------------- пути к ассетам ----------------
APP_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = APP_DIR / "assets"
ICONS_DIR  = ASSETS_DIR / "icons"
COMMON_DIR = ICONS_DIR / "common"
ANIM_DIR   = ICONS_DIR / "animated"
LOTTIE_DIR = ICONS_DIR / "lottie"
SVG_PLUS        = COMMON_DIR / "plus.svg"
SVG_CLOSE       = COMMON_DIR / "close.svg"
SVG_CLOSE_WHITE = COMMON_DIR / "close_white.svg"
ANIM_PROFILE_IN = ANIM_DIR / "profile_in.json"
ANIM_RELOAD     = ANIM_DIR / "reload_loop.json"
BOOKMARK_JSON   = ANIM_DIR / "favorite.json"
LOTTIE_JS       = LOTTIE_DIR / "lottie.min.js"
def _qicon(path: Path) -> QIcon:
    return QIcon(str(path)) if path.exists() else QApplication.style().standardIcon(
        QApplication.style().SP_FileIcon
    )
def _lottie_js_url() -> str:
    if LOTTIE_JS.exists():
        return QUrl.fromLocalFile(str(LOTTIE_JS)).toString()
    return "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.7.1/lottie.min.js"
_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  html,body { margin:0; padding:0; background:transparent; overflow:hidden; }
  #c { width:__W__px; height:__H__px; background:transparent; }
  svg { background: transparent !important; }
</style>
</head>
<body>
<div id="c"></div>
<script src="__JS__"></script>
<script>
(function(){
  const el = document.getElementById('c');
  const animData = __JSON__;
  const A = lottie.loadAnimation({
    container: el, renderer:'svg', loop:false, autoplay:false, animationData: animData
  });
  window._lottie = A;
  window.play_once = function(){ A.goToAndStop(0,true); A.play(); }
  const firstFrame = (animData.ip !== undefined ? animData.ip : 0) || 0;
  const lastFrame  = (animData.op !== undefined ? animData.op - 1 : (A.totalFrames || 1) - 1) || firstFrame;
  const offFrame = firstFrame;
  const onFrame  = lastFrame;
  let favHandler = null;
  function stopHandler(){
    if(favHandler){ A.removeEventListener('complete', favHandler); favHandler = null; }
  }
  function renderStill(frame){
    if(!A) return;
    A.goToAndStop(frame, true);
    if(A.renderer && typeof A.renderer.renderFrame === 'function'){
      A.renderer.renderFrame();
    }
  }
  window.fav_set = function(on){
    if(!A) return;
    stopHandler();
    A.loop = false;
    renderStill(on ? onFrame : offFrame);
  }
  window.fav_animate = function(on){
    if(!A) return;
    stopHandler();
    const start = on ? offFrame : onFrame;
    const end   = on ? onFrame  : offFrame;
    const forward = start <= end;
    const seg = [start, end];
    A.loop = false;
    A.setDirection(forward ? 1 : -1);
    renderStill(start);
    A.playSegments(seg, true);
    favHandler = function(){
      stopHandler();
      A.goToAndStop(end, true);
    };
    A.addEventListener('complete', favHandler);
  }
  A.addEventListener('DOMLoaded', function(){
    renderStill(offFrame);
  });
})();
</script>
</body>
</html>
"""
def _build_lottie_html(size: int, json_data: dict) -> str:
    return (_HTML
            .replace("__W__", str(size))
            .replace("__H__", str(size))
            .replace("__JS__", _lottie_js_url())
            .replace("__JSON__", json.dumps(json_data, ensure_ascii=False))
            )
class SafeLottie(QWebEngineView):
    """Безопасный QWebEngineView с флагом готовности и без таймеров на сам объект."""
    readyChanged = Signal(bool)
    def __init__(self, json_path: Path, size: int, parent: QWidget | None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.page().setBackgroundColor(Qt.transparent)
        self._ready = False
        try:
            j = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except Exception:
            j = {}
        self.loadFinished.connect(self._on_loaded)
        self.setHtml(_build_lottie_html(size, j), baseUrl=QUrl.fromLocalFile(str(ASSETS_DIR)))
    def _on_loaded(self, _ok: bool):
        if self._ready: return
        self._ready = True
        self.readyChanged.emit(True)
    @property
    def isReady(self) -> bool:
        return self._ready
# favourite (сердце)
class BookmarkIconWidget(QWidget):
    def __init__(self, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = False
        self._outline = QColor('#FFFFFF')
        self._fill = QColor('#FF6B00')
    def set_state(self, on: bool):
        self._state = bool(on)
        self.update()
    def set_colors(self, outline: str, fill: str):
        self._outline = QColor(outline) if outline else QColor('#FFFFFF')
        self._fill = QColor(fill) if fill else QColor('#FF6B00')
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        pen_width = max(1, int(rect.height() * 0.18))
        inner = rect.adjusted(pen_width / 2, pen_width / 2, -pen_width / 2, -pen_width / 2)
        notch = inner.height() * 0.35
        path = QPainterPath()
        path.moveTo(inner.left(), inner.top())
        path.lineTo(inner.right(), inner.top())
        path.lineTo(inner.right(), inner.bottom() - notch)
        path.lineTo(inner.center().x(), inner.bottom())
        path.lineTo(inner.left(), inner.bottom() - notch)
        path.closeSubpath()
        pen = QPen(self._outline)
        pen.setWidth(max(1, int(pen_width)))
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QColor(self._fill) if self._state else Qt.NoBrush)
        painter.drawPath(path)
class FavoriteIcon(SafeLottie):
    FRAME_OFF = 210
    FRAME_ON = 269
    def __init__(self, size: int, parent: QWidget | None = None, initial: bool = False):
        path = BOOKMARK_JSON if BOOKMARK_JSON.exists() else ANIM_PROFILE_IN
        super().__init__(path, size, parent)
        self._pending_state = initial
        self.readyChanged.connect(self._on_ready)
    def _on_ready(self, ready: bool):
        if ready:
            self.set_state(self._pending_state)
    def set_state(self, on: bool):
        self._pending_state = bool(on)
        if not self.isReady:
            return
        frame = self.FRAME_ON if self._pending_state else self.FRAME_OFF
        js = (
            "if (window._lottie) {"
            f"window._lottie.goToAndStop({frame}, true);"
            "if (window._lottie.renderer && window._lottie.renderer.renderFrame) {"
            "window._lottie.renderer.renderFrame();"
            "}"
            "}"
        )
        self.page().runJavaScript(js)
class TickerCell(QWidget):
    toggled = Signal(bool)
    def __init__(self, name: str, favorite: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("TickerCell")
        self.setMouseTracking(True)
        self._raw_text = ""
        self._selected = False
        self._state = bool(favorite)
        self._table_ref: weakref.ReferenceType[QTableWidget] | None = None
        self._table_obj: QTableWidget | None = None
        self._sel_model = None
        self._row = -1
        self._col = -1
        self._icon_size = 18
        self._text_color_normal = C("text", "#EDEBEB")
        self._text_color_selected = C("text", "#EDEBEB")
        self._outline_color_base = self._text_color_normal
        self._fill_color_base = C("accent", "#00E0FF")
        self._icon = FavoriteIcon(self._icon_size, self, favorite)
        self._label = QLabel(self)
        self._label.setFocusPolicy(Qt.NoFocus)
        self._label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._label.setWordWrap(False)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)
        layout.addWidget(self._label, 1)
        self.set_name(name)
        self._apply_text_color()
        self._update_icon()
    def set_name(self, name: str):
        self._raw_text = name or ""
        self._label.setToolTip(self._raw_text)
        self._update_label()
    def set_favorite(self, on: bool):
        self._state = bool(on)
        self._update_icon()
    def is_favorite_ready(self) -> bool:
        return True
    def on_favorite_ready(self, callback):
        QTimer.singleShot(0, callback)
    def set_text_palette(self, normal_text: str, selected_text: str):
        self._text_color_normal = normal_text
        self._text_color_selected = selected_text
        self._apply_text_color()
    def set_icon_colors(self, outline_color: str, fill_color: str):
        if outline_color:
            self._outline_color_base = outline_color
        if fill_color:
            self._fill_color_base = fill_color
        self._apply_text_color()
    def bind_selection(self, table: QTableWidget, row: int, col: int):
        self._table_ref = weakref.ref(table)
        self._table_obj = table
        self._row = row
        self._col = col
        table.itemSelectionChanged.connect(self._handle_selection)
        sel_model = table.selectionModel()
        if sel_model:
            self._sel_model = sel_model
            sel_model.selectionChanged.connect(self._on_selection_changed)
        self._handle_selection()
    def toggle(self):
        self._state = not self._state
        self._update_icon()
        self.toggled.emit(self._state)
    def _on_selection_changed(self, *_):
        self._handle_selection()
    def _handle_selection(self):
        table = self._table_ref() if self._table_ref else None
        if table is None:
            return
        if self._row < 0 or self._row >= table.rowCount():
            selected = False
        else:
            sel_model = table.selectionModel()
            if sel_model:
                idx = table.model().index(self._row, self._col)
                selected = sel_model.isSelected(idx)
            else:
                item = table.item(self._row, self._col)
                selected = bool(item and item.isSelected())
        if selected != self._selected:
            self._selected = selected
            self._update_selection_style()
    def _cleanup_connections(self, *_):
        table = self._table_obj
        if table is not None:
            try:
                table.itemSelectionChanged.disconnect(self._handle_selection)
            except Exception:
                pass
        if self._sel_model is not None:
            try:
                self._sel_model.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:
                pass
        self._table_obj = None
        self._sel_model = None
    def _apply_text_color(self):
        color = self._text_color_selected if self._selected else self._text_color_normal
        self._label.setStyleSheet(f"color:{color}; border:none; background:transparent;")
        # Lottie окраску управляет сам; при желании можно использовать outline_color_base
        self._update_icon()
    def _update_icon(self):
        self._icon.set_state(self._state)
    def _update_selection_style(self):
        self._apply_text_color()
    def _update_label(self):
        metrics = self._label.fontMetrics()
        width = max(0, self._label.width())
        text = self._raw_text
        if width:
            text = metrics.elidedText(text, Qt.ElideRight, width)
        self._label.setText(text)
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._update_label)
class LottieIcon(SafeLottie):
    def __init__(self, size: int, parent: QWidget | None):
        super().__init__(ANIM_PROFILE_IN, size, parent)
        self.readyChanged.connect(self.play_once_safe)
    def play_once_safe(self, _=True):
        if not self.isReady: return
        try:
            self.page().runJavaScript("window.play_once && window.play_once();")
        except RuntimeError:
            pass
# ---------------- делегат: обрезка длинных бирж ----------------
class ElideDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.State_HasFocus
        opt.displayAlignment = Qt.AlignVCenter | Qt.AlignLeft
        if index.column() in (ProfileView.COL_SPOT, ProfileView.COL_FUT):
            opt.textElideMode = Qt.ElideRight
            opt.text = opt.fontMetrics.elidedText(opt.text, Qt.ElideRight, opt.rect.width() - 8)
        QApplication.style().drawControl(QStyle.CE_ItemViewItem, opt, painter)
# ---------------- комбобокс с чекбоксами ----------------
class CheckableCombo(QComboBox):
    changed = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.view().setMinimumWidth(260)
        self.setEditable(False)
        self.view().pressed.connect(self._on_pressed)
        self._all_caption = "Выбрать всё"
    def set_items(self, names: List[str]):
        m: QStandardItemModel = self.model()  # type: ignore
        m.clear()
        # "Выбрать всё"
        it_all = QStandardItem(self._all_caption)
        it_all.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        it_all.setData(Qt.Unchecked, Qt.CheckStateRole)
        m.appendRow(it_all)
        for n in names:
            it = QStandardItem(n)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setData(Qt.Unchecked, Qt.CheckStateRole)
            m.appendRow(it)
        self._refresh_placeholder()
    def _on_pressed(self, idx):
        m: QStandardItemModel = self.model()  # type: ignore
        it: QStandardItem = m.itemFromIndex(idx)
        if it.text() == self._all_caption:
            # toggle all
            new_state = Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked
            for i in range(m.rowCount()):
                m.item(i).setCheckState(new_state)
        else:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
            # синхронизация «Выбрать всё»
            states = [m.item(i).checkState() for i in range(1, m.rowCount())]
            m.item(0).setCheckState(Qt.Checked if all(s == Qt.Checked for s in states) else Qt.Unchecked)
        self._refresh_placeholder()
        self.changed.emit()
    def checked(self) -> List[str]:
        m: QStandardItemModel = self.model()  # type: ignore
        out = []
        for i in range(1, m.rowCount()):
            it = m.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return out
    def _refresh_placeholder(self):
        sel = self.checked()
        self.setCurrentText("Биржи…" if not sel else ", ".join(sel[:3]) + (f" (+{len(sel)-3})" if len(sel) > 3 else ""))
# ---------------- правая кнопка «крестик» ----------------
class CloseButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(18, 18)
        self.setIconSize(QSize(14, 14))
        self._icon_normal = _qicon(SVG_CLOSE)
        self._icon_hover  = _qicon(SVG_CLOSE_WHITE)
        self.setIcon(self._icon_normal)
        self.setStyleSheet("""
            QToolButton{border:none; background:transparent; padding:0; border-radius:0;}
            QToolButton:hover{background: rgba(255,255,255,0.06);}
        """)
    def enterEvent(self, e): self.setIcon(self._icon_hover);  super().enterEvent(e)
    def leaveEvent(self, e): self.setIcon(self._icon_normal); super().leaveEvent(e)
# ---------------- хост для лотти/крестика (ровно по центру) ----------------
class SideHost(QWidget):
    def __init__(self, child: QWidget, left_gap: int, right_gap: int, tab_height: int, parent=None):
        super().__init__(parent)
        self.child = child; self.lgap = left_gap; self.rgap = right_gap; self.tab_h = tab_height
        child.setParent(self); self.setFixedHeight(tab_height)
        QTimer.singleShot(0, self._apply_geometry)
    def sizeHint(self) -> QSize:
        w = self.lgap + (self.child.width() or self.child.sizeHint().width() or 16) + self.rgap
        return QSize(w, self.tab_h)
    def _apply_geometry(self):
        ch = self.child.height() or self.child.sizeHint().height() or 16
        cw = self.child.width()  or self.child.sizeHint().width()  or 16
        y = max(0, (self.tab_h - ch) // 2)
        self.child.move(self.lgap, y)
        self.child.show()
        self.child.raise_()
        self.setFixedSize(self.lgap + cw + self.rgap, self.tab_h)
    def resizeEvent(self, e): super().resizeEvent(e); self._apply_geometry()
# ---------------- FX underline + ripple --------------------
class SweepRippleFx(QWidget):
    def __init__(self, tabbar: 'HardSeparatorsTabBar'):
        super().__init__(tabbar)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.bar = tabbar
        self._cur_left  = 0.0
        self._cur_width = 0.0
        self._sweep = 1.0
        self.anim_sweep = QPropertyAnimation(self, b"sweep")
        self.anim_sweep.setDuration(200)
        self.anim_sweep.setEasingCurve(QEasingCurve.InOutCubic)
        self._ripples: List[Tuple[QPoint, float, float]] = []
    def getSweep(self): return self._sweep
    def setSweep(self, v: float): self._sweep = v; self.update()
    sweep = Property(float, getSweep, setSweep)
    def set_target(self, rect: QRect):
        self._cur_left  = float(rect.left())
        self._cur_width = float(rect.width())
    def start_sweep(self):
        self.anim_sweep.stop()
        self.anim_sweep.setStartValue(0.0)
        self.anim_sweep.setEndValue(1.0)
        self.anim_sweep.start()
    def add_ripple(self, center: QPoint):
        self._ripples.append((center, 0.0, 0.35))
        self._tick_ripple()
    def clear_all(self):
        self.anim_sweep.stop()
        self._ripples.clear()
        self.update()
    def _tick_ripple(self):
        if not self._ripples: return
        new=[]
        for c,r,a in self._ripples:
            r2=min(22.0, r+6.0); a2=max(0.0, a-0.07)
            if a2>0.02: new.append((c,r2,a2))
        self._ripples=new; self.update()
        if self._ripples: QTimer.singleShot(16, self._tick_ripple)
    def paintEvent(self, _):
        if self.bar.count() == 0 or self.bar.currentIndex() < 0:
            return
        accent = QColor(C("accent", "#00E0FF"))
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, False)
        h=self.height(); y=h-2; x=int(self._cur_left); w=int(self._cur_width*self._sweep)
        pen=QPen(accent); pen.setWidth(3); pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen); p.drawLine(x, y, x+max(0,w), y)
        if p.isActive(): p.end()
# ---------------- Попап профилей ---------------------------------------------
class ProfilesPanel(QFrame):
    createRequested = Signal()
    profileRequested = Signal(str)
    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("ProfilesPanel")
        bg = _rgba_hex(C('bg2', '#1d2127'), 0.92)
        self.setStyleSheet(f"""
        QFrame#ProfilesPanel {{
            background: {bg};
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 8px;
        }}
        QListWidget {{
            background: transparent;
            border: none;
            color: {C('text','#E6EAED')};
            font-size: 12px;
            outline: none;
        }}
        QListWidget::item {{ padding: 6px 10px; }}
        QListWidget::item:selected {{ background: {_rgba_hex(C('accent','#00E0FF'),0.18)}; }}
        """)
        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemClicked.connect(self._on_item)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6); lay.addWidget(self.list)
    def rebuild(self, names: List[str]):
        self.list.clear()
        it0 = QListWidgetItem("Создать новый профиль…"); it0.setData(Qt.UserRole, "__create__")
        self.list.addItem(it0)
        self.list.addItem(QListWidgetItem())
        for n in names:
            it = QListWidgetItem(n); it.setData(Qt.UserRole, n); self.list.addItem(it)
        self.list.setMinimumWidth(220); self.list.setMaximumWidth(300)
        self.list.setMinimumHeight(min(360, 32*len(names)+64))
    def _on_item(self, it: QListWidgetItem):
        v = it.data(Qt.UserRole)
        if v == "__create__": self.createRequested.emit()
        elif isinstance(v, str): self.profileRequested.emit(v)
    def showNear(self, anchor: QWidget):
        self.adjustSize()
        br = anchor.mapToGlobal(anchor.rect().bottomRight())
        geo = self.frameGeometry()
        x = br.x() - geo.width() + anchor.width()
        y = br.y() + 6
        self.move(x, y); self.show()
# ---------------- TabBar ------------------------------------------------------
class HardSeparatorsTabBar(QTabBar):
    inlineRenameRequested = Signal(int, QRect)
    TAB_H = 36
    LEFT_ICON_W = 20
    GAP_BETWEEN_TABS = 0
    LEFT_EDGE_GAP = 10
    LEFT_AFTER_ICON = 6
    RIGHT_BEFORE_CLOSE = 6
    RIGHT_EDGE_GAP = 2
    CLOSE_W = 18
    ELIDE_THRESHOLD = 160
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HardSeparatorsTabBar")
        self.setDrawBase(False)
        self.setElideMode(Qt.ElideNone)
        self.setMovable(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setDocumentMode(True)
        self._dragging = False
        self._press_pos = QPoint()
        self.fx = SweepRippleFx(self); self.fx.setGeometry(self.rect())
        self.currentChanged.connect(self._on_current_changed)
        self.tabMoved.connect(lambda *_: QTimer.singleShot(0, self._after_layout_change))
        # прямые углы, ровные линии
        self.setStyleSheet(f"""
        QTabBar#HardSeparatorsTabBar {{
            background: transparent; color:{C('text','#E6EAED')};
            margin:0; padding:0;
        }}
        QTabBar#HardSeparatorsTabBar::tab {{
            background: transparent;
            margin-right: {self.GAP_BETWEEN_TABS}px;
            min-height: {self.TAB_H}px; max-height:{self.TAB_H}px;
            padding-top: 0px; padding-bottom: 0px;
            padding-left: {self.LEFT_AFTER_ICON}px;
            padding-right: {self.RIGHT_BEFORE_CLOSE + self.RIGHT_EDGE_GAP}px;
            border-right:1px solid rgba(255,255,255,0.08);
            border-bottom:1px solid rgba(255,255,255,0.06);
            font-size: 12px;
            border-radius: 0;
        }}
        QTabBar#HardSeparatorsTabBar::tab:selected {{
            background: {_rgba_hex(C('accent','#00E0FF'),0.08)};
            color:{C('text','#FFFFFF')};
        }}
        QTabBar#HardSeparatorsTabBar::tab:hover {{
            background: {_rgba_hex(C('accent','#00E0FF'),0.12)};
        }}
        """)
        self._external_plus: Optional[QToolButton] = None
    def set_external_plus(self, btn: QToolButton):
        self._external_plus = btn
    def sizeHint(self) -> QSize: return QSize(0, self.TAB_H)
    def minimumSizeHint(self) -> QSize: return QSize(0, self.TAB_H)
    def _raise_side_hosts(self):
        self.fx.lower()
        for i in range(self.count()):
            for side in (QTabBar.LeftSide, QTabBar.RightSide):
                host = self.tabButton(i, side)
                if isinstance(host, QWidget):
                    host.raise_()
                    child = getattr(host, "child", None)
                    if isinstance(child, QWidget):
                        child.raise_()
    def paintEvent(self, e):
        super().paintEvent(e)
        # вертикальная перегородка справа — у самого края таббара
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(255, 255, 255, 38)); pen.setWidth(1); p.setPen(pen)
        x = self.width() - 1; p.drawLine(x, 0, x, self.height())
        if p.isActive(): p.end()
    def tabLayoutChange(self):
        super().tabLayoutChange()
        QTimer.singleShot(0, self._after_layout_change)
    def _after_layout_change(self):
        self._recalc_elide()
        self._sync_fx_to_current()
        self._raise_side_hosts()
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fx.setGeometry(self.rect())
        self._after_layout_change()
    def _recalc_elide(self):
        cnt = self.count()
        if cnt <= 0:
            if self.elideMode() != Qt.ElideNone:
                self.setElideMode(Qt.ElideNone)
            return
        avail = max(0, self.width())
        avg = avail / float(cnt)
        want = Qt.ElideRight if avg < self.ELIDE_THRESHOLD else Qt.ElideNone
        if self.elideMode() != want:
            self.setElideMode(want); self.update()
    def tabInserted(self, index: int):
        super().tabInserted(index)
        lottie = LottieIcon(self.LEFT_ICON_W, self)
        left_host = SideHost(lottie, self.LEFT_EDGE_GAP, self.LEFT_AFTER_ICON, self.TAB_H, self)
        self.setTabButton(index, QTabBar.LeftSide, left_host)
        close_btn = CloseButton(self)
        close_host = SideHost(close_btn, self.RIGHT_BEFORE_CLOSE, self.RIGHT_EDGE_GAP, self.TAB_H, self)
        self.setTabButton(index, QTabBar.RightSide, close_host)
        close_btn.clicked.connect(lambda _=False, i=index: self._close_by_button(close_btn))
        QTimer.singleShot(0, lottie.play_once_safe)
        QTimer.singleShot(0, self._after_layout_change)
    def tabRemoved(self, index: int):
        super().tabRemoved(index)
        QTimer.singleShot(0, self._after_layout_change)
    def _close_by_button(self, btn: QToolButton):
        for i in range(self.count()):
            host = self.tabButton(i, QTabBar.RightSide)
            if isinstance(host, SideHost) and host.child is btn:
                tw: QTabWidget = self.parent()  # type: ignore
                if hasattr(tw, "parent") and hasattr(tw.parent(), "close_profile"):
                    tw.parent().close_profile(i)  # type: ignore
                break
    def _play_current_icon(self, idx: int):
        if self._dragging:  # не проигрываем иконку во время drag
            return
        host = self.tabButton(idx, QTabBar.LeftSide)
        if isinstance(host, SideHost):
            ic = host.child
            if isinstance(ic, LottieIcon): ic.play_once_safe()
    def _begin_drag(self):
        if self._dragging: return
        self._dragging = True
        self._set_hosts_visible(False)
        self.fx.clear_all()
        self.fx.setVisible(False)
    def _end_drag(self):
        if not self._dragging: return
        self._dragging = False
        self._set_hosts_visible(True)
        self.fx.set_target(self.tabRect(self.currentIndex()))
        self.fx.setSweep(1.0)
        self.fx.setVisible(True)
        self._raise_side_hosts()
    def _set_hosts_visible(self, visible: bool):
        for i in range(self.count()):
            for side in (QTabBar.LeftSide, QTabBar.RightSide):
                host = self.tabButton(i, side)
                if isinstance(host, SideHost): host.setVisible(visible)
    def mousePressEvent(self, e: QMouseEvent):
        if e.buttons() & Qt.LeftButton and not self._dragging:
            pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
            self.fx.add_ripple(pos)
        self._press_pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        super().mousePressEvent(e)
    def mouseMoveEvent(self, e: QMouseEvent):
        if not self._dragging and (e.buttons() & Qt.LeftButton):
            cur = e.position().toPoint() if hasattr(e, "position") else e.pos()
            if (self._press_pos - cur).manhattanLength() >= QApplication.startDragDistance():
                self._begin_drag()
        super().mouseMoveEvent(e)
    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MiddleButton:
            idx = self.tabAt(e.pos())
            if idx >= 0:
                tw: QTabWidget = self.parent()  # type: ignore
                if hasattr(tw, "parent") and hasattr(tw.parent(), "close_profile"):
                    tw.parent().close_profile(idx)  # type: ignore
                return
        super().mouseReleaseEvent(e)
        self._end_drag()
    def wheelEvent(self, e: QWheelEvent):
        if self.count() <= 0: return
        delta = e.angleDelta().y() or e.angleDelta().x()
        step = -1 if delta < 0 else 1
        i = (self.currentIndex() + step) % self.count()
        self.setCurrentIndex(i); e.accept()
    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            idx = self.tabAt(e.pos())
            if idx >= 0:
                rect = self._text_rect_for_index(idx)
                self.inlineRenameRequested.emit(idx, rect)
                return
        e.ignore()
    def _text_rect_for_index(self, idx: int) -> QRect:
        r = self.tabRect(idx)
        left = r.left() + self.LEFT_EDGE_GAP + self.LEFT_ICON_W + self.LEFT_AFTER_ICON
        right_pad = self.RIGHT_BEFORE_CLOSE + self.RIGHT_EDGE_GAP + self.CLOSE_W
        return QRect(left, r.top(), max(30, r.width() - (left - r.left()) - right_pad), r.height())
    def _on_current_changed(self, idx: int):
        if idx < 0: return
        rect = self.tabRect(idx)
        self.fx.set_target(rect)
        if self._dragging:
            self.fx.setSweep(1.0); self.fx.update()
        else:
            self.fx.start_sweep()
            self._play_current_icon(idx)
    def _sync_fx_to_current(self):
        idx = self.currentIndex()
        if idx < 0: return
        self.fx.set_target(self.tabRect(idx)); self.fx.update()
# ---------------- утилиты для бэкенда ----------------
def _safe_db_rename(db_obj, old: str, new: str):
    if hasattr(db_obj, "rename_profile"):
        fn = getattr(db_obj, "rename_profile")
        try:
            if len(inspect.signature(fn).parameters) == 1:
                return fn(new)  # type: ignore
        except Exception:
            pass
        try:
            return fn(old, new)  # type: ignore
        except Exception:
            pass
    if hasattr(Database, "rename_profile"):
        try: return Database.rename_profile(old, new)  # type: ignore
        except Exception: pass
    raise RuntimeError("rename_profile: неподдерживаемая сигнатура backend'а")
def _safe_db_delete(db_obj, name: str) -> bool:
    if hasattr(db_obj, "delete_profile"):
        fn = getattr(db_obj, "delete_profile")
        for try_fn in (lambda: fn(), lambda: fn(name)):
            try:
                res = try_fn()
                return bool(res) if res is not None else True
            except Exception:
                pass
    if hasattr(Database, "delete_profile"):
        try:
            res = Database.delete_profile(name)  # type: ignore
            return bool(res) if res is not None else True
        except Exception:
            pass
    return False
# ---------------- Оверлей перезагрузки ----------------
class ReloadOverlay(QWidget):
    def __init__(self, table: QTableWidget):
        super().__init__(table)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self._table = table
        self._viewport = table.viewport()
        self._viewport.installEventFilter(self)
        table.verticalScrollBar().valueChanged.connect(self._sync_geometry)
        table.horizontalScrollBar().valueChanged.connect(self._sync_geometry)
        self._depth = 0
        self._prev_effect = None
        self._blur_fx: QGraphicsBlurEffect | None = None
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_fx)
        self._fade_anim: QPropertyAnimation | None = None
        self.spinner = SafeLottie(ANIM_RELOAD, 56, self)
        self.spinner.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.spinner.readyChanged.connect(lambda *_: self._spin())
        self.apply_theme_now()
        on_theme_changed(self.apply_theme_now)
        self._sync_geometry()
    def eventFilter(self, obj, ev):
        if obj is self._viewport and ev.type() == QEvent.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, ev)
    def _sync_geometry(self):
        vp_rect = self._viewport.geometry()
        self.setGeometry(vp_rect)
        if self.spinner:
            x = max(0, (self.width() - self.spinner.width()) // 2)
            y = max(0, (self.height() - self.spinner.height()) // 2)
            self.spinner.move(x, y)
            self.spinner.raise_()
    def _spin(self):
        if not self.spinner.isReady:
            return
        try:
            self.spinner.page().runJavaScript("window.spin && window.spin();")
        except RuntimeError:
            pass
    def _animate_opacity(self, target: float, on_done=None):
        if self._fade_anim:
            self._fade_anim.stop()
        anim = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(self._opacity_fx.opacity())
        anim.setEndValue(target)
        if on_done:
            anim.finished.connect(on_done)
        anim.finished.connect(lambda: setattr(self, "_fade_anim", None))
        anim.start()
        self._fade_anim = anim
    def apply_theme_now(self):
        self.setStyleSheet(f"background:{_rgba_hex(C('bg0','#121417'),0.32)};")
    def start(self):
        self._depth += 1
        if self._depth > 1:
            self._spin()
            return
        self._prev_effect = self._viewport.graphicsEffect()
        blur = QGraphicsBlurEffect(self._viewport)
        blur.setBlurRadius(6.0)
        self._viewport.setGraphicsEffect(blur)
        self._blur_fx = blur
        self._sync_geometry()
        self.setVisible(True)
        self.raise_()
        self.spinner.show()
        self.spinner.raise_()
        self._animate_opacity(1.0)
        self._spin()
    def stop(self):
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth > 0:
            return
        def _finish():
            if self._viewport.graphicsEffect() is self._blur_fx:
                self._viewport.setGraphicsEffect(self._prev_effect)
            self._prev_effect = None
            self._blur_fx = None
            self._opacity_fx.setOpacity(0.0)
            self.setVisible(False)
        self._animate_opacity(0.0, _finish)
# ---------------- Контент профиля ----------------
class ProfileView(QWidget):
    COL_NAME = 0
    COL_SPOT = 1
    COL_FUT  = 2
    def __init__(self, profile_name: str, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.db = Database(profile_name)
        self._coins: List[Coin] = []
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._build_ui()
        self.reload_from_db()
    def eventFilter(self, obj, ev):
        if obj in (self.table.viewport(), self.table.horizontalHeader()) and ev.type() == QEvent.Resize:
            self._fit_columns()
        return super().eventFilter(obj, ev)
    # ---------- UI ----------
    def _build_ui(self):
        BG0 = C("bg0", "#121417"); BG1 = C("bg1", "#171A1E")
        OUT = C("outline", "#2a2f36"); TEXT = C("text", "#EDEBEB")
        ACC = C("accent", "#00E0FF"); SUB = C("subtext", "#B7B3B3")
        self._col_basis = (160, 420, 420)
        self._col_min = (140, 280, 280)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(8)
        # ----- Панель парсера -----
        parserBar = QFrame(self, objectName="parserBar")
        pL = QHBoxLayout(parserBar); pL.setContentsMargins(12, 10, 12, 10); pL.setSpacing(8)
        self.edCoins = QLineEdit(placeholderText="Введите монеты через запятую (пример: BTC, ETH, SOL)")
        self.edCoins.setMinimumWidth(320)
        self.cbHeadless = QCheckBox("Headless"); self.cbHeadless.setChecked(True)
        self.spinWorkers = QSpinBox(); self.spinWorkers.setRange(1, 8); self.spinWorkers.setValue(2)
        self.btnScan = QPushButton("Scan"); self.btnStop = QPushButton("Stop")
        self.btnScan.setCursor(Qt.PointingHandCursor); self.btnStop.setCursor(Qt.PointingHandCursor)
        self.pb = QProgressBar(); self.pb.setFixedWidth(60); self.pb.setRange(0, 100); self.pb.setValue(0)
        pL.addWidget(self.edCoins, 1)
        pL.addWidget(self.cbHeadless); pL.addWidget(QLabel("Workers:")); pL.addWidget(self.spinWorkers)
        pL.addWidget(self.btnScan); pL.addWidget(self.btnStop); pL.addWidget(self.pb)
        parserBar.setStyleSheet(f"""
            QFrame#parserBar {{
                background:{BG1}; border:1px solid {OUT}; border-radius:0;
            }}
            QLineEdit {{ background:{BG0}; color:{TEXT}; border:1px solid {OUT};
                        border-radius:0; padding:6px 10px; }}
            QPushButton {{ background:{BG0}; color:{TEXT}; border:1px solid {OUT};
                          border-radius:0; padding:6px 12px; font-weight:600; }}
            QPushButton:hover {{ background: {_rgba_hex(ACC,0.10)}; }}
            QCheckBox, QLabel {{ color:{TEXT}; }}
            QProgressBar {{ background:{BG0}; color:{TEXT}; border:1px solid {OUT};
                            border-radius:0; text-align:center; }}
            QProgressBar::chunk {{ background:{ACC}; margin:0; }}
        """)
        root.addWidget(parserBar)
        # Enter запускает Scan
        self.edCoins.returnPressed.connect(self.btnScan.click)
        # ----- Панель фильтров -----
        filterBar = QFrame(self, objectName="filterBar")
        fL = QHBoxLayout(filterBar); fL.setContentsMargins(12, 10, 12, 10); fL.setSpacing(8)
        lbl = QLabel("Фильтр:"); lbl.setStyleSheet(f"color:{TEXT};")
        self.edSearch = QLineEdit(placeholderText="Поиск по названию…")
        self.cmbType = QComboBox(); self.cmbType.addItems(["Все", "Спот", "Фьючерсы"])
        self.cmbExch = CheckableCombo()
        self.cbOnlySel = QCheckBox("Только выбранные биржи")
        self.cbFav = QCheckBox("Только избранное")
        for w in (lbl, self.edSearch, self.cmbType, self.cmbExch, self.cbOnlySel, self.cbFav):
            fL.addWidget(w)
        fL.insertStretch(100, 1)
        filterBar.setStyleSheet(f"""
            QFrame#filterBar {{
                background:{BG1}; border:1px solid {OUT}; border-radius:0;
            }}
            QLineEdit {{ background:{BG0}; color:{TEXT}; border:1px solid {OUT};
                        border-radius:0; padding:6px 10px; }}
            QComboBox {{ background:{BG0}; color:{TEXT}; border:1px solid {OUT};
                         border-radius:0; padding:6px 10px; min-width:180px; }}
            QCheckBox {{ color:{TEXT}; }}
        """)
        root.addWidget(filterBar)
        # ----- Таблица -----
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Монета", "Спотовые биржи", "Фьючерсные биржи"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setItemDelegate(ElideDelegate(self.table))
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        hdr.setSectionsMovable(False)
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(36)
        model = self.table.model()
        if hasattr(model, "setSortRole"):
            model.setSortRole(Qt.UserRole)
        self._apply_table_theme()
        on_theme_changed(self._apply_table_theme)
        root.addWidget(self.table, 1)
        # Оверлей перезагрузки
        self.overlay = ReloadOverlay(self.table)
        self._overlay_token = None
        self._overlay_pending = 0
        self._overlay_fallback = QTimer(self)
        self._overlay_fallback.setSingleShot(True)
        self._overlay_fallback.timeout.connect(self._on_overlay_fallback)
        # Статус
        self.lblStatus = QLabel("Показано: 0 / 0")
        self.lblStatus.setStyleSheet(f"color:{SUB}; padding-left:10px;")
        root.addWidget(self.lblStatus)
        # связи
        self.edSearch.textChanged.connect(self._apply_filters)
        self.cmbType.currentIndexChanged.connect(self._apply_filters)
        self.cbOnlySel.toggled.connect(self._apply_filters)
        self.cbFav.toggled.connect(self._apply_filters)
        self.cmbExch.changed.connect(self._apply_filters)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalHeader().installEventFilter(self)
        QTimer.singleShot(0, self._fit_columns)
        # parser actions
        self.btnScan.clicked.connect(self._start_scan)
        self.btnStop.clicked.connect(self._stop_scan)
    # ---------- helpers ----------
    def _apply_table_theme(self):
        BG0 = C("bg0", "#121417"); BG1 = C("bg1", "#171A1E")
        OUT = C("outline", "#2a2f36"); ACC = C("accent", "#00E0FF")
        TEXT = C("text", "#EDEBEB")
        self._bg_table = BG0
        selection_bg = _rgba_hex(ACC, 0.22)
        palette = self.table.palette()
        highlight_text = palette.color(QPalette.Active, QPalette.HighlightedText).name()
        normal_text = TEXT
        self._selection_bg = selection_bg
        self._selection_text_normal = normal_text
        self._selection_text_selected = highlight_text
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background:{BG0};
                color:{TEXT};
                border:1px solid {OUT};
                border-radius:0;
                gridline-color:{OUT};
            }}
            QHeaderView::section {{
                background:{BG1};
                color:{TEXT};
                border:0;
                border-right:1px solid {OUT};
                border-bottom:1px solid {OUT};
                border-left:1px solid {OUT};
                padding:10px 12px;
                font-weight:700;
            }}
            QHeaderView::section:first {{
                border-left:0;
            }}
            QHeaderView::section:last {{
                border-right:0;
            }}
            QTableView::item {{
                border:0;
                padding:10px 12px;
            }}
            QTableView::item:selected {{
                background:{selection_bg};
                color:{TEXT};
            }}
            QTableView::item:focus {{ outline:none; }}
            QTableCornerButton::section {{
                background:{BG1};
                border:0;
                border-right:1px solid {OUT};
                border-bottom:1px solid {OUT};
            }}
            """
        )
        # обновляем фон первой колонки (виджет рисует прозрачный фон)
        for row in range(self.table.rowCount()):
            it = self.table.item(row, self.COL_NAME)
            if it:
                it.setBackground(QColor(self._bg_table))
            w = self.table.cellWidget(row, self.COL_NAME)
            if isinstance(w, TickerCell):
                w.set_text_palette(normal_text, highlight_text)
                w.set_icon_colors(normal_text, ACC)
    def _on_icon_ready(self, token):
        if token != self._overlay_token:
            return
        if self._overlay_pending > 0:
            self._overlay_pending -= 1
        self._maybe_stop_overlay(token)
    def _maybe_stop_overlay(self, token):
        if token != self._overlay_token:
            return
        if self._overlay_pending <= 0:
            self._overlay_fallback.stop()
            self.overlay.stop()
            self._overlay_token = None
    def _on_overlay_fallback(self):
        token = self._overlay_token
        self._overlay_pending = 0
        self._maybe_stop_overlay(token)
    @staticmethod
    def _split_exchanges(s: str) -> List[str]:
        xs = [re.sub(r"\s+", " ", x.strip()) for x in (s or "").replace(";", ",").split(",")]
        return [x for x in xs if x]
    def _all_exchanges_from_coins(self, coins: List[Coin]) -> List[str]:
        bag = set()
        for c in coins:
            bag.update(self._split_exchanges(c.spot_exchanges))
            bag.update(self._split_exchanges(c.futures_exchanges))
        return sorted(bag, key=lambda x: x.lower())
    def _rebuild_exchanges_combo(self):
        self.cmbExch.set_items(self._all_exchanges_from_coins(self._coins))
    def reload_from_db(self):
        try:
            self._coins = list(self.db.search_coins() or [])
        except Exception as e:
            self._coins = []
            notify(self, f"DB error: {e}", "error")
        self._rebuild_exchanges_combo()
        self._apply_filters()
    def _apply_filters(self):
        token = object()
        self._overlay_token = token
        self._overlay_pending = 0
        self.overlay.start()
        self._overlay_fallback.start(1500)
        ACC = C("accent", "#00E0FF")
        TEXT = C("text", "#EDEBEB")
        name_q = (self.edSearch.text() or "").strip().lower()
        typ = self.cmbType.currentText()
        only_sel = self.cbOnlySel.isChecked()
        only_fav = self.cbFav.isChecked()
        chosen = set(self.cmbExch.checked())
        rows = []
        for c in self._coins:
            if only_fav and not getattr(c, "favorite", False):
                continue
            if name_q and name_q not in (c.name or "").lower():
                continue
            spot = self._split_exchanges(c.spot_exchanges)
            fut = self._split_exchanges(c.futures_exchanges)
            all_set = set(spot) | set(fut)
            if typ == "Спот" and not spot:
                continue
            if typ == "Фьючерсы" and not fut:
                continue
            if chosen:
                if not only_sel:
                    if typ == "Спот":
                        if not (set(spot) & chosen): continue
                    elif typ == "Фьючерсы":
                        if not (set(fut) & chosen): continue
                    else:
                        if not (all_set & chosen): continue
                else:
                    if typ == "Спот":
                        if set(spot) and not (set(spot) <= chosen): continue
                    elif typ == "Фьючерсы":
                        if set(fut) and not (set(fut) <= chosen): continue
                    else:
                        if all_set and not (all_set <= chosen): continue
            rows.append((c.name, ", ".join(spot), ", ".join(fut), bool(getattr(c, "favorite", False))))
        # заливка таблицы
        self.table.setRowCount(len(rows))
        for r, (nm, sp, fu, fav) in enumerate(rows):
            ticker = TickerCell(nm, fav, self.table)
            normal_text = getattr(self, "_selection_text_normal", C('text', '#EDEBEB'))
            selected_text = getattr(self, "_selection_text_selected", C('text', '#EDEBEB'))
            ticker.set_text_palette(normal_text, selected_text)
            ticker.set_icon_colors(TEXT, ACC)
            if not ticker.is_favorite_ready():
                self._overlay_pending += 1
                def _mark_ready(tok=token):
                    self._on_icon_ready(tok)
                ticker.on_favorite_ready(_mark_ready)
            item_name = QTableWidgetItem("")
            item_name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item_name.setData(Qt.UserRole, (nm or "").upper())
            item_name.setData(Qt.UserRole + 1, nm or "")
            self.table.setItem(r, self.COL_NAME, item_name)
            self.table.setCellWidget(r, self.COL_NAME, ticker)
            ticker.bind_selection(self.table, r, self.COL_NAME)
            it_sp = QTableWidgetItem(sp)
            it_sp.setToolTip(sp or "")
            it_fu = QTableWidgetItem(fu)
            it_fu.setToolTip(fu or "")
            it_sp.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            it_fu.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            it_sp.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_fu.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_sp.setData(Qt.UserRole, (sp or "").lower())
            it_fu.setData(Qt.UserRole, (fu or "").lower())
            self.table.setItem(r, self.COL_SPOT, it_sp)
            self.table.setItem(r, self.COL_FUT,  it_fu)
            # toggle избранного
            def on_toggle(state: bool, coin_name=nm):
                try:
                    self.db.set_favorite(coin_name, state)
                except Exception:
                    pass
                for coin in self._coins:
                    if getattr(coin, "name", "").upper() == (coin_name or "").upper():
                        setattr(coin, "favorite", state)
                        break
            ticker.toggled.connect(on_toggle)
        self._fit_columns()
        self.lblStatus.setText(f"Показано: {len(rows)} / {len(self._coins)}")
        if self._overlay_pending <= 0:
            QTimer.singleShot(120, lambda: self._maybe_stop_overlay(token))
    def _fit_columns(self):
        try:
            viewport_w = self.table.viewport().width()
        except Exception:
            return
        if viewport_w <= 0:
            return
        base_total = float(sum(self._col_basis)) or 1.0
        scale = viewport_w / base_total
        widths = []
        for idx, base in enumerate(self._col_basis):
            min_w = self._col_min[idx] if idx < len(self._col_min) else 120
            width = max(min_w, int(base * scale))
            widths.append(width)
        diff = viewport_w - sum(widths)
        if widths and diff != 0:
            last_idx = len(widths) - 1
            widths[last_idx] = max(self._col_min[last_idx], widths[last_idx] + diff)
        for idx, width in enumerate(widths):
            self.table.setColumnWidth(idx, width)
    # ---------- Parser actions ----------
    def _start_scan(self):
        raw = self.edCoins.text().strip()
        if not raw:
            notify(self, "Укажи монеты через запятую", "warning"); return
        names = [x.strip() for x in re.split(r"[,\s]+", raw) if x.strip()]
        if not names:
            notify(self, "Нет валидных тикеров", "warning"); return
        self.btnScan.setEnabled(False); self.pb.setValue(0)
        headless = self.cbHeadless.isChecked()
        total = len(names)
        done = dict(count=0)
        def work():
            for n in names:
                try:
                    res = parse_coin_in_process(n, headless=headless)
                    nm = (res.get("name") or n).upper()
                    spot = ", ".join(res.get("spot") or [])
                    fut  = ", ".join(res.get("futures") or [])
                    self.db.save_coin(nm, spot, fut)
                except Exception:
                    pass
                done["count"] += 1
                QTimer.singleShot(0, lambda: self.pb.setValue(int(done["count"] * 100 / total)))
            QTimer.singleShot(0, self._scan_finished)
        self._executor.submit(work)
    def _scan_finished(self):
        self.btnScan.setEnabled(True)
        self.reload_from_db()
        self.pb.setValue(100)
        notify(self, "Скан завершён", "success", 2200)
    def _stop_scan(self):
        self._executor.shutdown(cancel_futures=True)
        self._executor = ThreadPoolExecutor(max_workers=1)
        self.btnScan.setEnabled(True)
        notify(self, "Остановил очередь задач", "warning", 1800)
    def dispose(self):
        try: self._executor.shutdown(cancel_futures=True)
        except Exception: pass
        try: self.db.close()
        except Exception: pass
# ---------------- Страница Database ----------------
class DatabasePage(QWidget):
    SETTINGS_KEY_LAST = "DatabasePage/lastProfile"
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_profiles()
        QTimer.singleShot(150, lambda: self.tabs.tabBar()._on_current_changed(self.tabs.currentIndex()))
        QTimer.singleShot(0, self._restore_last_active)
        self.tabs.currentChanged.connect(self._save_last_active)
    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.tabs = QTabWidget(self)
        bar = HardSeparatorsTabBar(self.tabs)
        self.tabs.setTabBar(bar)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setMovable(True)
        self.tabs.setStyleSheet(f"QTabWidget::pane {{ border:0; top:0; background:{C('bg0','#121417')}; }}")
        # corner-widget с «+»
        plusHost = QWidget(self.tabs)
        phl = QHBoxLayout(plusHost); phl.setContentsMargins(8, 4, 8, 4); phl.setSpacing(0)
        self.plusBtn = QToolButton(plusHost)
        self.plusBtn.setCursor(Qt.PointingHandCursor)
        self.plusBtn.setIcon(_qicon(SVG_PLUS))
        self.plusBtn.setAutoRaise(True)
        self.plusBtn.setFixedSize(28, 28)
        self.plusBtn.setStyleSheet(f"""
            QToolButton {{
                border: none; padding: 0;
                background: {_rgba_hex(C('accent','#00E0FF'),0.22)};
                border-radius: 6px;
            }}
            QToolButton:hover  {{ background: {_rgba_hex(C('accent','#00E0FF'),0.34)}; }}
            QToolButton:pressed{{ background: {_rgba_hex(C('accent','#00E0FF'),0.50)}; }}
        """)
        phl.addWidget(self.plusBtn)
        self.tabs.setCornerWidget(plusHost, Qt.TopRightCorner)
        self.plusBtn.clicked.connect(self._show_plus_panel)
        bar.set_external_plus(self.plusBtn)
        # inline editor
        self._inline_editor = QLineEdit(self.tabs.tabBar())
        self._inline_editor.setVisible(False)
        self._inline_editor.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._inline_editor.setStyleSheet(f"""
            QLineEdit {{
                background:{C('bg1','#1f232a')}; color:{C('text','#E6EAED')};
                border:1px solid {_rgba_hex(C('accent','#00E0FF'),0.4)};
                border-radius:4px; padding:4px 8px; selection-background-color:#39424d;
                font-size:12px;
            }}
        """)
        f: QFont = bar.font(); f.setPixelSize(12); self._inline_editor.setFont(f)
        self._inline_editor.returnPressed.connect(self._commit_inline_rename)
        self._inline_editor.editingFinished.connect(self._commit_inline_rename)
        self._inline_editor.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        bar.inlineRenameRequested.connect(self._start_inline_rename)
        root.addWidget(self.tabs, 1)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_ctx)
        self._profiles_panel: Optional[ProfilesPanel] = None
    # ---------- Inline rename ----------
    def _start_inline_rename(self, idx: int, rect: QRect):
        if idx < 0: return
        name = self.tabs.tabText(idx)
        self._rename_idx = idx
        self._inline_editor.setText(name)
        self._inline_editor.selectAll()
        self._inline_editor.setGeometry(rect.adjusted(0, 4, 0, -4))
        self._inline_editor.setVisible(True)
        self._inline_editor.setFocus(Qt.TabFocusReason)
        self._inline_editor.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self._inline_editor, b"windowOpacity", self)
        anim.setDuration(120); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic); anim.start()
        self._inline_anim = anim
    def _commit_inline_rename(self):
        if not self._inline_editor.isVisible(): return
        new = self._inline_editor.text().strip()
        idx = getattr(self, "_rename_idx", -1)
        self._inline_editor.hide()
        if idx >= 0 and new: self.rename_profile(idx, new)
    def eventFilter(self, obj, ev):
        if obj is self._inline_editor and ev.type() == QEvent.KeyPress:
            if isinstance(ev, QKeyEvent) and ev.key() == Qt.Key_Escape:
                self._inline_editor.hide(); return True
        if self._inline_editor.isVisible() and ev.type() == QEvent.MouseButtonPress:
            try: gp = ev.globalPosition().toPoint()
            except Exception: gp = getattr(ev, "globalPos", lambda: QPoint())()
            editor_rect = QRect(self._inline_editor.mapToGlobal(QPoint(0, 0)), self._inline_editor.size())
            if not editor_rect.contains(gp): self._inline_editor.hide()
        return super().eventFilter(obj, ev)
    # ---------- Plus panel ----------
    def _ensure_profiles_panel(self):
        if self._profiles_panel: return
        self._profiles_panel = ProfilesPanel(self.window())
        self._profiles_panel.createRequested.connect(self._new_profile)
        self._profiles_panel.profileRequested.connect(self._open_or_focus_profile)
    def _show_plus_panel(self):
        self._ensure_profiles_panel()
        names = Database.list_profiles() or []
        self._profiles_panel.rebuild(names)
        self._profiles_panel.showNear(self.plusBtn)
    def _open_or_focus_profile(self, name: str):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i); return
        self._open_profile_tab(name)
    # ---------- Load / open ----------
    def _load_profiles(self):
        names = list(Database.list_profiles() or ["default"]) or ["default"]
        for n in names: self._open_profile_tab(n)
    def _open_profile_tab(self, name: str):
        view = ProfileView(name, self)
        idx = self.tabs.addTab(view, QIcon(), name)
        self.tabs.setCurrentIndex(idx)
    # ---------- Profile ops ----------
    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "Новый профиль", "Имя профиля:", text="Профиль")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in set(Database.list_profiles() or []):
            notify(self, "Это имя профиля уже занято", "error", ms=3000); return
        try: _ = Database(name)
        except Exception: pass
        self._open_profile_tab(name)
        notify(self, f"Профиль «{name}» создан", ms=3000)
    def close_profile(self, index: int, *, ask_delete: bool = False):
        w: Optional[ProfileView] = self.tabs.widget(index)  # type: ignore
        if not w: return
        name = getattr(w, "profile_name", "")
        if ask_delete:
            ok = QMessageBox.question(
                self, "Удаление профиля",
                f"Удалить профиль «{name}»? Это действие может быть необратимым.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) == QMessageBox.Yes
            if not ok: return
            try:
                success = _safe_db_delete(w.db, name)
            except Exception:
                success = False
            if not success:
                notify(self, "Не удалось удалить профиль через бэкенд", "error", ms=3500); return
        try: w.dispose()
        except Exception: pass
        self.tabs.removeTab(index)
    def rename_profile(self, index: int, new_name: str):
        w: Optional[ProfileView] = self.tabs.widget(index)  # type: ignore
        if not w: return
        new_name = new_name.strip()
        if not new_name: return
        old = w.profile_name
        if new_name == old: return
        if new_name in set(Database.list_profiles() or []):
            notify(self, "Это имя профиля уже занято", "error", ms=3000); return
        try:
            _safe_db_rename(w.db, old, new_name)
            w.profile_name = new_name
            self.tabs.setTabText(index, new_name)
            notify(self, "Переименовано", ms=2500)
        except Exception as e:
            QMessageBox.warning(self, "Переименование", f"Не удалось: {e}")
    # ---------- Context menu ----------
    def _tab_ctx(self, pos: QPoint):
        bar = self.tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0: return
        m = QMenu(self)
        m.addAction("Переименовать…", lambda: self._rename_ctx(idx))
        m.addSeparator()
        m.addAction("Закрыть вкладку", lambda: self.close_profile(idx, ask_delete=False))
        m.addAction("Удалить профиль…", lambda: self.close_profile(idx, ask_delete=True))
        m.setWindowOpacity(0.0); m.popup(bar.mapToGlobal(pos))
        anim = QPropertyAnimation(m, b"windowOpacity", self)
        anim.setDuration(120); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic); anim.start()
        self._ctx_anim = anim
    def _rename_ctx(self, idx: int):
        rect = self.tabs.tabBar()._text_rect_for_index(idx)
        self.tabs.tabBar().inlineRenameRequested.emit(idx, rect)
    # ---------- Persist last active ----------
    def _save_last_active(self, _i: int):
        name = self._current_profile_name() or ""
        _SETTINGS.setValue(self.SETTINGS_KEY_LAST, name)
    def _restore_last_active(self):
        want = _SETTINGS.value(self.SETTINGS_KEY_LAST, "", type=str) or ""
        if not want: return
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == want:
                self.tabs.setCurrentIndex(i); break
    def _current_profile_name(self) -> str:
        i = self.tabs.currentIndex()
        if i < 0: return ""
        return self.tabs.tabText(i) or ""
