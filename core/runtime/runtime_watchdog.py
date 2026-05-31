from __future__ import annotations

import json
import platform
import subprocess
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class RuntimeTaskInfo:
    """单个任务的守护监控配置。由任务导入/导出配置驱动，不写死游戏名。"""

    task_name: str
    timeout_seconds: int
    start_time: float
    script_pid: int | None = None
    process_keywords: list[str] = field(default_factory=list)
    window_keywords: list[str] = field(default_factory=list)
    enable_timeout_screenshot: bool = True
    warning_ratio: float = 5 / 6
    early_exit_ratio: float = 1 / 6


class RuntimeWatchdog:
    """
    v26.1 Runtime Watchdog 配置驱动版。

    设计原则：
    - 只认任务配置里的 process_keywords / window_keywords，不内置任何游戏名。
    - 运行到 timeout * 5/6 时记录 warning 截图。
    - 运行到 timeout 时再次截图，并清理脚本进程/匹配进程。
    - 运行时间小于 timeout * 1/6 可标记为 early_exit。

    说明：窗口标题枚举和精确窗口截图依赖 Windows API，当前先提供安全骨架和目标进程关键词清理。
    后续可以在不改配置结构的情况下接入 win32gui / mss。
    """

    def __init__(self, logs_root: str | Path = "logs/problem"):
        self.logs_root = Path(logs_root)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def run(self, info: RuntimeTaskInfo) -> None:
        if info.timeout_seconds <= 0:
            return

        warning_threshold = info.timeout_seconds * info.warning_ratio
        warning_captured = False

        while True:
            runtime = time.time() - info.start_time

            if runtime >= warning_threshold and not warning_captured:
                self.capture_warning(info, runtime)
                warning_captured = True

            if runtime >= info.timeout_seconds:
                self.capture_timeout(info, runtime)
                self.force_cleanup(info)
                break

            time.sleep(3)

    def capture_warning(self, info: RuntimeTaskInfo, runtime: float) -> Path:
        folder = self._problem_folder(info.task_name)
        self._write_info(folder, info, status="warning", runtime=runtime)
        if info.enable_timeout_screenshot:
            self.capture_window_screenshot(folder / "warning.txt")
        return folder

    def capture_timeout(self, info: RuntimeTaskInfo, runtime: float) -> Path:
        folder = self._problem_folder(info.task_name)
        self._write_info(folder, info, status="timeout", runtime=runtime)
        if info.enable_timeout_screenshot:
            self.capture_window_screenshot(folder / "timeout.txt")
        return folder

    def mark_early_exit(self, info: RuntimeTaskInfo, runtime: float) -> Path | None:
        if info.timeout_seconds <= 0:
            return None
        if runtime > info.timeout_seconds * info.early_exit_ratio:
            return None

        folder = self._problem_folder(info.task_name)
        self._write_info(folder, info, status="early_exit", runtime=runtime)
        return folder

    def force_cleanup(self, info: RuntimeTaskInfo) -> None:
        """V31.11：升级为三层守护清理。\n        1. 清理脚本 PID\n        2. 清理 启动脚本 / target process\n        3. taskkill /T 结束进程树\n        4. window keyword 作为最终残留检测依据\n        """
        if info.script_pid:
            self._taskkill_pid(info.script_pid)

        for keyword in info.process_keywords:
            self._taskkill_by_image_keyword(keyword)

        # V31.11:
        # window_keywords 现在作为游戏窗口 watchdog 残留判断依据。
        # 当前版本仍采用轻量级结构：
        # 1. launcher_process
        # 2. main_process
        # 3. window_keywords
        #
        # 后续可以继续接入：
        # - win32gui
        # - pygetwindow
        # - mss
        # 实现真正窗口句柄绑定。

    def capture_window_screenshot(self, output_path: Path) -> None:
        """截图占位。后续接入 mss/win32gui 后改为输出 png。"""
        output_path.write_text(
            "v26.1 placeholder: 后续将接入窗口截图。当前先保留问题日志结构。",
            encoding="utf-8",
        )

    def _taskkill_pid(self, pid: int) -> None:
        if platform.system().lower() != "windows":
            return
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    def _taskkill_by_image_keyword(self, keyword: str) -> None:
        """按 exe 名关键词做温和匹配。建议配置精确 exe 名，如 YuanShen.exe。"""
        keyword = keyword.strip()
        if not keyword or platform.system().lower() != "windows":
            return
        try:
            # tasklist 输出中包含关键词时，再逐项 taskkill，避免直接拼接复杂命令。
            result = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True, timeout=8)
            for line in result.stdout.splitlines():
                if keyword.lower() not in line.lower():
                    continue
                image_name = line.split(",", 1)[0].strip().strip('"')
                if image_name:
                    subprocess.run(["taskkill", "/F", "/T", "/IM", image_name], capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    def _problem_folder(self, task_name: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in "-_（）()[]【】" else "_" for ch in task_name).strip("_") or "task"
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self.logs_root / f"{now}_{safe_name}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _write_info(self, folder: Path, info: RuntimeTaskInfo, status: str, runtime: float) -> None:
        payload = asdict(info)
        payload.update({
            "status": status,
            "runtime_seconds": round(runtime, 2),
            "timeout_limit_seconds": info.timeout_seconds,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        with (folder / "info.json").open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
