
import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QWidget

from lib.filetools import scan_file_list
from .setting import ProtocolBaseConfig


class ProtocolFrame(QWidget):
    specChanged = Signal(Path, float)

    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent)
        self.logger = logger
        self.config = ProtocolBaseConfig()
        self.spec_file = spec_path / name

        # 创建垂直布局
        self.main_layout = QVBoxLayout()
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        spec_setting_layout = QHBoxLayout()
        spec_setting_layout.setContentsMargins(0, 0, 0, 0)
        spec_setting_layout.setSpacing(5)
        self.main_layout.addLayout(spec_setting_layout)
        spec_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>SPEC</font>"))
        self.spec_file_box = QComboBox()
        self.spec_file_box.setMaximumWidth(300)
        self.spec_file_box.setEditable(False)
        self.spec_file_box.currentTextChanged.connect(self.choose_spec_file)
        spec_setting_layout.addWidget(self.spec_file_box, 1)
        spec_setting_layout.addStretch(1)
        spec_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Voltage</font>"))
        self.spec_vol_box = QComboBox()
        self.spec_vol_box.setEditable(True)
        self.spec_vol_box.addItems(["1.2", "1.8", "3.3", "5.0"])
        self.spec_vol_box.currentTextChanged.connect(self.change_spec_signal)
        spec_setting_layout.addWidget(self.spec_vol_box)
        spec_setting_layout.addWidget(QLabel("V"))
        spec_setting_layout.addStretch(1)
        spec_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Thresholds</font>"))
        self.threshold_lower = QLineEdit("0.3")
        spec_setting_layout.addWidget(self.threshold_lower)
        spec_setting_layout.addWidget(QLabel("-"))
        self.threshold_upper = QLineEdit("0.7")
        spec_setting_layout.addWidget(self.threshold_upper)
        self.refresh_spec_list()

    def choose_spec_file(self):
        self.spec_file_box.blockSignals(True)
        current_text = self.spec_file_box.currentText()
        if current_text and current_text != "刷新列表":
            self.logger.info(f"用户选择了{current_text}")
            self.change_spec_signal()
        else:
            self.refresh_spec_list()
        self.spec_file_box.blockSignals(False)

    def change_spec_signal(self):
        current_text = self.spec_file_box.currentText()
        voltage = float(self.spec_vol_box.currentText())
        self.specChanged.emit(self.spec_file / (current_text + '.xlsx'), voltage)

    def refresh_spec_list(self):
        self.spec_file_box.clear()
        spec_list = scan_file_list(self.spec_file, suffix="xlsx")
        self.logger.info(f"当前识别到了{len(spec_list)}个xlsx文件")
        spec_list.append("刷新列表")
        self.spec_file_box.addItems(spec_list)
        self.spec_file_box.setCurrentIndex(0)

    def load_config(self, config: ProtocolBaseConfig):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

    def dump_config(self):
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))
        return self.config
