# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Signal, Qt, Property, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy


class CardPanel(QFrame):
    """v21 卡片组件。

    重点变化：
    - 不再用 QPainter 自绘卡片，避免 Painter 循环报错。
    - 卡片背景改成 QLabel 承载 PNG，始终 KeepAspectRatio。
    - 卡片布局由 CardSceneWidget 绝对定位，窗口缩放只改变 scale 与坐标，不拉伸素材。
    - overview/compact 只做导航；expanded 用半透明 Detail 面板承载真实控件。
    """

    clicked = Signal(str)
    exit_requested = Signal()

    def __init__(self, key: str, title: str, subtitle: str = "", preview: str = "") -> None:
        super().__init__()
        self.key = key
        self.title_text = title
        self.subtitle_text = subtitle
        self.preview_text = preview or subtitle
        self._mode = "overview"
        self._accent = QColor("#6C8EBF")
        self._panel_bg = QColor("#FFFFFF")
        self._border = QColor("#B7C7E6")
        self._large_card_pixmap = QPixmap()
        self._small_card_pixmap = QPixmap()
        self._hover_progress = 0.0
        self._pressed_progress = 0.0

        self.setObjectName("CardPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self.bg_label = QLabel(self)
        self.bg_label.setObjectName("CardBackgroundImage")
        self.bg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bg_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.bg_label.lower()

        self.overlay = QWidget(self)
        self.overlay.setObjectName("CardOverlay")
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.root_layout = QVBoxLayout(self.overlay)
        self.root_layout.setContentsMargins(24, 18, 24, 20)
        self.root_layout.setSpacing(10)

        header = QHBoxLayout()
        self.header_layout = header
        # v27.4：详情页标题栏统一 36px 控件高度，避免“返回总览 / 标题 / 进阶设置”基线割裂。
        header.setSpacing(12)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.exit_button = QPushButton("返回总览")
        self.exit_button.setObjectName("CardExitButton")
        self.exit_button.setFixedSize(96, 36)
        self.exit_button.setToolTip("退出详情页 / 回到卡片总览")
        self.exit_button.clicked.connect(self.exit_requested.emit)
        header.addWidget(self.exit_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setFixedHeight(36)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("CardSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.hide()

        header.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)

        self.badge_label = QLabel("")
        self.badge_label.setObjectName("CardBadge")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.badge_label)
        self.badge_label.hide()
        self.root_layout.addLayout(header)

        self.preview_label = QLabel(self.preview_text)
        self.preview_label.setObjectName("CardPreview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.root_layout.addWidget(self.preview_label, 1)

        self.content = QWidget()
        self.content.setObjectName("CardContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self.root_layout.addWidget(self.content, 1)

        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(120)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.set_mode("overview")

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self._update_visual_state()

    hoverProgress = Property(float, get_hover_progress, set_hover_progress)

    def enterEvent(self, event):  # noqa: N802
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_progress = 1.0
            child = self.childAt(event.position().toPoint())
            if child is not self.exit_button:
                self.clicked.emit(self.key)
            self._update_visual_state()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._pressed_progress = 0.0
        self._update_visual_state()
        super().mouseReleaseEvent(event)

    def set_visual_palette(self, accent: str, panel_bg: str, border: str) -> None:
        self._accent = QColor(accent)
        self._panel_bg = QColor(panel_bg)
        self._border = QColor(border)
        self._update_visual_state()

    def set_card_assets(self, large_path: str | None = None, small_path: str | None = None) -> None:
        self._large_card_pixmap = QPixmap(str(large_path)) if large_path else QPixmap()
        self._small_card_pixmap = QPixmap(str(small_path)) if small_path else QPixmap()
        self._refresh_background()

    def set_expanded(self, expanded: bool) -> None:
        self.set_mode("expanded" if expanded else "compact")

    def set_mode(self, mode: str) -> None:
        if mode not in {"overview", "compact", "expanded"}:
            mode = "overview"
        self._mode = mode
        self.setProperty("mode", mode)
        self.setProperty("expanded", mode == "expanded")

        # v27.3：详情页保留一个明确的“返回总览”，避免展开后无法回到卡片页。
        self.exit_button.setVisible(mode == "expanded")
        self.content.setVisible(mode == "expanded")
        self.preview_label.setVisible(mode != "expanded")
        self.bg_label.setVisible(mode != "expanded")

        if mode == "expanded":
            self.badge_label.setText("")
            self.badge_label.hide()
            self.badge_label.hide()
            self.badge_label.hide()
            self.subtitle_label.setVisible(bool(self.subtitle_text))
            self.preview_label.setText("")
            self.root_layout.setContentsMargins(24, 18, 24, 20)
        elif mode == "overview":
            self.badge_label.setText("")
            self.badge_label.hide()
            self.badge_label.hide()
            self.badge_label.hide()
            self.subtitle_label.setVisible(bool(self.subtitle_text))
            self.preview_label.setText(self.preview_text)
            self.root_layout.setContentsMargins(30, 24, 30, 24)
        else:
            self.badge_label.setText("")
            self.badge_label.hide()
            self.badge_label.hide()
            self.badge_label.hide()
            self.subtitle_label.setVisible(False)
            self.preview_label.setText("")
            self.root_layout.setContentsMargins(18, 14, 18, 16)

        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_background()
        self._update_visual_state()

    def resizeEvent(self, event):  # noqa: N802
        self.bg_label.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self._refresh_background()
        super().resizeEvent(event)

    def _current_pixmap(self) -> QPixmap:
        if self._mode == "overview" and self.key == "tasks":
            return self._large_card_pixmap
        return self._small_card_pixmap

    def _refresh_background(self) -> None:
        pixmap = self._current_pixmap()
        if pixmap.isNull() or self._mode == "expanded":
            self.bg_label.clear()
            return
        size = pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        if size.width() <= 0 or size.height() <= 0:
            self.bg_label.clear()
            return
        self.bg_label.setPixmap(pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _update_visual_state(self) -> None:
        # 不使用 QGraphicsEffect，避免 Qt 对自定义/复杂透明控件抓图导致 Painter 报错。
        if self._mode == "expanded":
            bg = QColor(self._panel_bg)
            bg.setAlpha(172)
            border = QColor(self._border)
            border.setAlpha(150)
            accent = QColor(self._accent)
            accent.setAlpha(150 + int(55 * self._hover_progress))
            self.setStyleSheet(
                f"QFrame#CardPanel {{ background-color: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()}); "
                f"border: 1px solid rgba({border.red()},{border.green()},{border.blue()},{border.alpha()}); "
                "border-radius: 16px; }"
            )
        else:
            self.setStyleSheet("QFrame#CardPanel { background: transparent; border: none; }")
        self.update()
