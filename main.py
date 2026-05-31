# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from core import _write_startup_error

try:
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
except Exception as exc:
    _write_startup_error(exc)
    print("启动失败，错误已写入 startup_error.log：", exc)
    raise


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _write_startup_error(exc)
        print("程序异常退出，错误已写入 startup_error.log：", exc)
        raise
