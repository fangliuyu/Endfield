import logging
import sys
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Optional, Union

from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel
)

from lib.customlog import create_logger


class MainWindow(QMainWindow):
    def __init__(
            self,
            name: str,
            version: str = "1.0.0",
            logger: Optional[Logger] = None,
            data_path: Union[PathLike[str], str, None] = None,
            dryrun: bool = False,
            *args,
            **kwargs,
    ):
        super().__init__()
        self.widget_name = name
        self.logger = logger
        self.data_path = Path.cwd()
        if data_path:
            self.data_path = Path(data_path)
        self.data_path.mkdir(exist_ok=True)
        if not self.logger:
            log_path = self.data_path / "script_log"
            log_path.mkdir(exist_ok=True)
            self.logger = create_logger(name=name, level=logging.DEBUG, log_path=log_path)
        self.logger.info(f"{name} logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        self.setWindowTitle(f"{name} V{version}")
        self.resize(800, 600)

        central_widget = QLabel(f"这是一个示例插件 on {'demo' if dryrun else 'other'}")
        central_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(central_widget)

    def deleteLater(self, /):
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="example")
    window.show()
    sys.exit(app.exec())
