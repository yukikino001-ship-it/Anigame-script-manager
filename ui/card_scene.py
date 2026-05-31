from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass
class CardPose:
    # 卡片中心点，按 CardSceneWidget 宽高比例计算
    x_ratio: float
    y_ratio: float

    # 卡片宽度，按 CardSceneWidget 宽度比例计算
    width_ratio: float

    # v25：伪 3D 三轴旋转
    # pitch：绕卡片自身水平轴俯仰
    # yaw：绕卡片自身垂直轴左右转向
    # roll：屏幕平面内旋转，等价于旧 rotation
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0

    # 保留旧字段兼容；读取旧 json 时会被迁移到 roll
    rotation: float = 0.0

    # 文字固定居中，不再单独调 title_x/title_y
    title_size_ratio: float = 0.065

    z: int = 0


# ============================================================
# v25 内部调参区
#
# x_ratio / y_ratio：卡片中心点
# width_ratio：卡片宽度比例，等比例缩放 PNG，不拉伸
# pitch / yaw / roll：伪 3D 三轴旋转
# title_size_ratio：居中文字字号比例
#
# 注意：
# 这不是 OpenGL 真 3D，而是把卡片四角投影到二维平面后做 QTransform。
# 对 UI 卡片来说已经足够模拟“向中间延伸”的透视感。
# ============================================================
OVERVIEW_LAYOUT: Dict[str, CardPose] = {
    # v28.3：采用当前实测较舒服的默认布局参数。
    # 三张卡片统一 yaw=-30，让正面略朝向右侧看板娘；
    # 主卡更大，小卡贴近主卡下方，形成轻舞台式三角构图。
    "tasks": CardPose(
        x_ratio=0.565, y_ratio=0.310, width_ratio=0.425,
        pitch=-8.0, yaw=-30.0, roll=1.0,
        title_size_ratio=0.060, z=3
    ),
    "stats": CardPose(
        x_ratio=0.318, y_ratio=0.694, width_ratio=0.255,
        pitch=-2.0, yaw=-30.0, roll=-2.0,
        title_size_ratio=0.073, z=2
    ),
    "logs": CardPose(
        x_ratio=0.775, y_ratio=0.680, width_ratio=0.255,
        pitch=-6.0, yaw=-30.0, roll=-2.0,
        title_size_ratio=0.073, z=2
    ),
}

EXPANDED_LAYOUT: Dict[str, CardPose] = {
    "tasks": CardPose(x_ratio=0.30, y_ratio=0.900, width_ratio=0.185, pitch=0.0, yaw=0.0, roll=-2.0, title_size_ratio=0.073, z=2),
    "stats": CardPose(x_ratio=0.50, y_ratio=0.900, width_ratio=0.185, pitch=0.0, yaw=0.0, roll=0.0, title_size_ratio=0.073, z=2),
    "logs":  CardPose(x_ratio=0.70, y_ratio=0.900, width_ratio=0.185, pitch=0.0, yaw=0.0, roll=2.0, title_size_ratio=0.073, z=2),
}

DEFAULT_TITLES = {
    "tasks": "任务执行",
    "stats": "运行耗时",
    "logs": "运行日志",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _asset_path(*parts: str) -> Path:
    return _project_root() / "assets" / Path(*parts)


def _layout_debug_path() -> Path:
    path = _project_root() / "config" / "card_layout_debug.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _pose_from_dict(data: Dict[str, Any], fallback: CardPose) -> CardPose:
    """兼容旧版 card_layout_debug.json。

    旧版有 rotation / skew_x / title_x 等字段。
    v25 只取当前有效字段，并把 rotation 迁移到 roll。
    """
    base = asdict(fallback)
    valid_keys = set(base.keys())

    # 旧 rotation 没有 roll 时，自动迁移。
    if "roll" not in data and "rotation" in data:
        data = dict(data)
        data["roll"] = data.get("rotation", 0.0)

    for key, value in data.items():
        if key in valid_keys:
            base[key] = value

    return CardPose(**base)


def _projected_quad(width: float, height: float, pitch_deg: float, yaw_deg: float, roll_deg: float) -> QPolygonF:
    """根据 pitch/yaw/roll 计算二维投影四边形。

    坐标原点以卡片中心为准。
    """
    hw = width / 2.0
    hh = height / 2.0

    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    roll = math.radians(roll_deg)

    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cr, sr = math.cos(roll), math.sin(roll)

    # 相机距离越大，透视越弱；越小，透视越强。
    camera_distance = max(width, height) * 2.6

    points = [
        (-hw, -hh, 0.0),
        ( hw, -hh, 0.0),
        ( hw,  hh, 0.0),
        (-hw,  hh, 0.0),
    ]

    projected = []
    for x, y, z in points:
        # pitch: 绕 X 轴
        y1 = y * cp - z * sp
        z1 = y * sp + z * cp
        x1 = x

        # yaw: 绕 Y 轴
        x2 = x1 * cy + z1 * sy
        z2 = -x1 * sy + z1 * cy
        y2 = y1

        # roll: 绕 Z 轴
        x3 = x2 * cr - y2 * sr
        y3 = x2 * sr + y2 * cr
        z3 = z2

        factor = camera_distance / (camera_distance + z3)
        projected.append(QPointF(x3 * factor, y3 * factor))

    return QPolygonF(projected)


class ImageCard(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, title: str, image_path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = key
        self.title = title
        self.image_path = Path(image_path)
        self._base_pixmap = QPixmap(str(self.image_path)) if self.image_path.exists() else QPixmap()
        self._scaled_pixmap = QPixmap()
        self._pose = OVERVIEW_LAYOUT.get(key)
        self._target_width = 220
        self._transform = QTransform()
        self._source_rect = QRectF()

        # v28：伪 2.5D 双层卡片。
        # 用同一张 PNG 在背后再叠一层，轻微偏移、透明、变亮，
        # 低成本制造玻璃厚度感，不引入 Three.js / OpenGL 真 3D。
        self._paint_margin = 36
        # v28.1：默认卡片整体朝右侧看板娘方向展示时，后层应落在左下侧，
        # 避免后层叠到右上方后显得“反向出厚度”。
        self._back_dx = -18
        self._back_dy = 12
        self._back_opacity = 0.34
        self._foreground_center = QPointF(0, 0)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def set_title(self, title: str) -> None:
        self.title = title
        self.update()

    def set_image(self, image_path: Path) -> None:
        self.image_path = Path(image_path)
        self._base_pixmap = QPixmap(str(self.image_path)) if self.image_path.exists() else QPixmap()
        self.set_pose(self._target_width, self._pose)

    def set_pose(self, target_width: int, pose: CardPose) -> None:
        if target_width <= 10:
            return

        self._pose = pose
        self._target_width = target_width

        if self._base_pixmap.isNull():
            self._scaled_pixmap = QPixmap()
            w = target_width
            h = int(target_width * 0.44)
        else:
            self._scaled_pixmap = self._base_pixmap.scaledToWidth(
                target_width,
                Qt.TransformationMode.SmoothTransformation,
            )
            w = self._scaled_pixmap.width()
            h = self._scaled_pixmap.height()

        self._source_rect = QRectF(0, 0, w, h)
        src = QPolygonF([
            QPointF(0, 0),
            QPointF(w, 0),
            QPointF(w, h),
            QPointF(0, h),
        ])

        quad = _projected_quad(w, h, pose.pitch, pose.yaw, pose.roll)
        bounds = quad.boundingRect()

        m = self._paint_margin
        dst = QPolygonF([
            QPointF(quad[0].x() - bounds.left() + m, quad[0].y() - bounds.top() + m),
            QPointF(quad[1].x() - bounds.left() + m, quad[1].y() - bounds.top() + m),
            QPointF(quad[2].x() - bounds.left() + m, quad[2].y() - bounds.top() + m),
            QPointF(quad[3].x() - bounds.left() + m, quad[3].y() - bounds.top() + m),
        ])

        transform = QTransform()
        ok = QTransform.quadToQuad(src, dst, transform)
        if ok:
            self._transform = transform
        else:
            self._transform = QTransform()

        self._foreground_center = QPointF(m + bounds.width() / 2.0, m + bounds.height() / 2.0)

        # 给背后叠层、发光和阴影预留绘制空间，避免偏移后被裁切。
        self.resize(
            max(1, int(bounds.width()) + m * 2 + abs(self._back_dx) + 8),
            max(1, int(bounds.height()) + m * 2 + abs(self._back_dy) + 8),
        )
        self.update()

    def foreground_center(self) -> QPointF:
        return QPointF(self._foreground_center)

    def paintEvent(self, event):  # type: ignore[override]
        if self._pose is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        painter.setTransform(self._transform)

        if not self._scaled_pixmap.isNull():
            # v28.1：背后一层同素材卡片，制造类 2.5D 厚度。
            # 当前布局通常让卡片正面偏向右侧，因此后层默认压到左下侧。
            # 后层只承担空间感，不绘制文字，避免重影。
            painter.save()
            painter.setOpacity(self._back_opacity)
            painter.drawPixmap(self._back_dx, self._back_dy, self._scaled_pixmap)
            painter.restore()

            # 前层保持清晰。
            painter.drawPixmap(0, 0, self._scaled_pixmap)
        else:
            painter.save()
            painter.setOpacity(self._back_opacity)
            painter.setPen(QColor(120, 160, 215, 110))
            painter.setBrush(QColor(255, 255, 255, 55))
            painter.drawRoundedRect(
                QRectF(self._source_rect).translated(self._back_dx, self._back_dy),
                12,
                12,
            )
            painter.restore()

            painter.setPen(QColor(120, 160, 215, 180))
            painter.setBrush(QColor(255, 255, 255, 80))
            painter.drawRoundedRect(self._source_rect, 12, 12)

        font = QFont("Microsoft YaHei")
        font.setBold(True)
        font.setPixelSize(max(14, int(self._source_rect.width() * self._pose.title_size_ratio)))
        painter.setFont(font)
        painter.setPen(QColor("#20365F"))
        painter.drawText(self._source_rect, Qt.AlignmentFlag.AlignCenter, self.title)

        painter.end()


class LayoutTunerDialog(QDialog):
    """内部布局调参器。"""

    PARAMS = [
        ("x_ratio", 0.0, 1.0, 0.005, 3),
        ("y_ratio", 0.0, 1.0, 0.005, 3),
        ("width_ratio", 0.05, 0.80, 0.005, 3),
        ("pitch", -75.0, 75.0, 0.5, 1),
        ("yaw", -75.0, 75.0, 0.5, 1),
        ("roll", -360.0, 360.0, 0.5, 1),
        ("title_size_ratio", 0.02, 0.15, 0.001, 3),
    ]

    def __init__(self, scene: "CardSceneWidget"):
        super().__init__(scene)
        self.scene = scene
        self.setWindowTitle("v25 内部卡片布局调参器")
        self.resize(620, 680)

        root = QVBoxLayout(self)
        tip = QLabel(
            "文字现在固定居中并跟随卡片变换。\n"
            "pitch=上下俯仰，yaw=左右转向，roll=平面旋转。"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.controls: Dict[str, Dict[str, QDoubleSpinBox]] = {}

        for key, title in DEFAULT_TITLES.items():
            section = QWidget()
            form = QFormLayout(section)
            form.setContentsMargins(8, 8, 8, 8)
            form.addRow(QLabel(f"【{title}】{key}"), QLabel(""))

            self.controls[key] = {}
            pose = self.scene.overview_layout[key]
            for name, min_v, max_v, step, decimals in self.PARAMS:
                spin = QDoubleSpinBox()
                spin.setRange(min_v, max_v)
                spin.setSingleStep(step)
                spin.setDecimals(decimals)
                spin.setValue(float(getattr(pose, name)))
                spin.valueChanged.connect(lambda value, k=key, n=name: self._on_value_changed(k, n, value))
                self.controls[key][name] = spin
                form.addRow(name, spin)

            body_layout.addWidget(section)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        btns = QHBoxLayout()
        copy_btn = QPushButton("复制当前参数")
        save_btn = QPushButton("保存到 config/card_layout_debug.json")
        load_btn = QPushButton("加载已保存")
        reset_btn = QPushButton("重置默认")
        close_btn = QPushButton("关闭")

        copy_btn.clicked.connect(self.copy_current_params)
        save_btn.clicked.connect(self.save_current_params)
        load_btn.clicked.connect(self.load_saved_params)
        reset_btn.clicked.connect(self.reset_defaults)
        close_btn.clicked.connect(self.accept)

        btns.addWidget(copy_btn)
        btns.addWidget(save_btn)
        btns.addWidget(load_btn)
        btns.addWidget(reset_btn)
        btns.addWidget(close_btn)
        root.addLayout(btns)

        self.setStyleSheet("""
            QDialog, QWidget {
                background-color: #EEF6FF;
                color: #20365F;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QLabel {
                color: #20365F;
                background: transparent;
                font-size: 13px;
            }
            QDoubleSpinBox {
                color: #20365F;
                background-color: rgba(255, 255, 255, 235);
                border: 1px solid rgba(120, 160, 215, 180);
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 24px;
                selection-background-color: #B7D3FF;
                selection-color: #10243F;
            }
            QPushButton {
                color: #20365F;
                background-color: rgba(255, 255, 255, 235);
                border: 1px solid rgba(120, 160, 215, 190);
                border-radius: 8px;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(225, 240, 255, 245);
            }
        """)

    def _on_value_changed(self, key: str, name: str, value: float) -> None:
        setattr(self.scene.overview_layout[key], name, float(value))
        self.scene.apply_layout()

    def _sync_controls(self) -> None:
        for key, fields in self.controls.items():
            pose = self.scene.overview_layout[key]
            for name, spin in fields.items():
                spin.blockSignals(True)
                spin.setValue(float(getattr(pose, name)))
                spin.blockSignals(False)

    def _serializable(self) -> Dict[str, Dict[str, float]]:
        return {key: asdict(pose) for key, pose in self.scene.overview_layout.items()}

    def copy_current_params(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("OVERVIEW_LAYOUT = " + repr(self._serializable()))

    def save_current_params(self) -> None:
        with _layout_debug_path().open("w", encoding="utf-8") as f:
            json.dump(self._serializable(), f, ensure_ascii=False, indent=2)

    def load_saved_params(self) -> None:
        self.scene.load_debug_layout()
        self._sync_controls()

    def reset_defaults(self) -> None:
        self.scene.reset_debug_layout()
        self._sync_controls()


class CardSceneWidget(QWidget):
    """v25：卡片导航 + 真实功能详情页容器 + pitch/yaw/roll 调参器。"""

    cardClicked = Signal(str)
    card_clicked = Signal(str)
    exit_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._active_key = "tasks"
        self._mode = "overview"
        self.detail_panels: Dict[str, QWidget] = {}
        self.overview_layout: Dict[str, CardPose] = {
            key: CardPose(**asdict(value)) for key, value in OVERVIEW_LAYOUT.items()
        }
        self._default_overview_layout: Dict[str, CardPose] = {
            key: CardPose(**asdict(value)) for key, value in OVERVIEW_LAYOUT.items()
        }

        self.cards: Dict[str, ImageCard] = {
            "tasks": ImageCard("tasks", DEFAULT_TITLES["tasks"], self._default_image_path("tasks"), self),
            "stats": ImageCard("stats", DEFAULT_TITLES["stats"], self._default_image_path("stats"), self),
            "logs": ImageCard("logs", DEFAULT_TITLES["logs"], self._default_image_path("logs"), self),
        }

        for card in self.cards.values():
            card.clicked.connect(self._emit_clicked)
            card.show()

        self.back_button = QPushButton("↙", self)
        self.back_button.setToolTip("返回卡片总览")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setStyleSheet("""
            QPushButton {
                color: #20365f;
                background: rgba(255, 255, 255, 165);
                border: 1px solid rgba(110, 150, 210, 130);
                border-radius: 12px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 220);
            }
        """)
        self.back_button.clicked.connect(self.exit_requested.emit)
        self.back_button.hide()

        self._tuner_dialog: Optional[LayoutTunerDialog] = None
        self.load_debug_layout(silent=True)

    def _emit_clicked(self, key: str) -> None:
        key = self._normalize_key(key)
        self._active_key = key
        self.cardClicked.emit(key)
        self.card_clicked.emit(key)

    def _default_image_path(self, key: str) -> Path:
        if key == "tasks":
            p = _asset_path("cards", "main", "card_main.png")
            if not p.exists():
                p = _asset_path("cards", "large", "card_main.png")
            return p

        if key == "stats":
            p = _asset_path("cards", "small", "card_stats.png")
            if p.exists():
                return p

        if key == "logs":
            # v28.6: 运行日志优先读取第二张小卡素材，便于和“运行耗时”做视觉区分。
            p = _asset_path("cards", "small", "card_sub_2.png")
            if p.exists():
                return p
            p = _asset_path("cards", "small", "card_logs.png")
            if p.exists():
                return p

        return _asset_path("cards", "small", "card_sub.png")

    def open_layout_tuner(self) -> None:
        if self._tuner_dialog is None:
            self._tuner_dialog = LayoutTunerDialog(self)
        self._tuner_dialog._sync_controls()
        self._tuner_dialog.show()
        self._tuner_dialog.raise_()
        self._tuner_dialog.activateWindow()

    def reset_debug_layout(self) -> None:
        self.overview_layout = {
            key: CardPose(**asdict(value)) for key, value in self._default_overview_layout.items()
        }
        self.apply_layout()

    def load_debug_layout(self, silent: bool = False) -> None:
        path = _layout_debug_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, item in data.items():
                if key in self.overview_layout and isinstance(item, dict):
                    self.overview_layout[key] = _pose_from_dict(item, self.overview_layout[key])
            self.apply_layout()
        except Exception:
            if not silent:
                raise

    # ---- compatibility API for main_window.py ----
    def set_cards(self, cards: Any) -> None:
        if isinstance(cards, dict):
            for key, panel in cards.items():
                norm = self._normalize_key(str(key))
                if norm not in self.cards:
                    continue

                self.cards[norm].set_title(DEFAULT_TITLES[norm])

                if isinstance(panel, QWidget):
                    self.detail_panels[norm] = panel
                    panel.setParent(self)
                    panel.hide()

                    if hasattr(panel, "set_mode"):
                        panel.set_mode("expanded")
                    if hasattr(panel, "exit_requested"):
                        try:
                            panel.exit_requested.connect(self.exit_requested.emit)
                        except Exception:
                            pass
                    if hasattr(panel, "clicked"):
                        try:
                            panel.clicked.connect(self._emit_clicked)
                        except Exception:
                            pass

        self.apply_layout()

    def set_active_card(self, key: str) -> None:
        self._active_key = self._normalize_key(key)
        self.apply_layout()

    def set_overview(self) -> None:
        self._mode = "overview"
        self.back_button.hide()
        for panel in self.detail_panels.values():
            panel.hide()
        for card in self.cards.values():
            card.show()
        self.apply_layout()

    def set_expanded(self, key: str) -> None:
        self._mode = "expanded"
        self._active_key = self._normalize_key(key)
        # v27.3：返回交互放回详情面板标题栏，场景浮动按钮保持隐藏，避免双返回。
        self.back_button.hide()
        # v27：详情页改为独立大页面，不再在底部保留另外两张小卡片。
        for card in self.cards.values():
            card.hide()
        for k, panel in self.detail_panels.items():
            panel.setVisible(k == self._active_key)
            if k == self._active_key and hasattr(panel, "set_mode"):
                panel.set_mode("expanded")
        self.apply_layout()

    def show_overview(self) -> None:
        self.set_overview()

    def show_detail(self, key: str) -> None:
        self.set_expanded(key)

    def refresh_cards(self) -> None:
        self.apply_layout()

    def _normalize_key(self, key: str) -> str:
        k = key.lower().strip()
        mapping = {
            "task": "tasks",
            "tasks": "tasks",
            "任务": "tasks",
            "任务执行": "tasks",
            "stats": "stats",
            "stat": "stats",
            "statistics": "stats",
            "运行耗时": "stats",
            "运行耗时统计": "stats",
            "logs": "logs",
            "log": "logs",
            "日志": "logs",
            "运行日志": "logs",
        }
        return mapping.get(k, k if k in self.cards else "tasks")

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self.apply_layout()

    def apply_layout(self) -> None:
        if self._mode == "expanded":
            self.apply_expanded_layout()
        else:
            self.apply_overview_layout()

    def apply_overview_layout(self) -> None:
        w = max(1, self.width())
        h = max(1, self.height())
        self.back_button.hide()

        for panel in self.detail_panels.values():
            panel.hide()

        for key, pose in self.overview_layout.items():
            card = self.cards[key]
            target_w = max(160, int(w * pose.width_ratio))
            card.set_pose(target_w, pose)
            cx = int(w * pose.x_ratio)
            cy = int(h * pose.y_ratio)
            visual_center = card.foreground_center() if hasattr(card, "foreground_center") else QPointF(card.width() / 2, card.height() / 2)
            card.move(int(cx - visual_center.x()), int(cy - visual_center.y()))
            card.show()
            card.raise_()

    def apply_expanded_layout(self) -> None:
        w = max(1, self.width())
        h = max(1, self.height())

        # v27.2：详情卡片扩到几乎占满左侧工作区，去掉冗余返回按钮。
        self.back_button.hide()

        detail_rect = QRect(
            int(w * 0.010),
            int(h * 0.010),
            int(w * 0.980),
            int(h * 0.965),
        )

        for key, panel in self.detail_panels.items():
            if key == self._active_key:
                panel.setGeometry(detail_rect)
                panel.show()
                panel.raise_()
            else:
                panel.hide()

        # v27：展开详情页时隐藏底部卡片，避免任务表格被挤压。
        for card in self.cards.values():
            card.hide()

        self.back_button.hide()
