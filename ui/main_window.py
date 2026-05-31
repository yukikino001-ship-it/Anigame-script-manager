# -*- coding: utf-8 -*-
from __future__ import annotations

from core import *
import random
import re
import json
from ui.cards import CardPanel
from ui.card_scene import CardSceneWidget, _pose_from_dict
from PySide6.QtCore import QPropertyAnimation, QParallelAnimationGroup, QSequentialAnimationGroup, QEasingCurve, QRect, QRectF, QDateTime, QSize, Signal
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QTableView, QAbstractScrollArea, QMenu


class SpeechBubbleLabel(QLabel):
    clicked = Signal()

    """代码绘制的看板娘发言气泡。

    v31.1：气泡高度会跟随文本自动调整，短句保持小气泡；
    偶发长句最多扩大到三行高度，避免文字被裁切。
    """

    MIN_BUBBLE_HEIGHT = 76
    MAX_BUBBLE_HEIGHT = 138

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(self.MIN_BUBBLE_HEIGHT)
        self.setMaximumHeight(self.MIN_BUBBLE_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        QTimer.singleShot(0, self._adjust_height_to_text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(str(text or ""))
        QTimer.singleShot(0, self._adjust_height_to_text)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().sizeHint()
        return QSize(hint.width(), self.height())

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._adjust_height_to_text()

    def mousePressEvent(self, event):  # type: ignore[override]
        self.clicked.emit()
        super().mousePressEvent(event)

    def _adjust_height_to_text(self) -> None:
        width = max(160, self.width() - 50)
        metrics = self.fontMetrics()
        text_rect = metrics.boundingRect(
            QRect(0, 0, width, 1000),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.text(),
        )
        # 文字区上下 padding + 气泡尾巴高度；限制最大高度，避免气泡变说明书。
        desired = text_rect.height() + 38
        desired = max(self.MIN_BUBBLE_HEIGHT, min(self.MAX_BUBBLE_HEIGHT, desired))
        if self.minimumHeight() != desired or self.maximumHeight() != desired:
            self.setMinimumHeight(desired)
            self.setMaximumHeight(desired)
            self.updateGeometry()
        self.update()

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = max(1, self.width())
        h = max(1, self.height())
        tail_h = 14.0
        margin = 3.0
        body = QRectF(margin, margin, w - margin * 2, h - tail_h - margin * 2)

        path = QPainterPath()
        path.addRoundedRect(body, 24.0, 24.0)

        # 小尾巴朝下，指向下方看板娘；位置略偏右，接近参考图气泡。
        tail_w = min(34.0, max(20.0, w * 0.085))
        tail_x = min(w - tail_w - 28.0, max(28.0, w * 0.70))
        path.moveTo(tail_x, body.bottom() - 1.0)
        path.lineTo(tail_x + tail_w * 0.42, body.bottom() + tail_h)
        path.lineTo(tail_x + tail_w, body.bottom() - 1.0)
        path.closeSubpath()

        painter.setPen(QPen(QColor(120, 130, 155, 185), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255, 238)))
        painter.drawPath(path)

        painter.setPen(QColor(66, 78, 105, 235))
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        text_rect = body.adjusted(22.0, 10.0, -22.0, -10.0)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.text(),
        )


class FrozenColumnsTableWidget(QTableWidget):
    """带左侧冻结列的任务表格。

    v27.3：冻结“启用 / 游戏脚本名称”两列；弱化冻结分隔线，并用轻微底色区分定位列。
    """

    def __init__(self, rows: int, columns: int, frozen_columns: int = 2, parent=None):
        super().__init__(rows, columns, parent)
        self.frozen_columns = max(0, frozen_columns)
        self.frozen_view = QTableView(self)
        self.frozen_view.setModel(self.model())
        self.frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frozen_view.verticalHeader().hide()
        self.frozen_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.frozen_view.setSelectionModel(self.selectionModel())
        self.frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setEditTriggers(self.editTriggers())
        self.frozen_view.setShowGrid(True)
        self.frozen_view.setAlternatingRowColors(True)
        self.frozen_view.setStyleSheet("""
            QTableView {
                background-color: rgba(246, 250, 255, 238);
                alternate-background-color: rgba(238, 245, 255, 238);
                border: none;
                border-right: 1px solid rgba(183, 199, 230, 95);
                gridline-color: rgba(183, 199, 230, 125);
            }
            QHeaderView::section {
                background-color: rgba(226, 236, 252, 245);
                border: 1px solid rgba(183, 199, 230, 130);
                padding: 5px;
            }
        """)
        self.frozen_view.show()

        self.horizontalHeader().sectionResized.connect(self._update_frozen_section_width)
        self.verticalHeader().sectionResized.connect(self._update_frozen_section_height)
        self.verticalScrollBar().valueChanged.connect(self.frozen_view.verticalScrollBar().setValue)
        self.frozen_view.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self._sync_frozen_columns()
        self._update_frozen_geometry()

    def setEditTriggers(self, triggers):  # type: ignore[override]
        super().setEditTriggers(triggers)
        if hasattr(self, "frozen_view"):
            self.frozen_view.setEditTriggers(triggers)

    def setColumnHidden(self, column: int, hide: bool) -> None:  # type: ignore[override]
        super().setColumnHidden(column, hide)
        if hasattr(self, "frozen_view"):
            self.frozen_view.setColumnHidden(column, hide or column >= self.frozen_columns)
            self._update_frozen_geometry()

    def setRowCount(self, rows: int) -> None:  # type: ignore[override]
        super().setRowCount(rows)
        if hasattr(self, "frozen_view"):
            self._sync_frozen_columns()
            self._update_frozen_geometry()

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._update_frozen_geometry()

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):  # type: ignore[override]
        # 冻结列由叠加视图显示，主视图横向滚动时不强制回到左侧。
        if index.column() >= self.frozen_columns:
            super().scrollTo(index, hint)

    def _sync_frozen_columns(self) -> None:
        for col in range(self.columnCount()):
            self.frozen_view.setColumnHidden(col, col >= self.frozen_columns or self.isColumnHidden(col))
        for row in range(self.rowCount()):
            self.frozen_view.setRowHeight(row, self.rowHeight(row))
        for col in range(self.frozen_columns):
            self.frozen_view.setColumnWidth(col, self.columnWidth(col))

    def _update_frozen_section_width(self, logical_index: int, old_size: int, new_size: int) -> None:
        if logical_index < self.frozen_columns:
            self.frozen_view.setColumnWidth(logical_index, new_size)
            self._update_frozen_geometry()

    def _update_frozen_section_height(self, logical_index: int, old_size: int, new_size: int) -> None:
        self.frozen_view.setRowHeight(logical_index, new_size)

    def _frozen_width(self) -> int:
        return sum(self.columnWidth(col) for col in range(self.frozen_columns) if not self.isColumnHidden(col))

    def _update_frozen_geometry(self) -> None:
        width = self._frozen_width()
        if width <= 0:
            self.frozen_view.hide()
            return
        self.frozen_view.show()
        frame = self.frameWidth()
        self.frozen_view.setGeometry(
            frame,
            frame,
            width + 2,
            self.viewport().height() + self.horizontalHeader().height(),
        )
        self.frozen_view.raise_()


class MainWindow(QMainWindow):
    COL_ENABLED = 0
    COL_NAME = 1
    COL_PATH = 2
    COL_BROWSE = 3
    COL_ORDER = 4
    COL_TIMEOUT = 5
    COL_ACTION = 6
    COL_USE_ARGS = 7
    COL_ARGS = 8
    COL_WAIT_MODE = 9
    COL_WAIT_PROCESS = 10
    COL_CONFIRM_ENTER = 11
    COL_CONCURRENT_GROUP = 12
    COL_CONCURRENT_POLICY = 13
    COL_WATCHDOG = 14
    COL_PROCESS_KEYWORDS = 15
    COL_WINDOW_KEYWORDS = 16
    COL_ADVANCED = 17

    def __init__(self) -> None:
        super().__init__()
        self.base_dir = app_dir()
        self.config_manager = ConfigManager(self.base_dir / CONFIG_FILE_NAME)
        self.file_logger = FileLogger(self.base_dir / LOG_DIR_NAME)
        self.stats_manager = RuntimeStatsManager(self.base_dir)
        self.config = self.config_manager.load()

        self.runner_thread: Optional[QThread] = None
        self.runner_worker: Optional[ScriptRunnerWorker] = None
        self.is_running = False

        # v28.7：看板娘状态机。
        # idle：未执行任务时待机；work：执行中；rest：暂停/结束；error：异常提示。
        # error 带最低展示锁定时间，连续触发按 15s、30s、45s... 叠加。
        self.mascot_state = "idle"
        self.mascot_last_non_error_state = "idle"
        self.mascot_error_count = 0
        self.mascot_error_locked_until_ms = 0
        self.mascot_random_timer: Optional[QTimer] = None  # v28.8：保留兼容，不再高频随机换图
        self.shutdown_warning_dialog: Optional[QDialog] = None
        self.shutdown_warning_timer: Optional[QTimer] = None
        self.shutdown_warning_remaining = 0
        self.shutdown_warning_countdown_label: Optional[QLabel] = None
        self.mascot_error_timer: Optional[QTimer] = None
        # v31：统一气泡优先级，避免卡片提示/新手引导覆盖运行中或异常提示。
        self.bubble_priority = 0
        self.bubble_restore_timer: Optional[QTimer] = None
        self._reported_abnormal_messages: set[str] = set()
        self.run_task_error_count = 0
        # v31.3：未配置引导气泡支持点击循环播放，避免单条短提示信息量不足。
        self.current_bubble_kind = "idle"
        self.guide_bubble_index = 0
        self.guide_bubble_texts = [
            "还没有配置任务哦～",
            "可以点击左上角\n“文件”导入配置。",
            "也可以在任务执行卡片里\n手动设置配置。",
            "配置完成后，点击\n开始执行就可以啦。",
            "第一次使用的话，\n可以先观察一下运行状态哦～",
        ]

        self.current_task_name = "-"
        self.current_elapsed = 0
        self.current_progress = (0, 0)

        self.setWindowTitle("雪乃酱 / 二游脚本助手 v1.0")
        self.resize(1280, 800)

        self._build_ui()
        self._connect_signals()
        self._load_config_to_ui()
        self.apply_theme(self.config.theme)
        # v18：启动后强制回到卡片总览态，避免上一次开发阶段遗留为展开态。
        QTimer.singleShot(0, lambda: self.collapse_cards(animated=False))

        self.append_log("程序启动。")
        self.append_log(f"配置文件：{self.config_manager.config_path}")
        self.append_log(f"日志目录：{self.file_logger.log_dir}")
        self.append_log(f"资源目录：{self.base_dir / 'assets'}")
        # v28.8：界面显示后立刻加载 idle，避免刚打开 UI 时看板娘区域空白。
        QTimer.singleShot(0, lambda: self.set_mascot_state("idle", force=True))
        # v31.2：如果还没有可用任务配置，启动后优先播放一次引导气泡，再进入普通 idle。
        QTimer.singleShot(900, lambda: self.show_first_config_guide_if_needed(force=True))
        self.refresh_runtime_stats_view()
        QTimer.singleShot(800, self.show_startup_problem_report_if_needed)

        if self.config.auto_start_tasks:
            self.append_log("已启用程序启动后自动开始执行任务。")
            QTimer.singleShot(1500, self.start_tasks)

    def _build_ui(self) -> None:
        """v14：卡片式主界面。

        这一版先保留 v12 的所有运行逻辑和配置表格，只重构视觉组织：
        任务、统计、日志变成三张卡片，同一时间只有一张卡片是展开页。
        """
        root = QWidget(self)
        root.setObjectName("RootWidget")
        self.root_widget = root
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(10)

        top_group = QGroupBox("控制")
        top_layout = QHBoxLayout(top_group)

        self.add_button = QPushButton("添加任务")
        self.delete_button = QPushButton("删除任务")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.save_button = QPushButton("保存配置")
        self.start_button = QPushButton("开始执行")
        self.resume_button = QPushButton("继续执行")
        self.pause_button = QPushButton("暂停执行")
        self.stop_button = QPushButton("停止执行\nF8")
        self.emergency_stop_button = QPushButton("紧急停止全部\nCtrl+Alt+F8")
        self.file_button = QPushButton("文件 ▼")
        self.settings_button = QPushButton("⚙ 设置")
        self.layout_tuner_button = QPushButton("布局调参")
        self.layout_tuner_button.setVisible(False)  # 发布前用户模式：隐藏开发调参入口
        self.cancel_shutdown_button = QPushButton("取消关机")
        self.export_config_button = QPushButton("导出配置")
        self.import_config_button = QPushButton("导入配置")
        self.export_ui_params_button = QPushButton("导出UI参数")
        self.import_ui_params_button = QPushButton("导入UI参数")

        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.emergency_stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("background-color: #B3261E; color: white; font-weight: bold; padding: 8px 12px;")
        self.emergency_stop_button.setStyleSheet("background-color: #8B0000; color: white; font-weight: bold; padding: 8px 12px;")

        # v28.5：文件菜单里已经包含保存/导入/导出配置和 UI 参数导入导出，
        # 顶部长条控制栏只保留高频全局操作，避免同类入口重复。
        for button in [
            self.file_button,
            self.start_button,
            self.resume_button,
            self.pause_button,
            self.stop_button,
            self.emergency_stop_button,
            self.settings_button,
            self.layout_tuner_button,
            self.cancel_shutdown_button,
        ]:
            top_layout.addWidget(button)
        top_layout.addStretch(1)
        main_layout.addWidget(top_group)

        settings_group = QGroupBox("全局设置")
        settings_layout = QGridLayout(settings_group)
        self.shutdown_checkbox = QCheckBox("所有任务完成后自动关机")
        self.shutdown_delay_spin = QSpinBox()
        self.shutdown_delay_spin.setRange(0, 24 * 3600)
        self.shutdown_delay_spin.setSuffix(" 秒")
        self.shutdown_delay_spin.setSingleStep(10)
        self.auto_exit_checkbox = QCheckBox("所有任务完成后自动退出程序")
        self.auto_start_tasks_checkbox = QCheckBox("程序启动后自动开始执行任务")
        self.windows_startup_checkbox = QCheckBox("Windows 开机自启动本程序")
        self.timeout_screenshot_checkbox = QCheckBox("超时处理时保存前后截图")
        self.theme_label = QLabel("当前主题：-")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("经典风", "yukino")
        self.theme_combo.addItem("校园风", "campus")
        self.theme_combo.addItem("清新风", "fresh")
        self.theme_combo.addItem("暖色幻想风", "fantasy")
        self.theme_label.setVisible(False)
        self.theme_combo.setVisible(False)
        settings_layout.addWidget(self.shutdown_checkbox, 0, 0)
        settings_layout.addWidget(QLabel("关机倒计时："), 0, 1)
        settings_layout.addWidget(self.shutdown_delay_spin, 0, 2)
        settings_layout.addWidget(self.auto_exit_checkbox, 0, 3)
        settings_layout.addWidget(self.auto_start_tasks_checkbox, 1, 0)
        settings_layout.addWidget(self.windows_startup_checkbox, 1, 1, 1, 2)
        settings_layout.addWidget(self.timeout_screenshot_checkbox, 2, 0, 1, 2)
        settings_layout.addWidget(self.theme_label, 0, 4)
        settings_layout.addWidget(self.theme_combo, 0, 5)
        settings_layout.setColumnStretch(6, 1)
        # v17：全局设置不再占据主界面空间，放入齿轮按钮打开的设置弹窗。
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("全局设置")
        self.settings_dialog.setModal(False)
        self.settings_dialog.setObjectName("SettingsDialog")
        settings_dialog_layout = QVBoxLayout(self.settings_dialog)
        settings_dialog_layout.addWidget(settings_group)
        close_settings_button = QPushButton("关闭")
        close_settings_button.clicked.connect(self.settings_dialog.hide)
        settings_dialog_layout.addWidget(close_settings_button, alignment=Qt.AlignmentFlag.AlignRight)

        # v17：当前状态缩成窄条，后面放在看板娘上方。
        status_group = QGroupBox("当前状态")
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setHorizontalSpacing(6)
        status_layout.setVerticalSpacing(4)
        self.status_value_label = QLabel("空闲")
        self.task_value_label = QLabel("-")
        self.elapsed_value_label = QLabel("00:00")
        self.progress_value_label = QLabel("0 / 0")
        status_layout.addWidget(QLabel("状态"), 0, 0)
        status_layout.addWidget(self.status_value_label, 0, 1)
        status_layout.addWidget(QLabel("当前"), 1, 0)
        status_layout.addWidget(self.task_value_label, 1, 1)
        status_layout.addWidget(QLabel("耗时"), 0, 2)
        status_layout.addWidget(self.elapsed_value_label, 0, 3)
        status_layout.addWidget(QLabel("进度"), 1, 2)
        status_layout.addWidget(self.progress_value_label, 1, 3)
        status_layout.setColumnStretch(4, 1)
        self.status_group = status_group

        # ===== v14 卡片工作区 =====
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter, stretch=1)

        # v25-alpha：卡片区改为场景式布局，不再依赖 QGridLayout 拉伸卡片。
        # CardSceneWidget 使用绝对锚点坐标，窗口缩放时只重算位置/比例，卡片素材不变形。
        self.card_area = CardSceneWidget()
        self.main_splitter.addWidget(self.card_area)

        self.task_card = CardPanel(
            "tasks",
            "任务执行",
            "",
            "",
        )
        self.stats_card = CardPanel(
            "stats",
            "运行耗时统计",
            "",
            "",
        )
        self.log_card = CardPanel(
            "logs",
            "运行日志",
            "",
            "",
        )
        self.cards = {
            "tasks": self.task_card,
            "stats": self.stats_card,
            "logs": self.log_card,
        }
        self.card_area.set_cards(self.cards)
        self.card_area.card_clicked.connect(self.expand_card)
        self.card_area.exit_requested.connect(self.collapse_cards)

        self.table = FrozenColumnsTableWidget(0, 18, frozen_columns=2)
        self.table.setHorizontalHeaderLabels([
            "启用", "游戏/脚本名称", "脚本路径", "浏览", "顺序", "最大运行时间(分钟)", "超时处理方式",
            "启用命令/参数", "启动命令/参数", "完成判断", "等待关键词/进程名", "自动Enter秒",
            "并发组", "组完成策略", "守护监控", "目标进程关键词", "游戏窗口关键词", "高级"
        ])
        # v31.15：给两个高级监控列增加悬停说明，避免把进程名、窗口名混淆。
        self.table.horizontalHeaderItem(self.COL_PROCESS_KEYWORDS).setToolTip(
            "目标进程关键词：填写脚本拉起/等待/需要清理的目标程序。\n"
            "例如：Endfield.exe、OK-WW、BetterGI.exe。\n"
            "用于等待判断、超时清理、停止执行和紧急停止。"
        )
        self.table.horizontalHeaderItem(self.COL_WINDOW_KEYWORDS).setToolTip(
            "游戏窗口关键词：填写游戏窗口标题里的关键词。\n"
            "例如：Endfield、鸣潮、星穹铁道。\n"
            "用于窗口出现/消失判断；清理时会尝试按窗口 PID 兜底关闭。"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_PATH, QHeaderView.ResizeMode.Stretch)
        for col in [self.COL_BROWSE, self.COL_ORDER, self.COL_TIMEOUT, self.COL_ACTION, self.COL_USE_ARGS,
                    self.COL_ARGS, self.COL_WAIT_MODE, self.COL_WAIT_PROCESS, self.COL_CONFIRM_ENTER,
                    self.COL_CONCURRENT_GROUP, self.COL_CONCURRENT_POLICY, self.COL_WATCHDOG,
                    self.COL_PROCESS_KEYWORDS, self.COL_WINDOW_KEYWORDS, self.COL_ADVANCED]:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # v27.2：高级参数由任务标题右侧的全局开关展开，不再每行放一个按钮。
        # 默认基础表格保留“启用/名称/路径/顺序/超时/完成判断/等待关键词”等高频项；
        # 自动 Enter、并发组、组策略、守护/进程/窗口等高级项默认隐藏。
        # v31.12：任务级“超时截图”列已删除，超时截图只受全局设置控制。
        self.advanced_columns_visible = False
        self.advanced_task_columns = [
            self.COL_CONFIRM_ENTER,
            self.COL_CONCURRENT_GROUP,
            self.COL_CONCURRENT_POLICY,
            self.COL_WATCHDOG,
            self.COL_PROCESS_KEYWORDS,
            self.COL_WINDOW_KEYWORDS,
        ]
        self.table.setColumnHidden(self.COL_ADVANCED, True)
        self.task_advanced_toggle_button = QPushButton("进阶设置")
        self.task_advanced_toggle_button.setObjectName("TaskAdvancedToggleButton")
        self.task_advanced_toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_advanced_toggle_button.setFixedSize(96, 36)
        self.task_advanced_toggle_button.clicked.connect(lambda _checked=False: self.open_task_advanced_settings(0))
        # v28.3：添加/删除/上移/下移属于“任务执行”局部操作，
        # 从顶部全局控制栏移入任务详情标题栏，避免全局按钮过杂。
        if hasattr(self.task_card, "header_layout"):
            for local_btn in [self.add_button, self.delete_button, self.up_button, self.down_button]:
                local_btn.setFixedHeight(36)
                self.task_card.header_layout.insertWidget(3, local_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self.task_card.header_layout.insertWidget(7, self.task_advanced_toggle_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_task_advanced_columns_visible(False)
        self.task_card.content_layout.addWidget(self.table)

        stats_buttons_layout = QHBoxLayout()
        self.refresh_stats_button = QPushButton("刷新统计")
        self.open_stats_button = QPushButton("打开统计目录")
        stats_buttons_layout.addWidget(self.refresh_stats_button)
        stats_buttons_layout.addWidget(self.open_stats_button)
        stats_buttons_layout.addStretch(1)
        self.stats_table = QTableWidget(0, 5)
        self.stats_table.setHorizontalHeaderLabels(["脚本名称", "次数", "平均耗时", "最近耗时", "最近完成时间"])
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stats_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.stats_table.setAlternatingRowColors(True)
        stats_header = self.stats_table.horizontalHeader()
        stats_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            stats_header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_card.content_layout.addLayout(stats_buttons_layout)
        self.stats_card.content_layout.addWidget(self.stats_table)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_card.content_layout.addWidget(self.log_edit)

        # 右侧看板娘预留区：v14 先做静态占位，后续接入状态素材。
        self.mascot_panel = QGroupBox("雪乃酱")
        mascot_layout = QVBoxLayout(self.mascot_panel)
        self.mascot_label = QLabel("看板娘素材预留\nassets/mascot/")
        self.mascot_label.setObjectName("MascotImage")
        self.mascot_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.mascot_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.mascot_label.setMinimumWidth(260)
        self.mascot_label.setMinimumHeight(320)
        
        self.mascot_text_label = SpeechBubbleLabel("雪乃酱待命中，任务卡片已经准备好了。")
        self.mascot_text_label.setObjectName("MascotSpeechBubble")
        self.mascot_text_label.clicked.connect(self.on_mascot_bubble_clicked)
        # v18：当前状态放到看板娘上方，避免主界面横向占用空间。
        self.status_group.setMaximumHeight(78)
        mascot_layout.addWidget(self.status_group)
        mascot_layout.addWidget(self.mascot_text_label)
        mascot_layout.addWidget(self.mascot_label, stretch=1)
        self.main_splitter.addWidget(self.mascot_panel)
        self.main_splitter.setSizes([870, 360])

        self.expanded_card_key = None
        self._card_transition_running = False
        self._card_transition_queue = None
        # v20：彻底移除 QGraphicsOpacityEffect。
        # 父级透明动画会抓取子控件 pixmap，和自绘卡片/QPainter 容易冲突。
        # 卡片过渡先采用稳定的即时布局切换，后续如需复杂动画建议改 QGraphicsScene。
        self.collapse_cards(animated=False)
        # v28.8：看板娘只在“进入状态”时随机一次，不再 8 秒高频换姿态。
        # 这样 idle 两分钟也会保持同一张图，避免抢注意力。

        donation_layout = QHBoxLayout()
        self.author_link_button = QPushButton("联系作者")
        self.github_link_button = QPushButton("GitHub")
        self.about_link_button = QPushButton("关于 / 说明")
        for link_button in [self.author_link_button, self.github_link_button, self.about_link_button]:
            link_button.setFlat(True)
            link_button.setCursor(Qt.CursorShape.PointingHandCursor)
            link_button.setStyleSheet("QPushButton { color: #3367D6; text-decoration: underline; border: none; background: transparent; padding: 4px 8px; } QPushButton:hover { color: #174EA6; }")
            donation_layout.addWidget(link_button)
        donation_layout.addStretch(1)
        self.donation_button = QPushButton("☕ 赞赏支持 / Sponsor")
        self.donation_button.setStyleSheet("background-color: #FFD54F; color: #202124; font-weight: bold; padding: 8px 18px; border-radius: 6px;")
        donation_layout.addWidget(self.donation_button)
        donation_layout.addStretch(1)
        main_layout.addLayout(donation_layout)

        self._build_menu()

    def _clear_card_layout(self) -> None:
        """v25-alpha：保留兼容接口。卡片布局现在由 CardSceneWidget 管理。"""
        return

    def collapse_cards(self, animated: bool = True) -> None:
        """回到卡片总览。v25-alpha 使用场景式锚点布局，避免卡片素材被拉伸。"""
        self.expanded_card_key = None
        if hasattr(self, "card_area"):
            self.card_area.set_overview()
        if hasattr(self, "main_splitter"):
            self.main_splitter.setSizes([830, 390])
        self._update_mascot_for_card("overview")

    def expand_card(self, key: str) -> None:
        """展开指定卡片。详情页为半透明内容面板，其余卡片压到底部作为切换入口。"""
        if key not in getattr(self, "cards", {}):
            key = "tasks"
        self.expanded_card_key = key
        if hasattr(self, "card_area"):
            self.card_area.set_expanded(key)
        if hasattr(self, "main_splitter"):
            self.main_splitter.setSizes([900, 320])
        self._update_mascot_for_card(key)

    def _animate_card_layout_change(self, apply_layout_func) -> None:
        """v25-alpha：动画接口暂时保留；卡片系统先稳定锚点布局。"""
        apply_layout_func()

    def _play_startup_animation(self) -> None:
        """v20：启动动画暂时关闭，优先保证 Painter 稳定。"""
        return

    def _update_mascot_for_card(self, key: str) -> None:
        """卡片切换只更新低优先级提示；运行中/异常中不被主卡片说明打断。"""
        if getattr(self, "mascot_state", "idle") == "error" or self.is_running:
            return
        text_map = {
            "overview": "雪乃酱待命中～需要时可以展开卡片继续操作。",
            "tasks": "任务列表在这里。确认好之后，就可以开始执行啦。",
            "stats": "这里能看看最近的运行情况。",
            "logs": "运行记录会放在这里，出问题时再慢慢看就好。",
        }
        self._set_mascot_bubble(text_map.get(key, "雪乃酱待命中～"), priority=20, duration_seconds=8)
        if not self.is_running:
            self.set_mascot_state("idle", force=False)

    def _mascot_image_candidates(self, state: str) -> List[Path]:
        """返回某个状态可用的看板娘素材。"""
        mascot_dir = self.base_dir / "assets" / "mascot"
        state_aliases = {
            "idle": ["idle"],
            "rest": ["rest", "pause", "paused", "done", "finish", "finished"],
            "error": ["error", "err", "exception", "warning"],
            "work": ["work", "working", "run", "running", "gaming"],
        }
        aliases = state_aliases.get(state, [state])
        result: List[Path] = []
        for alias in aliases:
            folder = mascot_dir / alias
            if folder.exists():
                for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    result.extend(sorted(folder.glob(ext)))
            for ext in ("png", "jpg", "jpeg", "webp"):
                result.extend(sorted(mascot_dir.glob(f"{alias}_*.{ext}")))
                result.extend(sorted(mascot_dir.glob(f"{alias}*.{ext}")))
                single = mascot_dir / f"{alias}.{ext}"
                if single.exists():
                    result.append(single)
        seen = set()
        unique: List[Path] = []
        for path in result:
            key = str(path.resolve())
            if key not in seen and path.exists():
                seen.add(key)
                unique.append(path)
        return unique

    def _load_mascot_image(self, state: str, random_pick: bool = True) -> None:
        candidates = self._mascot_image_candidates(state)
        if not candidates and state != "idle":
            candidates = self._mascot_image_candidates("idle")
        if candidates:
            path = random.choice(candidates) if random_pick else candidates[0]
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                target_w = max(260, self.mascot_label.width() - 20)
                target_h = max(320, self.mascot_label.height() - 20)
                self.mascot_label.setPixmap(
                    pixmap.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                self.mascot_label.setText("")
                return
        self.mascot_label.setPixmap(QPixmap())
        self.mascot_label.setText(
            "看板娘素材预留\nassets/mascot/\n\n"
            "推荐：idle×3 / rest×3 / error×2 / work×2\n"
            "例如 assets/mascot/idle/idle_1.png"
        )

    def _default_mascot_text(self, state: str) -> str:
        text_map = {
            "idle": "雪乃酱待命中～",
            "work": random.choice([
                "正在执行中，我会帮你看着的。",
                "任务已经跑起来啦～先别急着关窗口哦。",
                "目前正在运行中，有问题我会提醒你的。",
                "雪乃酱正在确认运行状态。",
            ]),
            "rest": "现在先休息一下，需要时再继续吧。",
            "error": "这次运行好像遇到问题了，我先帮你标出来。",
        }
        return text_map.get(state, text_map["idle"])

    def _priority_for_mascot_state(self, state: str) -> int:
        return {"error": 100, "work": 70, "rest": 50, "guide": 30, "idle": 20}.get(state, 20)

    def _normalize_bubble_text(self, text: str) -> str:
        """统一兜底气泡文案，避免旧长句或说明书式文本撑破气泡。"""
        raw = str(text or "").strip()
        if not raw:
            return "雪乃酱待命中～"
        # 兼容旧版本残留的长引导句：统一替换成短句池。
        if "还未设置配置文件" in raw or "请在任务执行中设置配置" in raw or "左上角文件导入配置" in raw:
            guide_texts = getattr(self, "guide_bubble_texts", None)
            if guide_texts:
                return guide_texts[0]
            return "还没有配置任务哦～"
        # 气泡最多三行；异常详细内容应留在日志区，不直接塞进气泡。
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) > 3:
            raw = "\n".join(lines[:3])
        if len(raw) > 72:
            raw = raw[:69].rstrip("，。,. ") + "……"
        return raw

    def _set_mascot_bubble(self, text: str, *, priority: int, duration_seconds: int = 0, force: bool = False, bubble_kind: str = "normal") -> bool:
        """v31：统一气泡调度入口。低优先级不能覆盖高优先级。

        v31.3：bubble_kind="guide" 时，气泡可点击循环下一条引导短句。
        """
        if not force and priority < getattr(self, "bubble_priority", 0):
            return False
        self.bubble_priority = priority
        self.current_bubble_kind = bubble_kind
        if bubble_kind == "guide":
            self.mascot_text_label.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.mascot_text_label.unsetCursor()
        self.mascot_text_label.setText(self._normalize_bubble_text(text))
        if duration_seconds > 0:
            if self.bubble_restore_timer is None:
                self.bubble_restore_timer = QTimer(self)
                self.bubble_restore_timer.setSingleShot(True)
                self.bubble_restore_timer.timeout.connect(self._restore_mascot_message_after_success)
            self.bubble_restore_timer.start(max(1, int(duration_seconds) * 1000))
        return True

    def set_mascot_state(self, state: str, *, force: bool = False, error_reason: str = "") -> None:
        """切换看板娘状态；error 有锁定时间，避免一闪而过。"""
        valid_states = {"idle", "rest", "error", "work"}
        if state not in valid_states:
            state = "idle"

        now_ms = QDateTime.currentMSecsSinceEpoch()
        if self.mascot_state == "error" and state != "error" and not force:
            if now_ms < self.mascot_error_locked_until_ms:
                return

        if state == "error":
            self.mascot_error_count += 1
            lock_seconds = self.mascot_error_count * 15
            self.mascot_error_locked_until_ms = now_ms + lock_seconds * 1000
            if self.mascot_state != "error":
                self.mascot_last_non_error_state = self.mascot_state
            self.mascot_state = "error"
            self._load_mascot_image("error", random_pick=True)
            self._set_mascot_bubble(error_reason or self._default_mascot_text("error"), priority=100, force=True)
            self._schedule_mascot_error_release(lock_seconds)
            return

        if self.mascot_state == "error" and force:
            self.mascot_error_count = 0
            self.mascot_error_locked_until_ms = 0

        if self.mascot_state == state and not force:
            return
        self.mascot_state = state
        self.mascot_last_non_error_state = state
        self.bubble_priority = self._priority_for_mascot_state(state)
        self._load_mascot_image(state, random_pick=True)
        self._set_mascot_bubble(self._default_mascot_text(state), priority=self.bubble_priority, force=True)

    def show_temporary_mascot_message(self, text: str, duration_seconds: int = 10, priority: int = 30) -> None:
        """显示不会切换图片的临时气泡文案；通过优先级避免互相打断。"""
        if getattr(self, "mascot_state", "idle") == "error":
            return
        self._set_mascot_bubble(text, priority=priority, duration_seconds=duration_seconds)

    def _restore_mascot_message_after_success(self) -> None:
        if getattr(self, "mascot_state", "idle") == "error":
            return
        if self.is_running:
            self.bubble_priority = 70
            self.current_bubble_kind = "work"
            self.mascot_text_label.unsetCursor()
            self.mascot_text_label.setText(self._normalize_bubble_text(self._default_mascot_text("work")))
        else:
            self.bubble_priority = self._priority_for_mascot_state(getattr(self, "mascot_state", "idle"))
            self.current_bubble_kind = getattr(self, "mascot_state", "idle")
            self.mascot_text_label.unsetCursor()
            self.mascot_text_label.setText(self._normalize_bubble_text(self._default_mascot_text(getattr(self, "mascot_state", "idle"))))

    def has_usable_task_config(self) -> bool:
        """判断当前是否已经有可执行的任务配置。

        用于首次使用引导：只要表格/配置里还没有启用且脚本路径有效的任务，
        就认为用户仍需要导入或设置配置。
        """
        try:
            tasks = self.collect_tasks_from_table(sort_by_order=False)
        except Exception:
            tasks = list(getattr(self.config, "tasks", []) or [])
        for task in tasks:
            if not getattr(task, "enabled", True):
                continue
            script_path = str(getattr(task, "script_path", "") or "").strip()
            if script_path:
                return True
        return False

    def show_first_config_guide_if_needed(self, *, force: bool = False) -> None:
        """未导入/未设置配置时，用看板娘气泡给出轻量引导。

        guide 的优先级高于普通 idle/卡片说明，低于运行中、完成/暂停和异常。
        这样首次打开且未配置时，用户会先看到导入/配置提示；开始执行后则不会打断运行态。
        """
        if self.is_running or getattr(self, "mascot_state", "idle") == "error":
            return
        if self.has_usable_task_config():
            return
        guide_texts = getattr(self, "guide_bubble_texts", []) or ["还没有配置任务哦～"]
        self.guide_bubble_index = max(0, min(getattr(self, "guide_bubble_index", 0), len(guide_texts) - 1))
        self._set_mascot_bubble(
            guide_texts[self.guide_bubble_index],
            priority=30,
            duration_seconds=12,
            force=force,
            bubble_kind="guide",
        )

    def on_mascot_bubble_clicked(self) -> None:
        """v31.3：引导气泡期间，点击气泡循环播放下一条引导。"""
        if getattr(self, "current_bubble_kind", "") != "guide":
            return
        if self.is_running or getattr(self, "mascot_state", "idle") == "error":
            return
        if self.has_usable_task_config():
            return
        guide_texts = getattr(self, "guide_bubble_texts", []) or ["还没有配置任务哦～"]
        self.guide_bubble_index = (getattr(self, "guide_bubble_index", 0) + 1) % len(guide_texts)
        self._set_mascot_bubble(
            guide_texts[self.guide_bubble_index],
            priority=30,
            duration_seconds=12,
            force=True,
            bubble_kind="guide",
        )

    def _friendly_error_bubble_text(self, message: str) -> str:
        """把日志/异常内容转换成更像桌面助手的气泡文案。详细原因仍保留在日志区。"""
        raw = str(message or "").strip()
        clean = raw.split("] ", 1)[-1] if "] " in raw else raw
        task_match = re.search(r"任务「([^」]+)」", clean)
        task_part = f"任务「{task_match.group(1)}」" if task_match else "当前任务"

        if any(key in clean for key in ["启动失败", "构建启动命令失败", "脚本不存在", "脚本路径为空", "路径不是文件", "WinError 740", "请求的操作需要提升"]):
            return f"{task_part}没有顺利启动。雪乃酱先帮你标出来，详细原因可以看日志。"
        if any(key in clean for key in ["已超时", "超时", "强制结束"]):
            return f"{task_part}运行太久了，已经按设置处理。雪乃酱会先保持异常提示。"
        if any(key in clean for key in ["疑似过早退出", "提前退出", "过早退出"]):
            return f"{task_part}很快就退出了，可能没有正常跑完。详细情况在日志里。"
        if any(key in clean for key in ["未检测到", "判定为异常"]):
            return f"{task_part}没有检测到预期结果，雪乃酱先记为异常。"
        return f"{task_part}遇到异常了。雪乃酱先提示你，详细信息可以打开日志查看。"

    def _schedule_mascot_error_release(self, lock_seconds: int) -> None:
        if self.mascot_error_timer is None:
            self.mascot_error_timer = QTimer(self)
            self.mascot_error_timer.setSingleShot(True)
            self.mascot_error_timer.timeout.connect(self._release_mascot_error_if_due)
        self.mascot_error_timer.start(max(1, lock_seconds * 1000))

    def _release_mascot_error_if_due(self) -> None:
        now_ms = QDateTime.currentMSecsSinceEpoch()
        if self.mascot_state != "error":
            return
        remaining_ms = self.mascot_error_locked_until_ms - now_ms
        if remaining_ms > 0:
            self.mascot_error_timer.start(max(1, remaining_ms))
            return
        next_state = "work" if self.is_running else "rest"
        self.set_mascot_state(next_state, force=True)

    def _start_mascot_random_timer(self) -> None:
        """v28.8：兼容旧接口。

        看板娘现在采用“进入状态时随机一次”的低干扰策略，
        不再用定时器持续换图；否则 idle 时会一直动，反而抢注意力。
        """
        if self.mascot_random_timer is not None:
            self.mascot_random_timer.stop()

    def _refresh_mascot_random_image(self) -> None:
        """保留调试入口：手动调用时才随机刷新当前状态图。"""
        if self.mascot_state == "error":
            return
        self._load_mascot_image(self.mascot_state, random_pick=True)

    def _set_layout_visible(self, layout, visible: bool) -> None:
        """递归设置布局内控件可见性，用于可折叠区域。"""
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.setVisible(visible)
            if child_layout is not None:
                self._set_layout_visible(child_layout, visible)

    def _make_group_collapsible(self, group: QGroupBox) -> None:
        """让 QGroupBox 点击标题即可展开/收起。"""
        base_title = group.title().replace("▼ ", "").replace("▶ ", "")
        group.setCheckable(True)
        group.setChecked(True)
        group.setTitle(f"▼ {base_title}")

        def on_toggled(checked: bool) -> None:
            group.setTitle(f"{'▼' if checked else '▶'} {base_title}")
            layout = group.layout()
            if layout is not None:
                self._set_layout_visible(layout, checked)
            if checked:
                group.setMaximumHeight(16777215)
            else:
                # 保留标题栏高度，使用户可以再次点击展开。
                group.setMaximumHeight(44)

        group.toggled.connect(on_toggled)

    def _build_menu(self) -> None:
        """v28.3：弱化传统菜单栏，把“文件”入口合并到顶部控制条。"""
        file_menu = QMenu(self)

        save_action = QAction("保存配置", self)
        save_action.triggered.connect(self.save_config_from_ui)
        file_menu.addAction(save_action)

        export_action = QAction("导出配置", self)
        export_action.triggered.connect(self.export_config)
        file_menu.addAction(export_action)

        import_action = QAction("导入配置", self)
        import_action.triggered.connect(self.import_config)
        file_menu.addAction(import_action)

        # 发布前用户模式：隐藏 UI 参数导入/导出，避免暴露开发调参入口。
        file_menu.addSeparator()

        open_config_action = QAction("打开配置所在目录", self)
        open_config_action.triggered.connect(lambda: self.open_directory(self.base_dir))
        file_menu.addAction(open_config_action)

        open_log_action = QAction("打开日志目录", self)
        open_log_action.triggered.connect(lambda: self.open_directory(self.file_logger.log_dir))
        file_menu.addAction(open_log_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.file_button.setMenu(file_menu)
        self.menuBar().hide()

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self.add_task)
        self.delete_button.clicked.connect(self.delete_selected_task)
        self.up_button.clicked.connect(self.move_selected_task_up)
        self.down_button.clicked.connect(self.move_selected_task_down)
        self.save_button.clicked.connect(self.save_config_from_ui)
        self.start_button.clicked.connect(self.start_tasks)
        self.resume_button.clicked.connect(self.resume_tasks)
        self.pause_button.clicked.connect(self.pause_tasks)
        self.stop_button.clicked.connect(self.stop_tasks)
        self.emergency_stop_button.clicked.connect(self.emergency_stop_tasks)
        self.settings_button.clicked.connect(self.show_settings_dialog)
        self.layout_tuner_button.clicked.connect(self.show_layout_tuner)
        self.theme_combo.currentIndexChanged.connect(self.on_theme_combo_changed)
        self.cancel_shutdown_button.clicked.connect(self.cancel_shutdown)
        self._setup_shortcuts()
        self.export_config_button.clicked.connect(self.export_config)
        self.import_config_button.clicked.connect(self.import_config)
        self.export_ui_params_button.clicked.connect(self.export_ui_params)
        self.import_ui_params_button.clicked.connect(self.import_ui_params)
        self.refresh_stats_button.clicked.connect(self.refresh_runtime_stats_view)
        self.open_stats_button.clicked.connect(lambda: self.open_directory(self.base_dir / "runtime_stats"))
        self.donation_button.clicked.connect(self.show_donation_dialog)
        self.author_link_button.clicked.connect(lambda: self.open_external_url(AUTHOR_URL))
        self.github_link_button.clicked.connect(lambda: self.open_external_url(GITHUB_URL))
        self.about_link_button.clicked.connect(self.open_local_documentation)

    def show_layout_tuner(self) -> None:
        """打开 v25 内部卡片布局调参器。"""
        if hasattr(self, "card_area") and hasattr(self.card_area, "open_layout_tuner"):
            self.card_area.open_layout_tuner()
        else:
            self._show_themed_message("布局调参", "当前卡片区域不支持布局调参。")

    def show_settings_dialog(self) -> None:
        """打开全局设置弹窗。"""
        self.settings_dialog.resize(980, 320)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self, activated=self.start_tasks)
        QShortcut(QKeySequence("F6"), self, activated=self.resume_tasks)
        QShortcut(QKeySequence("F7"), self, activated=self.pause_tasks)
        QShortcut(QKeySequence("F8"), self, activated=self.stop_tasks)
        QShortcut(QKeySequence("Ctrl+Alt+F8"), self, activated=self.emergency_stop_tasks)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        self.append_log("快捷键：F5启动，F6继续，F7暂停，F8停止执行，Ctrl+Alt+F8紧急停止全部，Ctrl+Q关闭程序。")

    def _load_config_to_ui(self) -> None:
        self.shutdown_checkbox.setChecked(self.config.shutdown_after_done)
        self.shutdown_delay_spin.setValue(self.config.shutdown_delay_seconds)
        self.auto_exit_checkbox.setChecked(self.config.auto_exit_after_done)
        self.auto_start_tasks_checkbox.setChecked(self.config.auto_start_tasks)
        self.windows_startup_checkbox.setChecked(self.config.windows_startup)
        self.timeout_screenshot_checkbox.setChecked(getattr(self.config, "enable_timeout_screenshot", False))
        self.reload_table(self.config.tasks)

    def refresh_runtime_stats_view(self) -> None:
        """在 UI 中用表格展示历史耗时统计，避免长脚本名导致列对齐错乱。"""
        try:
            summary_path = self.base_dir / "runtime_stats" / "runtime_summary.json"
            if not summary_path.exists():
                self.stats_table.setRowCount(0)
                return
            with summary_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                self.stats_table.setRowCount(0)
                return

            rows = []
            for name, item in data.items():
                if not isinstance(item, dict):
                    continue
                rows.append((
                    str(name),
                    int(item.get("count", 0)),
                    int(float(item.get("average_seconds", 0))),
                    int(item.get("last_seconds", 0)),
                    str(item.get("last_time", "")),
                ))
            rows.sort(key=lambda x: x[0].lower())

            self.stats_table.setRowCount(len(rows))
            for row, (name, count, avg, last, last_time) in enumerate(rows):
                values = [name, str(count), format_seconds(avg), format_seconds(last), last_time]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col in {1, 2, 3}:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.stats_table.setItem(row, col, item)
            self.stats_table.resizeRowsToContents()
        except Exception as exc:
            self.stats_table.setRowCount(1)
            self.stats_table.setItem(0, 0, QTableWidgetItem(f"读取统计失败：{exc}"))

    def append_log(self, message: str, already_formatted: bool = False) -> None:
        if already_formatted:
            line = message
            self.file_logger.write_line(line)
        else:
            line = self.file_logger.log(message)

        self.log_edit.append(line)
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_edit.setTextCursor(cursor)

    def add_task(self) -> None:
        tasks = self.collect_tasks_from_table(sort_by_order=False)
        next_order = len(tasks) + 1
        tasks.append(
            TaskConfig(
                enabled=True,
                name=f"新任务{next_order}",
                script_path="",
                order=next_order,
                timeout_minutes=30,
                timeout_action="kill_and_continue",
                use_args=False,
                args="",
                wait_mode="direct_process",
                wait_process_name="",
                confirm_enter_delay_seconds=0,
                concurrent_group="",
                concurrent_policy="wait_all",
                enable_watchdog=False,
                process_keywords=[],
                window_keywords=[],
            )
        )
        self.reload_table(tasks)
        self.table.selectRow(len(tasks) - 1)

    def delete_selected_task(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self._show_themed_message("提示", "请先选择要删除的任务。")
            return

        task_name = self._item_text(row, self.COL_NAME, default=f"第 {row + 1} 行")
        if not self._ask_themed_yes_no("确认删除", f"确定删除任务「{task_name}」吗？"):
            return

        tasks = self.collect_tasks_from_table(sort_by_order=False)
        if 0 <= row < len(tasks):
            tasks.pop(row)
        self._normalize_orders(tasks)
        self.reload_table(tasks)

    def move_selected_task_up(self) -> None:
        row = self.table.currentRow()
        if row <= 0:
            return

        tasks = self.collect_tasks_from_table(sort_by_order=False)
        tasks[row - 1], tasks[row] = tasks[row], tasks[row - 1]
        self._normalize_orders(tasks)
        self.reload_table(tasks)
        self.table.selectRow(row - 1)

    def move_selected_task_down(self) -> None:
        row = self.table.currentRow()
        tasks = self.collect_tasks_from_table(sort_by_order=False)
        if row < 0 or row >= len(tasks) - 1:
            return

        tasks[row + 1], tasks[row] = tasks[row], tasks[row + 1]
        self._normalize_orders(tasks)
        self.reload_table(tasks)
        self.table.selectRow(row + 1)


    def _apply_frozen_identity_cell_style(self, item: Optional[QTableWidgetItem]) -> None:
        """给冻结定位列一个很轻的底色，避免靠粗边框区分。"""
        if item is None:
            return
        item.setBackground(QColor(246, 250, 255, 235))

    def reload_table(self, tasks: List[TaskConfig]) -> None:
        self.table.setRowCount(0)

        tasks_to_show = list(tasks)
        tasks_to_show.sort(key=lambda task: task.order)

        for row, task in enumerate(tasks_to_show):
            self.table.insertRow(row)
            self._set_task_row(row, task)

        self._normalize_order_cells()

    def _set_task_row(self, row: int, task: TaskConfig) -> None:
        enabled_item = QTableWidgetItem("")
        enabled_item.setFlags(enabled_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled_item.setCheckState(Qt.CheckState.Checked if task.enabled else Qt.CheckState.Unchecked)
        enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_frozen_identity_cell_style(enabled_item)
        self.table.setItem(row, self.COL_ENABLED, enabled_item)

        name_item = QTableWidgetItem(task.name)
        self._apply_frozen_identity_cell_style(name_item)
        self.table.setItem(row, self.COL_NAME, name_item)

        path_item = QTableWidgetItem(task.script_path)
        self.table.setItem(row, self.COL_PATH, path_item)

        browse_button = QPushButton("选择")
        browse_button.clicked.connect(lambda _checked=False, r=row: self.browse_script_for_row(r))
        self.table.setCellWidget(row, self.COL_BROWSE, browse_button)

        order_item = QTableWidgetItem(str(task.order))
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_ORDER, order_item)

        timeout_item = QTableWidgetItem(str(task.timeout_minutes))
        timeout_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_TIMEOUT, timeout_item)

        action_combo = QComboBox()
        for value, label in TIMEOUT_ACTIONS.items():
            action_combo.addItem(label, value)
        index = action_combo.findData(task.timeout_action)
        if index < 0:
            index = action_combo.findData("kill_and_continue")
        action_combo.setCurrentIndex(index)
        self.table.setCellWidget(row, self.COL_ACTION, action_combo)

        use_args_item = QTableWidgetItem("")
        use_args_item.setFlags(use_args_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        use_args_item.setCheckState(Qt.CheckState.Checked if task.use_args else Qt.CheckState.Unchecked)
        use_args_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_USE_ARGS, use_args_item)

        args_item = QTableWidgetItem(task.args)
        self.table.setItem(row, self.COL_ARGS, args_item)

        wait_combo = QComboBox()
        for value, label in WAIT_MODES.items():
            wait_combo.addItem(label, value)
        wait_index = wait_combo.findData(task.wait_mode)
        if wait_index < 0:
            wait_index = wait_combo.findData("direct_process")
        wait_combo.setCurrentIndex(wait_index)
        self.table.setCellWidget(row, self.COL_WAIT_MODE, wait_combo)

        wait_process_item = QTableWidgetItem(task.wait_process_name)
        self.table.setItem(row, self.COL_WAIT_PROCESS, wait_process_item)

        confirm_item = QTableWidgetItem(str(task.confirm_enter_delay_seconds))
        confirm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_CONFIRM_ENTER, confirm_item)

        concurrent_group_item = QTableWidgetItem(task.concurrent_group)
        concurrent_group_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_CONCURRENT_GROUP, concurrent_group_item)

        concurrent_policy_combo = QComboBox()
        for value, label in CONCURRENT_POLICIES.items():
            concurrent_policy_combo.addItem(label, value)
        policy_index = concurrent_policy_combo.findData(task.concurrent_policy)
        if policy_index < 0:
            policy_index = concurrent_policy_combo.findData("wait_all")
        concurrent_policy_combo.setCurrentIndex(policy_index)
        self.table.setCellWidget(row, self.COL_CONCURRENT_POLICY, concurrent_policy_combo)

        watchdog_item = QTableWidgetItem("")
        watchdog_item.setFlags(watchdog_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        watchdog_item.setCheckState(Qt.CheckState.Checked if task.enable_watchdog else Qt.CheckState.Unchecked)
        watchdog_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_WATCHDOG, watchdog_item)

        self.table.setItem(row, self.COL_PROCESS_KEYWORDS, QTableWidgetItem(keywords_to_text(task.process_keywords)))
        self.table.setItem(row, self.COL_WINDOW_KEYWORDS, QTableWidgetItem(keywords_to_text(task.window_keywords)))

        # v27.2：高级列由标题右侧全局按钮统一展开/收起；每行不再放按钮。
        self.table.setItem(row, self.COL_ADVANCED, QTableWidgetItem(""))
        self.table.setColumnHidden(self.COL_ADVANCED, True)
        for col in getattr(self, "advanced_task_columns", []):
            self.table.setColumnHidden(col, not getattr(self, "advanced_columns_visible", False))


    def set_task_advanced_columns_visible(self, visible: bool) -> None:
        """显示/隐藏任务表格的高级运行列。"""
        self.advanced_columns_visible = visible
        for col in getattr(self, "advanced_task_columns", []):
            self.table.setColumnHidden(col, not visible)

        button_text = "收起进阶" if visible else "进阶设置"
        if hasattr(self, "task_advanced_toggle_button"):
            self.task_advanced_toggle_button.setText(button_text)

        # 展开后给长文本列更多空间，并自动拉到最右侧；收起时恢复紧凑。
        header = self.table.horizontalHeader()
        if visible:
            header.setSectionResizeMode(self.COL_PROCESS_KEYWORDS, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(self.COL_PROCESS_KEYWORDS, 170)
            header.setSectionResizeMode(self.COL_WINDOW_KEYWORDS, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(self.COL_WINDOW_KEYWORDS, 170)
            QTimer.singleShot(0, lambda: self.table.horizontalScrollBar().setValue(self.table.horizontalScrollBar().maximum()))
        else:
            header.setSectionResizeMode(self.COL_PROCESS_KEYWORDS, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(self.COL_WINDOW_KEYWORDS, QHeaderView.ResizeMode.ResizeToContents)
        if hasattr(self.table, "_sync_frozen_columns"):
            self.table._sync_frozen_columns()

    def open_task_advanced_settings(self, row: int) -> None:
        """v27.2：标题右侧全局开关控制高级列展开/收起。"""
        if row < 0 or row >= self.table.rowCount():
            return
        self.set_task_advanced_columns_visible(not getattr(self, "advanced_columns_visible", False))

    def browse_script_for_row(self, row: int) -> None:
        if row < 0 or row >= self.table.rowCount():
            return

        current_path = self._item_text(row, self.COL_PATH, default="")
        start_dir = str(Path(current_path).parent) if current_path and Path(current_path).parent.exists() else str(self.base_dir)

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择脚本文件",
            start_dir,
            "脚本文件 (*.bat *.cmd *.exe *.py);;所有文件 (*.*)",
        )
        if not path:
            return

        item = self.table.item(row, self.COL_PATH)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, self.COL_PATH, item)
        item.setText(path)

    def collect_tasks_from_table(self, sort_by_order: bool = True) -> List[TaskConfig]:
        tasks: List[TaskConfig] = []

        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, self.COL_ENABLED)
            enabled = enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True

            name = self._item_text(row, self.COL_NAME, default=f"任务{row + 1}").strip()
            script_path = self._item_text(row, self.COL_PATH, default="").strip()
            order = safe_int(self._item_text(row, self.COL_ORDER, default=str(row + 1)), row + 1, 1)
            timeout_minutes = safe_int(self._item_text(row, self.COL_TIMEOUT, default="30"), 30, 0)
            use_args_item = self.table.item(row, self.COL_USE_ARGS)
            use_args = use_args_item.checkState() == Qt.CheckState.Checked if use_args_item else False
            args = self._item_text(row, self.COL_ARGS, default="").strip()
            wait_process_name = self._item_text(row, self.COL_WAIT_PROCESS, default="").strip()
            confirm_enter_delay_seconds = safe_int(self._item_text(row, self.COL_CONFIRM_ENTER, default="0"), 0, 0)
            concurrent_group = self._item_text(row, self.COL_CONCURRENT_GROUP, default="").strip()
            watchdog_item = self.table.item(row, self.COL_WATCHDOG)
            enable_watchdog = watchdog_item.checkState() == Qt.CheckState.Checked if watchdog_item else False
            process_keywords = normalize_keywords(self._item_text(row, self.COL_PROCESS_KEYWORDS, default=""))
            window_keywords = normalize_keywords(self._item_text(row, self.COL_WINDOW_KEYWORDS, default=""))
            concurrent_policy_combo = self.table.cellWidget(row, self.COL_CONCURRENT_POLICY)
            concurrent_policy = "wait_all"
            if isinstance(concurrent_policy_combo, QComboBox):
                value = concurrent_policy_combo.currentData()
                if isinstance(value, str) and value in CONCURRENT_POLICIES:
                    concurrent_policy = value

            wait_combo = self.table.cellWidget(row, self.COL_WAIT_MODE)
            wait_mode = "direct_process"
            if isinstance(wait_combo, QComboBox):
                value = wait_combo.currentData()
                if isinstance(value, str) and value in WAIT_MODES:
                    wait_mode = value

            combo = self.table.cellWidget(row, self.COL_ACTION)
            timeout_action = "kill_and_continue"
            if isinstance(combo, QComboBox):
                value = combo.currentData()
                if isinstance(value, str) and value in TIMEOUT_ACTIONS:
                    timeout_action = value

            tasks.append(
                TaskConfig(
                    enabled=enabled,
                    name=name or f"任务{row + 1}",
                    script_path=script_path,
                    order=order,
                    timeout_minutes=timeout_minutes,
                    timeout_action=timeout_action,
                    use_args=use_args,
                    args=args,
                    wait_mode=wait_mode,
                    wait_process_name=wait_process_name,
                    confirm_enter_delay_seconds=confirm_enter_delay_seconds,
                    concurrent_group=concurrent_group,
                    concurrent_policy=concurrent_policy,
                    enable_watchdog=enable_watchdog,
                    process_keywords=process_keywords,
                    window_keywords=window_keywords,
                )
            )

        if sort_by_order:
            tasks.sort(key=lambda task: task.order)
            self._normalize_orders(tasks)

        return tasks

    def _item_text(self, row: int, col: int, default: str = "") -> str:
        item = self.table.item(row, col)
        if item is None:
            return default
        return item.text()

    def _normalize_orders(self, tasks: List[TaskConfig]) -> None:
        for index, task in enumerate(tasks, start=1):
            task.order = index

    def _normalize_order_cells(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_ORDER)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, self.COL_ORDER, item)
            item.setText(str(row + 1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def save_config_from_ui(self) -> None:
        tasks = self.collect_tasks_from_table(sort_by_order=True)
        self.config.tasks = tasks
        self.config.shutdown_after_done = self.shutdown_checkbox.isChecked()
        self.config.shutdown_delay_seconds = int(self.shutdown_delay_spin.value())
        self.config.auto_exit_after_done = self.auto_exit_checkbox.isChecked()
        self.config.auto_start_tasks = self.auto_start_tasks_checkbox.isChecked()
        self.config.windows_startup = self.windows_startup_checkbox.isChecked()
        self.config.auto_start_tasks = self.auto_start_tasks_checkbox.isChecked()
        self.config.windows_startup = self.windows_startup_checkbox.isChecked()
        self.config.enable_timeout_screenshot = self.timeout_screenshot_checkbox.isChecked()
        self._apply_windows_startup(self.config.windows_startup)

        # 保存时同步表格顺序，避免 order 字段和显示顺序不一致。
        self.reload_table(tasks)

        try:
            self.config_manager.save(self.config)
            self.append_log("配置已保存。")
        except Exception as exc:
            self._show_themed_message("保存失败", f"保存配置失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"保存配置失败：{exc}")

    def start_tasks(self) -> None:
        if self.is_running:
            return

        self.save_config_from_ui()

        tasks = self.collect_tasks_from_table(sort_by_order=True)
        enabled_count = sum(1 for task in tasks if task.enabled)
        if enabled_count == 0:
            self._show_themed_message("提示", "当前没有启用的任务。")
            self.show_first_config_guide_if_needed()
            return

        if not self.has_usable_task_config():
            self._show_themed_message("提示", "还没有设置可执行的脚本配置。")
            self.show_first_config_guide_if_needed()
            return

        self.config.tasks = tasks
        self.config.shutdown_after_done = self.shutdown_checkbox.isChecked()
        self.config.shutdown_delay_seconds = int(self.shutdown_delay_spin.value())
        self.config.auto_exit_after_done = self.auto_exit_checkbox.isChecked()
        self.config.auto_start_tasks = self.auto_start_tasks_checkbox.isChecked()
        self.config.windows_startup = self.windows_startup_checkbox.isChecked()
        self.config.auto_start_tasks = self.auto_start_tasks_checkbox.isChecked()
        self.config.windows_startup = self.windows_startup_checkbox.isChecked()
        self.config.enable_timeout_screenshot = self.timeout_screenshot_checkbox.isChecked()
        self._apply_windows_startup(self.config.windows_startup)

        self.is_running = True
        self.run_task_error_count = 0
        self.set_controls_running(True)
        self.status_value_label.setText("启动确认中")
        self.set_mascot_state("work", force=True)
        self.show_temporary_mascot_message("正在启动任务，我会先帮你确认状态。", 8, priority=75)
        self.task_value_label.setText("-")
        self.elapsed_value_label.setText("00:00")
        self.progress_value_label.setText(f"0 / {enabled_count}")

        self.runner_thread = QThread(self)
        self.runner_worker = ScriptRunnerWorker(
            tasks=tasks,
            shutdown_after_done=self.config.shutdown_after_done,
            shutdown_delay_seconds=self.config.shutdown_delay_seconds,
            logger=self.file_logger,
            stats_manager=self.stats_manager,
            enable_timeout_screenshot=getattr(self.config, "enable_timeout_screenshot", False),
        )
        self.runner_worker.moveToThread(self.runner_thread)

        self.runner_thread.started.connect(self.runner_worker.run)
        self.runner_worker.log_signal.connect(self.on_worker_log)
        self.runner_worker.status_signal.connect(self.on_worker_status)
        self.runner_worker.progress_signal.connect(self.on_worker_progress)
        self.runner_worker.task_started_signal.connect(self.on_worker_task_started)
        self.runner_worker.elapsed_signal.connect(self.on_worker_elapsed)
        self.runner_worker.shutdown_prompt_signal.connect(self.show_shutdown_warning_dialog)
        self.runner_worker.task_error_signal.connect(self.on_worker_task_error)
        self.runner_worker.task_launch_success_signal.connect(self.on_worker_task_launch_success)
        self.runner_worker.finished_signal.connect(self.on_worker_finished)

        self.runner_worker.finished_signal.connect(self.runner_thread.quit)
        self.runner_thread.finished.connect(self.runner_worker.deleteLater)
        self.runner_thread.finished.connect(self.runner_thread.deleteLater)

        self.runner_thread.start()
        self.append_log("后台执行线程已启动。")

    def pause_tasks(self) -> None:
        if not self.is_running or self.runner_worker is None:
            return
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)
        self.status_value_label.setText("已暂停")
        self.set_mascot_state("rest")
        self.show_temporary_mascot_message("先暂停一下吧，我在这里等你回来。", 10, priority=55)
        self.runner_worker.request_pause()

    def resume_tasks(self) -> None:
        if not self.is_running or self.runner_worker is None:
            return
        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.status_value_label.setText("运行中")
        self.set_mascot_state("work")
        self.runner_worker.request_resume()

    def stop_tasks(self) -> None:
        if not self.is_running or self.runner_worker is None:
            return

        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.status_value_label.setText("正在停止执行")
        self.set_mascot_state("rest")
        self.show_temporary_mascot_message("收到停止指令啦，我会帮你收尾当前任务。", 10, priority=55)
        self.append_log("用户点击停止执行。")
        self.runner_worker.request_stop()

    def emergency_stop_tasks(self) -> None:
        if not self._ask_themed_yes_no(
            "确认紧急停止",
            "紧急停止会扫描所有任务配置，并按以下顺序强制收尾：\n"
            "1. 启动脚本进程 / launched script\n"
            "2. 目标进程 / target process\n"
            "3. 游戏窗口 / 扩展进程\n"
            "4. 游戏窗口关键词对应 PID 兜底清理\n\n"
            "确定要执行紧急停止吗？",
            QMessageBox.Icon.Warning,
        ):
            return

        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.emergency_stop_button.setEnabled(False)
        self.status_value_label.setText("紧急停止中")
        self.set_mascot_state("rest")
        self.show_temporary_mascot_message("正在紧急停止，我会尽量把相关进程一起处理掉。", 12, priority=95)
        self.append_log("用户触发紧急停止全部。")
        if self.runner_worker is not None:
            self.runner_worker.request_emergency_stop()
        else:
            self.append_log("当前没有正在运行的调度任务，紧急停止仅记录日志。")

    @Slot(str)
    def on_worker_log(self, line: str) -> None:
        self.log_edit.append(line)
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_edit.setTextCursor(cursor)

        # v31.10：收紧兜底 error 识别。
        # 之前这里用关键词粗扫日志，会把“已登记可强制结束的同名进程”误判为 error，
        # 导致任务正常运行时看板娘也切到 error。现在只保留真正明确的执行失败类日志。
        error_keywords = [
            "启动失败", "构建启动命令失败", "脚本不存在", "脚本路径为空",
            "路径不是文件", "请求的操作需要提升", "WinError 740",
            "执行器发生异常", "保存异常报告失败",
            "强制结束失败", "kill 失败", "终止失败",
            "紧急停止失败", "关闭失败",
        ]
        timeout_error_markers = [
            "已超时",
            "超时：正在强制结束",
        ]
        if any(keyword in line for keyword in error_keywords) or any(keyword in line for keyword in timeout_error_markers):
            self._record_abnormal_report(line)
            self.set_mascot_state("error", error_reason=self._friendly_error_bubble_text(line))

    @Slot(str)
    def on_worker_task_launch_success(self, task_name: str) -> None:
        # 启动真正确认成功后，自动回到卡片主界面；失败则不会触发这个信号，因此保留在当前详情页。
        if getattr(self, "mascot_state", "idle") == "error":
            return
        self.status_value_label.setText("运行中")
        self.set_mascot_state("work", force=True)
        self.collapse_cards(animated=True)
        self.show_temporary_mascot_message("启动成功啦～接下来我会帮你盯着进度。", 10, priority=80)

    @Slot(str)
    def on_worker_task_error(self, message: str) -> None:
        self.run_task_error_count += 1
        self._record_abnormal_report(message)
        self.set_mascot_state("error", error_reason=self._friendly_error_bubble_text(message))

    @Slot(str)
    def on_worker_status(self, status: str) -> None:
        self.status_value_label.setText(status)
        if any(keyword in status for keyword in ["异常", "错误", "失败", "报错"]):
            self.set_mascot_state("error", error_reason="当前状态出现异常。雪乃酱会先停留在提示状态，方便你查看。")
        elif status in ["已暂停", "已停止", "已完成", "超时处理中"]:
            self.set_mascot_state("rest")
        elif "运行" in status:
            self.set_mascot_state("work")

    @Slot(int, int)
    def on_worker_progress(self, current: int, total: int) -> None:
        self.current_progress = (current, total)
        self.progress_value_label.setText(f"{current} / {total}")

    @Slot(str, int, int)
    def on_worker_task_started(self, task_name: str, index: int, total: int) -> None:
        self.current_task_name = task_name
        self.current_elapsed = 0
        self.task_value_label.setText(task_name)
        self.elapsed_value_label.setText("00:00")
        self.progress_value_label.setText(f"{index} / {total}")

    @Slot(int)
    def on_worker_elapsed(self, elapsed: int) -> None:
        self.current_elapsed = elapsed
        self.elapsed_value_label.setText(format_seconds(elapsed))

    @Slot(bool)
    def on_worker_finished(self, stopped_or_error: bool) -> None:
        self.is_running = False
        self.set_controls_running(False)
        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.emergency_stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        # 断开引用，避免重复 stop。
        self.runner_worker = None
        self.runner_thread = None

        if stopped_or_error:
            # v28.9：普通手动停止仍然进入 rest；任务级异常则保留/触发 error。
            current_status = self.status_value_label.text()
            if "停止" in current_status and self.mascot_state != "error":
                self.status_value_label.setText("已停止")
                self.set_mascot_state("rest")
                self.show_temporary_mascot_message("已经按你的要求停止啦，后续任务不会继续执行。", 12, priority=60)
            else:
                self.status_value_label.setText("已完成（有异常）")
                count = max(1, int(getattr(self, "run_task_error_count", 0)))
                msg = f"任务结束，发生了 {count} 次任务异常。"
                self._record_abnormal_report(msg)
                self.set_mascot_state("error", error_reason=msg)
        else:
            self.status_value_label.setText("已完成")
            self.set_mascot_state("rest")
            self.show_temporary_mascot_message("任务已经顺利完成啦～这轮工作收好啦。", 12, priority=60)

        self.refresh_runtime_stats_view()

        if self.config.auto_exit_after_done and not stopped_or_error:
            self.append_log("已启用任务完成后自动退出程序，程序即将退出。")
            QTimer.singleShot(1500, QApplication.instance().quit)

    def set_controls_running(self, running: bool) -> None:
        self.add_button.setEnabled(not running)
        self.delete_button.setEnabled(not running)
        self.up_button.setEnabled(not running)
        self.down_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(running)
        self.stop_button.setEnabled(running)
        self.emergency_stop_button.setEnabled(running)
        self.table.setEnabled(not running)
        self.shutdown_checkbox.setEnabled(not running)
        self.shutdown_delay_spin.setEnabled(not running)
        self.auto_exit_checkbox.setEnabled(not running)
        self.auto_start_tasks_checkbox.setEnabled(not running)
        self.windows_startup_checkbox.setEnabled(not running)
        self.timeout_screenshot_checkbox.setEnabled(not running)
        self.settings_button.setEnabled(True)
        self.cancel_shutdown_button.setEnabled(True)
        self.export_config_button.setEnabled(not running)
        self.import_config_button.setEnabled(not running)
        self.export_ui_params_button.setEnabled(not running)
        self.import_ui_params_button.setEnabled(not running)
        self.refresh_stats_button.setEnabled(True)
        self.open_stats_button.setEnabled(True)

    def toggle_theme(self) -> None:
        order = ["light", "dark", "yukino", "campus", "fresh", "fantasy"]
        current = self.config.theme if self.config.theme in order else "yukino"
        new_theme = order[(order.index(current) + 1) % len(order)]
        self.config.theme = new_theme
        self.apply_theme(new_theme)
        try:
            self.save_config_from_ui()
        except Exception:
            pass

    def on_theme_combo_changed(self) -> None:
        theme = self.theme_combo.currentData()
        if not theme:
            return
        if getattr(self, "_applying_theme", False):
            return
        self.config.theme = str(theme)
        self.apply_theme(str(theme))
        try:
            self.save_config_from_ui()
        except Exception:
            pass

    def _theme_asset_folder(self, theme: str) -> str:
        """v18：主题名到资源目录的映射。"""
        if theme == "yukino":
            return "classic"
        if theme == "fantasy":
            return "warm"
        if theme in {"campus", "fresh"}:
            return theme
        # 浅色/深色暂时复用经典背景；没有图片时自动回退纯色。
        return "classic"

    def _asset_path(self, *parts) -> Path:
        return self.base_dir / "assets" / Path(*parts)

    def _existing_asset_path(self, *parts) -> Path | None:
        path = self._asset_path(*parts)
        return path if path.exists() else None

    def apply_theme(self, theme: str) -> None:
        palettes = {
            "light": {
                "name": "浅色", "bg": "#F7F7F7", "fg": "#202124", "panel": "#FFFFFF", "panel2": "#F4F7FC",
                "border": "#DDE7F2", "accent": "#6C8EBF", "accent2": "#8FAADE", "muted": "#5B6475",
                "button": "#FFFFFF", "button_hover": "#EFEFEF", "table": "#FFFFFF", "header": "#ECECEC",
                "select": "#D9E7FF", "danger": "#B3261E", "danger2": "#8B0000",
            },
            "dark": {
                "name": "深色", "bg": "#202124", "fg": "#E8EAED", "panel": "#252932", "panel2": "#2A2D35",
                "border": "#5B6F9A", "accent": "#6C8EBF", "accent2": "#8FAADE", "muted": "#B7C7E6",
                "button": "#303134", "button_hover": "#3C4043", "table": "#17181B", "header": "#303134",
                "select": "#3C4043", "danger": "#B3261E", "danger2": "#8B0000",
            },
            "yukino": {
                "name": "经典风", "bg": "#F4F7FC", "fg": "#203648", "panel": "#FFFFFF", "panel2": "#EEF4FF",
                "border": "#B7C7E6", "accent": "#6C8EBF", "accent2": "#8FAADE", "muted": "#5B6475",
                "button": "#EAF1FB", "button_hover": "#DCE9FF", "table": "#FFFFFF", "header": "#E8F0FF",
                "select": "#D8E8FF", "danger": "#B3261E", "danger2": "#8B0000",
            },
            "campus": {
                "name": "校园风", "bg": "#F8FBFF", "fg": "#26364D", "panel": "#FFFFFF", "panel2": "#EFF6FF",
                "border": "#BFD8FF", "accent": "#4D8FEA", "accent2": "#7EB6FF", "muted": "#60728A",
                "button": "#EAF4FF", "button_hover": "#D7EAFF", "table": "#FFFFFF", "header": "#E5F1FF",
                "select": "#CFE6FF", "danger": "#D34A4A", "danger2": "#9A1E1E",
            },
            "fresh": {
                "name": "清新风", "bg": "#F5FCFA", "fg": "#24423E", "panel": "#FFFFFF", "panel2": "#ECFAF6",
                "border": "#BCE7DB", "accent": "#56BFA7", "accent2": "#8DDCCB", "muted": "#5B7B75",
                "button": "#E8FAF5", "button_hover": "#D6F3EC", "table": "#FFFFFF", "header": "#E3F7F1",
                "select": "#C9F0E6", "danger": "#C64A4A", "danger2": "#8F2020",
            },
            "fantasy": {
                "name": "暖色幻想风", "bg": "#FFF8EF", "fg": "#4D3426", "panel": "#FFFFFF", "panel2": "#FFF0DC",
                "border": "#F3D2A8", "accent": "#E59A45", "accent2": "#F2BD75", "muted": "#7A6254",
                "button": "#FFF0D8", "button_hover": "#FFE4BC", "table": "#FFFFFF", "header": "#FFEAD0",
                "select": "#FFE0B2", "danger": "#C94A3A", "danger2": "#8B1E16",
            },
        }
        if theme not in palettes:
            theme = "yukino"
        pal = palettes[theme]
        self.config.theme = theme
        self.theme_label.setText(f"当前主题：{pal['name']}")
        if hasattr(self, "theme_combo"):
            self._applying_theme = True
            idx = self.theme_combo.findData(theme)
            if idx >= 0:
                self.theme_combo.setCurrentIndex(idx)
            self._applying_theme = False

        # 同步卡片自绘用色和外部卡片美术资源。
        if hasattr(self, "cards"):
            large_card = self._existing_asset_path("cards", "large", "card_main.png")
            small_card = self._existing_asset_path("cards", "small", "card_sub.png")
            for card in self.cards.values():
                card.set_visual_palette(pal["accent"], pal["panel"], pal["border"])
                if hasattr(card, "set_card_assets"):
                    card.set_card_assets(str(large_card) if large_card else None, str(small_card) if small_card else None)

        bg_path = self._existing_asset_path("bg", self._theme_asset_folder(theme), "bg_01.png")
        if bg_path:
            bg_style = f'border-image: url("{str(bg_path).replace(chr(92), "/")}") 0 0 0 0 stretch stretch;'
        else:
            bg_style = f'background-color: {pal["bg"]};'

        self.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                color: {pal['fg']};
                font-size: 13px;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }}
            QWidget#RootWidget {{
                {bg_style}
            }}
            QGroupBox {{
                border: 1px solid rgba(183,199,230,115);
                border-radius: 12px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: rgba(255,255,255,28);
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px 0 6px;
                color: {pal['muted']};
            }}
            QPushButton {{
                background-color: {pal['button']};
                color: {pal['fg']};
                border: 1px solid {pal['border']};
                border-radius: 8px;
                padding: 6px 11px;
            }}
            QPushButton:hover {{
                background-color: {pal['button_hover']};
                border-color: {pal['accent']};
            }}
            QPushButton:disabled {{
                color: #9AA4B2;
                background-color: {pal['panel2']};
            }}
            QComboBox, QSpinBox, QLineEdit {{
                background-color: {pal['panel']};
                color: {pal['fg']};
                border: 1px solid {pal['border']};
                border-radius: 6px;
                padding: 4px 8px;
            }}
            QTableWidget, QTextEdit {{
                background-color: rgba(255,255,255,210);
                color: {pal['fg']};
                border: 1px solid rgba(183,199,230,135);
                border-radius: 10px;
                selection-background-color: {pal['select']};
                gridline-color: rgba(183,199,230,135);
            }}
            QHeaderView::section {{
                background-color: {pal['header']};
                color: {pal['fg']};
                border: 1px solid {pal['border']};
                padding: 5px;
            }}
            QMenuBar, QMenu {{
                background-color: {pal['bg']};
                color: {pal['fg']};
            }}
            QWidget#CardSceneWidget {{
                background: transparent;
            }}
            QFrame#CardPanel {{
                background: transparent;
                border: none;
            }}
            QWidget#CardOverlay {{
                background: transparent;
            }}
            QWidget#CardContent {{
                background: transparent;
            }}
            QLabel#CardTitle {{
                font-size: 21px;
                font-weight: 800;
                color: {pal['fg']};
                background: transparent;
                padding: 0px;
                margin: 0px;
            }}
            QLabel#CardSubtitle, QLabel#CardPreview {{
                color: {pal['muted']};
                background: transparent;
                line-height: 150%;
            }}
            QLabel#CardBadge {{
                color: #FFFFFF;
                background-color: rgba(88,123,177,185);
                border: 1px solid rgba(255,255,255,95);
                border-radius: 10px;
                padding: 5px 11px;
                font-weight: bold;
                min-width: 52px;
            }}
            QPushButton#CardExitButton {{
                background-color: {pal['button']};
                color: {pal['fg']};
                border: 1px solid {pal['border']};
                border-radius: 8px;
                padding: 0px;
                font-weight: bold;
            }}
            QPushButton#TaskAdvancedToggleButton {{
                background-color: rgba(255,255,255,190);
                color: {pal['fg']};
                border: 1px solid {pal['border']};
                border-radius: 8px;
                padding: 0px;
                font-weight: 700;
            }}
            QPushButton#TaskAdvancedToggleButton:hover {{
                background-color: rgba(225,240,255,230);
                border-color: {pal['accent']};
            }}
            QLabel#MascotImage {{
                border: 1px solid rgba(255,255,255,80);
                border-radius: 16px;
                color: {pal['accent']};
                background-color: rgba(255,255,255,18);
            }}
            QLabel#MascotSpeechBubble {{
                color: {pal['fg']};
                background: transparent;
                font-weight: 700;
                padding: 0px;
            }}
            QDialog#SettingsDialog {{
                background-color: rgba(236,246,255,245);
                color: {pal['fg']};
            }}
            QDialog#SettingsDialog QGroupBox {{
                background-color: rgba(255,255,255,155);
                border: 1px solid rgba(138,183,226,150);
                border-radius: 14px;
                margin-top: 12px;
                padding-top: 14px;
            }}
            QDialog#SettingsDialog QLabel, QDialog#SettingsDialog QCheckBox {{
                color: {pal['fg']};
                background: transparent;
                font-size: 14px;
            }}
            QDialog#SettingsDialog QSpinBox, QDialog#SettingsDialog QComboBox {{
                color: {pal['fg']};
                background-color: rgba(255,255,255,235);
                border: 1px solid rgba(138,183,226,160);
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 28px;
            }}
            QMessageBox {{
                background-color: rgba(236,246,255,248);
                color: #1F344D;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 14px;
            }}
            QMessageBox QLabel {{
                color: #1F344D;
                background: transparent;
                font-size: 14px;
                font-weight: 600;
                padding: 4px;
            }}
            QMessageBox QPushButton {{
                background-color: rgba(255,255,255,225);
                color: #315F9A;
                border: 1px solid rgba(138,183,226,170);
                border-radius: 9px;
                padding: 7px 18px;
                min-width: 72px;
                min-height: 30px;
                font-weight: 700;
            }}
            QMessageBox QPushButton:hover {{
                background-color: rgba(221,239,255,235);
                border-color: rgba(88,145,207,210);
            }}
        """)

        # 样式表会覆盖按钮内联样式，危险按钮和赞赏按钮重新设置。
        if hasattr(self, "stop_button"):
            self.stop_button.setStyleSheet(f"background-color: {pal['danger']}; color: white; font-weight: bold; padding: 8px 12px; border-radius: 8px;")
            self.emergency_stop_button.setStyleSheet(f"background-color: {pal['danger2']}; color: white; font-weight: bold; padding: 8px 12px; border-radius: 8px;")
        if hasattr(self, "donation_button"):
            self.donation_button.setStyleSheet("background-color: #FFD54F; color: #202124; font-weight: bold; padding: 8px 18px; border-radius: 8px;")


    def _current_startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        return '"{}" "{}"'.format(sys.executable, self.base_dir / "main.py")

    def _apply_windows_startup(self, enabled: bool) -> None:
        if platform.system().lower() != "windows":
            return
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self._current_startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            self.append_log(f"更新 Windows 开机自启动失败：{exc}")


    def export_config(self) -> None:
        """导出一份适合分享的配置文件。"""
        try:
            tasks = self.collect_tasks_from_table(sort_by_order=True)
            export_config = AppConfig(
                theme=self.config.theme,
                shutdown_after_done=self.shutdown_checkbox.isChecked(),
                shutdown_delay_seconds=int(self.shutdown_delay_spin.value()),
                auto_exit_after_done=self.auto_exit_checkbox.isChecked(),
                auto_start_tasks=self.auto_start_tasks_checkbox.isChecked(),
                windows_startup=False,  # 分享配置不携带开机自启动，避免导入者误开。
                tasks=tasks,
            )

            default_path = str(self.base_dir / "auto_script_config_share.json")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出配置",
                default_path,
                "JSON 配置文件 (*.json);;所有文件 (*.*)",
            )
            if not path:
                return

            with Path(path).open("w", encoding="utf-8") as f:
                json.dump(export_config.to_dict(), f, ensure_ascii=False, indent=2)
            self.append_log(f"配置已导出：{path}")
            self._show_themed_message("导出成功", f"配置已导出：\n{path}")
        except Exception as exc:
            self._show_themed_message("导出失败", f"导出配置失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"导出配置失败：{exc}")

    def import_config(self) -> None:
        """导入别人分享的配置文件，并刷新到当前界面。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入配置",
            str(self.base_dir),
            "JSON 配置文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            with Path(path).open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("配置文件顶层结构不是对象")

            imported = AppConfig.from_dict(data)

            # 分享配置只导入“任务执行配置”，不覆盖本机行为设置。
            # 这些本机设置包括：自动关机、自动退出、开机自启动、全局截图开关、主题等。
            # 这样可以避免别人分享的配置让本机意外启用自动关机等系统级行为。
            local_config = self.config
            self.config = AppConfig(
                theme=local_config.theme,
                shutdown_after_done=local_config.shutdown_after_done,
                shutdown_delay_seconds=local_config.shutdown_delay_seconds,
                auto_exit_after_done=local_config.auto_exit_after_done,
                auto_start_tasks=local_config.auto_start_tasks,
                windows_startup=local_config.windows_startup,
                enable_timeout_screenshot=local_config.enable_timeout_screenshot,
                tasks=imported.tasks,
            )

            self._load_config_to_ui()
            self.config_manager.save(self.config)
            self.append_log(f"配置已导入并保存：{path}")
            self.append_log("导入说明：仅导入任务配置；自动关机、开机自启动、截图开关等本机设置保持不变。")
            if self.has_usable_task_config():
                self.show_temporary_mascot_message("配置导入完成啦～可以先试着开始执行。", 10, priority=30)
            else:
                self.show_first_config_guide_if_needed()
            self._show_themed_message(
                "导入成功",
                "配置已导入。\n已仅导入任务配置；自动关机、开机自启动、截图开关等本机设置保持不变。",
            )
        except Exception as exc:
            self._show_themed_message("导入失败", f"导入配置失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"导入配置失败：{exc}")

    def _collect_ui_params(self) -> dict:
        """收集卡片布局调参参数。"""
        if not hasattr(self, "card_area"):
            return {}
        return {key: pose.__dict__.copy() for key, pose in self.card_area.overview_layout.items()}

    def export_ui_params(self) -> None:
        """导出卡片 UI 布局参数，供开发版调参复用。"""
        try:
            default_path = str(self.base_dir / "card_layout_debug.json")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出UI参数",
                default_path,
                "JSON 参数文件 (*.json);;所有文件 (*.*)",
            )
            if not path:
                return
            with Path(path).open("w", encoding="utf-8") as f:
                json.dump(self._collect_ui_params(), f, ensure_ascii=False, indent=2)
            self.append_log(f"UI参数已导出：{path}")
            self._show_themed_message("导出成功", f"UI参数已导出：\n{path}")
        except Exception as exc:
            self._show_themed_message("导出失败", f"导出UI参数失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"导出UI参数失败：{exc}")

    def import_ui_params(self) -> None:
        """导入卡片 UI 布局参数，并保存为 config/card_layout_debug.json。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入UI参数",
            str(self.base_dir),
            "JSON 参数文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("UI参数文件顶层结构不是对象")
            if not hasattr(self, "card_area"):
                raise RuntimeError("当前界面没有可调参的卡片区域")
            for key, item in data.items():
                if key in self.card_area.overview_layout and isinstance(item, dict):
                    self.card_area.overview_layout[key] = _pose_from_dict(item, self.card_area.overview_layout[key])
            self.card_area.apply_layout()

            debug_path = self.base_dir / "config" / "card_layout_debug.json"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_path.open("w", encoding="utf-8") as f:
                json.dump(self._collect_ui_params(), f, ensure_ascii=False, indent=2)

            if getattr(self.card_area, "_tuner_dialog", None) is not None:
                self.card_area._tuner_dialog._sync_controls()

            self.append_log(f"UI参数已导入并保存：{path}")
            self._show_themed_message("导入成功", "UI参数已导入，并保存为默认调参文件。")
        except Exception as exc:
            self._show_themed_message("导入失败", f"导入UI参数失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"导入UI参数失败：{exc}")

    def open_external_url(self, url: str) -> None:
        try:
            webbrowser.open(url)
            self.append_log(f"已打开链接：{url}")
        except Exception as exc:
            self._show_themed_message("打开失败", f"无法打开链接：{exc}", QMessageBox.Icon.Warning)

    def open_local_documentation(self) -> None:
        docs_path = self.base_dir / LOCAL_DOC_RELATIVE_PATH
        if not docs_path.exists():
            self._show_themed_message(
                "说明文档不存在",
                f"未找到本地说明文档：{docs_path}\n\n请确认 docs/index.html 已与程序一起放置。",
            )
            return
        try:
            if platform.system().lower() == "windows":
                os.startfile(str(docs_path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(docs_path.as_uri())
            self.append_log(f"已打开本地说明文档：{docs_path}")
        except Exception as exc:
            self._show_themed_message("打开失败", f"无法打开说明文档：{exc}", QMessageBox.Icon.Warning)

    def _show_themed_message(self, title: str, text: str, icon=QMessageBox.Icon.Information) -> None:
        """统一浅色玻璃风提示框，避免系统暗色 QMessageBox 导致文字不可读。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._prepare_popup_dialog(box)
        box.adjustSize()
        self._center_popup_on_screen(box)
        box.exec()

    def _ask_themed_yes_no(self, title: str, text: str, icon=QMessageBox.Icon.Question) -> bool:
        box = QMessageBox(self)
        self._prepare_popup_dialog(box)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.adjustSize()
        self._center_popup_on_screen(box)
        return box.exec() == QMessageBox.StandardButton.Yes

    def show_donation_dialog(self) -> None:
        """显示本地赞赏码图片。把图片放到程序目录 donation/ 下即可。"""
        donation_dir = self.base_dir / "donation"
        candidates = []
        for name in [
            "wechat_reward.png", "wechat_reward.jpg", "wechat_reward.jpeg",
            "reward.png", "reward.jpg", "reward.jpeg",
            "wechat.png", "wechat.jpg", "wechat.jpeg",
            "alipay.png", "alipay.jpg", "alipay.jpeg",
            "donate.png", "donate.jpg", "donate.jpeg",
        ]:
            path = donation_dir / name
            if path.exists():
                candidates.append(path)

        if not candidates:
            self._show_themed_message(
                "赞赏支持",
                "请先在程序目录下创建 donation 文件夹，并放入微信赞赏码图片。\n\n"
                "推荐文件名：\n"
                "wechat_reward.png（首选）/ reward.png / wechat.png",
            )
            return

        dialog = QDialog(self)
        dialog.setObjectName("DonationDialog")
        dialog.setWindowTitle("赞赏支持")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("☕ 赞赏支持 / Sponsor")
        title.setObjectName("DonationTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        tip = QLabel(
            "此程序为免费开源项目。若你为软件本体付了钱，请立即退款。\n"
            "赞赏完全自愿，用于支持作者继续开发与维护。\n"
            "赞赏前请优先点击下方 GitHub / B站按钮确认官方来源，警惕二次打包篡改收款码。"
        )
        tip.setObjectName("DonationTip")
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tip)

        for image_path in candidates[:2]:
            label = QLabel()
            label.setObjectName("DonationImage")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(360, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(pixmap)
            else:
                label.setText(f"无法读取图片：{image_path.name}")
            layout.addWidget(label)

        link_layout = QHBoxLayout()
        github_button = QPushButton("打开 GitHub 官方仓库")
        bilibili_button = QPushButton("打开作者 B站主页")
        close_button = QPushButton("关闭")
        for btn in [github_button, bilibili_button, close_button]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_button.clicked.connect(lambda: self.open_external_url(GITHUB_URL))
        bilibili_button.clicked.connect(lambda: self.open_external_url(AUTHOR_URL))
        close_button.clicked.connect(dialog.accept)
        link_layout.addWidget(github_button)
        link_layout.addWidget(bilibili_button)
        link_layout.addWidget(close_button)
        layout.addLayout(link_layout)

        dialog.setStyleSheet("""
            QDialog#DonationDialog {
                background-color: rgba(236, 246, 255, 245);
                color: #1F344D;
            }
            QLabel#DonationTitle {
                color: #315F9A;
                font-size: 22px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#DonationTip {
                color: #31506F;
                background-color: rgba(255, 255, 255, 176);
                border: 1px solid rgba(138, 183, 226, 150);
                border-radius: 14px;
                padding: 12px;
                line-height: 150%;
            }
            QLabel#DonationImage {
                background-color: rgba(255, 255, 255, 130);
                border: 1px solid rgba(138, 183, 226, 130);
                border-radius: 18px;
                padding: 10px;
                color: #31506F;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 185);
                color: #315F9A;
                border: 1px solid rgba(138, 183, 226, 150);
                border-radius: 9px;
                padding: 8px 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: rgba(221, 239, 255, 220);
                border: 1px solid rgba(88, 145, 207, 190);
            }
        """)
        dialog.resize(580, 680)
        dialog.exec()


    def _record_abnormal_report(self, message: str, task_name: str = "") -> None:
        """v31：把运行中识别到的异常写入下次启动汇报文件。"""
        clean_message = str(message or "").strip()
        if not clean_message:
            return
        key = clean_message[:240]
        if key in self._reported_abnormal_messages:
            return
        self._reported_abnormal_messages.add(key)
        report_path = self.base_dir / "logs" / "last_abnormal_report.json"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"events": []}
            if report_path.exists():
                try:
                    data = json.loads(report_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {"events": []}
            events = data.setdefault("events", [])
            severity = "warning" if ("提醒" in clean_message or "配置不匹配" in clean_message) else "error"
            events.append({
                "time": QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"),
                "task_name": task_name or getattr(self, "current_task_name", "-") or "当前任务",
                "message": clean_message,
                "severity": severity,
                "log_file": self.file_logger.log_path().name if hasattr(self, "file_logger") else "",
                "log_session": getattr(getattr(self, "file_logger", None), "session_label", ""),
            })
            report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.append_log(f"写入下次异常报告失败：{exc}")



    def _classic_dialog_stylesheet(self) -> str:
        return """
            QDialog, QMessageBox {
                background-color: rgba(236, 246, 255, 248);
                color: #1F344D;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 14px;
            }
            QLabel {
                color: #1F344D;
                background: transparent;
                font-size: 14px;
                font-weight: 600;
                padding: 4px;
            }
            QPushButton {
                background-color: rgba(255,255,255,225);
                color: #315F9A;
                border: 1px solid rgba(138,183,226,170);
                border-radius: 9px;
                padding: 7px 18px;
                min-width: 76px;
                min-height: 30px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: rgba(221,239,255,235);
                border-color: rgba(88,145,207,210);
            }
        """

    def _center_popup_on_screen(self, dialog: QDialog) -> None:
        try:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            frame = dialog.frameGeometry()
            frame.moveCenter(geo.center())
            dialog.move(frame.topLeft())
        except Exception:
            pass

    def _prepare_popup_dialog(self, dialog: QDialog, *, modal: bool = True, stay_on_top: bool = True) -> None:
        dialog.setStyleSheet(self._classic_dialog_stylesheet())
        if modal:
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        if stay_on_top:
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def show_startup_problem_report_if_needed(self) -> None:
        """v30：启动时只汇报上一次运行产生的异常报告。

        正常运行不会主动弹窗；异常项包括启动失败、过早退出、超时强退、
        监控的游戏/窗口/进程没有出现等。弹出后删除报告，避免每次启动重复打扰。
        """
        report_path = self.base_dir / "logs" / "last_abnormal_report.json"
        if not report_path.exists():
            return

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            events = data.get("events", [])
        except Exception as exc:
            self.append_log(f"读取上次异常报告失败：{exc}")
            return

        if not events:
            try:
                report_path.unlink()
            except Exception:
                pass
            return

        def brief_reason(message: str, severity: str) -> str:
            if "疑似过早退出" in message:
                return "快速退出（未达到 1/6 预期时长）"
            if "已超时" in message or "超时" in message:
                return "超时退出" + ("，已尝试保存现场截图" if "截图" in message else "")
            if "启动失败" in message:
                reason = message.split("启动失败", 1)[-1].strip("，：: ") or "启动失败"
                return "启动失败" if len(reason) > 60 else f"启动失败：{reason}"
            if "未检测到窗口标题关键词" in message:
                return "运行后未检测到目标窗口，可能是窗口标题关键词配置不匹配" if severity == "warning" else "脚本启动后，目标游戏/窗口未启动"
            if "未检测到指定进程" in message:
                return "运行后未检测到目标进程，可能是目标进程名配置不匹配" if severity == "warning" else "脚本启动后，目标进程未出现"
            if "未检测到命令行关键词" in message:
                return "运行后未检测到命令行关键词，可能是关键词配置不匹配" if severity == "warning" else "脚本启动后，目标命令行关键词未出现"
            return message

        error_lines = []
        warning_lines = []
        for event in events:
            index = len(error_lines) + len(warning_lines) + 1
            task_name = str(event.get("task_name") or f"进程{index}")
            message = str(event.get("message") or "未知异常")
            severity = str(event.get("severity") or "error")
            line = f"{task_name}：{brief_reason(message, severity)}"
            if severity == "warning":
                warning_lines.append(line)
            else:
                error_lines.append(line)

        parts = ["上次运行报告："]
        if error_lines:
            parts.append("\n异常：")
            parts.extend(f"{i}. {line}" for i, line in enumerate(error_lines, start=1))
        if warning_lines:
            parts.append("\n提醒：")
            parts.extend(f"{i}. {line}" for i, line in enumerate(warning_lines, start=1))
        log_file = str(data.get("log_file") or (events[0].get("log_file") if events else "") or "")
        if log_file:
            parts.append(f"\n对应日志：{log_file}")
        parts.append("\n正常完成的任务不会在这里汇报。")
        msg = "\n".join(parts)
        box = QMessageBox(self)
        self._prepare_popup_dialog(box)
        box.setWindowTitle("上次运行异常报告")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(msg)
        open_button = box.addButton("打开日志目录", QMessageBox.ButtonRole.ActionRole)
        box.addButton("我知道了", QMessageBox.ButtonRole.AcceptRole)
        box.adjustSize()
        self._center_popup_on_screen(box)
        box.exec()
        if box.clickedButton() == open_button:
            self.open_directory(report_path.parent)

        try:
            report_path.unlink()
        except Exception as exc:
            self.append_log(f"删除已读异常报告失败：{exc}")

    @Slot(int)
    def show_shutdown_warning_dialog(self, delay_seconds: int = 60) -> None:
        """任务完成后的可取消关机提示。

        v28.8：不再静默强制关机。先发送 60 秒/配置秒数关机命令，
        同时弹出置顶警告窗口；“取消关机”才会执行 shutdown /a，
        “关闭弹窗”或不操作都会继续倒计时关机。
        """
        if platform.system().lower() != "windows":
            self.append_log("当前非 Windows 环境，自动关机提示仅记录，不发送关机命令。")
            self._show_themed_message("自动关机", "当前非 Windows 环境，未发送关机命令。")
            return

        delay = max(1, int(delay_seconds or 60))
        self.shutdown_warning_remaining = delay
        try:
            subprocess.Popen(
                ["shutdown", "/s", "/t", str(delay)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            self.append_log(f"已发送延迟关机命令：shutdown /s /t {delay}")
        except Exception as exc:
            self._show_themed_message("关机失败", f"发送关机命令失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"发送关机命令失败：{exc}")
            return

        if self.shutdown_warning_dialog is not None:
            try:
                self.shutdown_warning_dialog.close()
            except Exception:
                pass

        dialog = QDialog(self)
        dialog.setWindowTitle("即将自动关机")
        dialog.setObjectName("ShutdownWarningDialog")
        self._prepare_popup_dialog(dialog)

        layout = QVBoxLayout(dialog)
        title = QLabel("⚠ 1分钟后将关机" if delay == 60 else f"⚠ {delay} 秒后将关机")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #B3261E;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        body = QLabel("若您仍需使用电脑，请点击『取消关机』。\n点击『关闭弹窗』或不进行任何操作，将继续倒计时关机。")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet("font-size: 14px; line-height: 1.5;")
        layout.addWidget(body)

        countdown = QLabel(f"剩余：{self.shutdown_warning_remaining} 秒")
        countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        countdown.setStyleSheet("font-size: 18px; font-weight: 700; color: #7A1E1E;")
        layout.addWidget(countdown)
        self.shutdown_warning_countdown_label = countdown

        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消关机")
        close_button = QPushButton("关闭弹窗")
        cancel_button.setStyleSheet("background-color: #B3261E; color: white; font-weight: 700; padding: 8px 16px; border-radius: 8px;")
        close_button.setStyleSheet("padding: 8px 16px; border-radius: 8px;")
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(close_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        cancel_button.clicked.connect(self._cancel_shutdown_from_warning)
        close_button.clicked.connect(dialog.close)

        self.shutdown_warning_dialog = dialog
        if self.shutdown_warning_timer is None:
            self.shutdown_warning_timer = QTimer(self)
            self.shutdown_warning_timer.timeout.connect(self._tick_shutdown_warning)
        self.shutdown_warning_timer.start(1000)

        dialog.resize(460, 250)
        self._center_popup_on_screen(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _tick_shutdown_warning(self) -> None:
        self.shutdown_warning_remaining = max(0, self.shutdown_warning_remaining - 1)
        if self.shutdown_warning_countdown_label is not None:
            self.shutdown_warning_countdown_label.setText(f"剩余：{self.shutdown_warning_remaining} 秒")
        if self.shutdown_warning_remaining <= 0 and self.shutdown_warning_timer is not None:
            self.shutdown_warning_timer.stop()

    def _cancel_shutdown_from_warning(self) -> None:
        self.cancel_shutdown()
        if self.shutdown_warning_timer is not None:
            self.shutdown_warning_timer.stop()
        if self.shutdown_warning_dialog is not None:
            self.shutdown_warning_dialog.close()
            self.shutdown_warning_dialog = None

    def cancel_shutdown(self) -> None:
        if platform.system().lower() != "windows":
            self._show_themed_message("提示", "取消关机按钮当前主要面向 Windows。")
            return

        try:
            subprocess.Popen(
                ["shutdown", "/a"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            self.append_log("已发送取消关机命令：shutdown /a")
        except Exception as exc:
            self._show_themed_message("取消失败", f"取消关机失败：{exc}", QMessageBox.Icon.Critical)
            self.append_log(f"取消关机失败：{exc}")

    def open_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            if platform.system().lower() == "windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif platform.system().lower() == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self._show_themed_message("打开失败", f"无法打开目录：{exc}", QMessageBox.Icon.Warning)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.is_running:
            if not self._ask_themed_yes_no(
                "任务正在运行",
                "当前任务还在运行。退出程序会尝试停止当前脚本，确定要退出吗？",
                QMessageBox.Icon.Warning,
            ):
                event.ignore()
                return

            if self.runner_worker is not None:
                self.runner_worker.request_stop()

        self.append_log("程序退出。")
        event.accept()


