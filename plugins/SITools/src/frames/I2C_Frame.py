
import logging
from pathlib import Path

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox

from ..protocol_frame import ProtocolFrame


class I2C_Frame(ProtocolFrame):
    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent, name, spec_path, logger)

        address_setting_layout = QHBoxLayout()
        address_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        address_setting_layout.setContentsMargins(0, 0, 0, 0)
        address_setting_layout.setSpacing(5)
        self.main_layout.addLayout(address_setting_layout)
        address_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Address</font>"))
        address_setting_layout.addStretch(1)
        address_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Slave(7b)</font>"))
        self.address_box = QLineEdit("0x")
        address_setting_layout.addWidget(self.address_box)
        address_setting_layout.addStretch(1)
        address_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Register</font>"))
        self.register_box = QLineEdit("0x")
        address_setting_layout.addWidget(self.register_box)
        address_setting_layout.addStretch(1)
        address_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>DataLength</font>"))
        self.data_len_box = QLineEdit("1")
        address_setting_layout.addWidget(self.data_len_box)

        sda_setting_layout = QHBoxLayout()
        sda_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        sda_setting_layout.setContentsMargins(0, 0, 0, 0)
        sda_setting_layout.setSpacing(10)
        self.main_layout.addLayout(sda_setting_layout)
        self.sda_en_box = QCheckBox()
        self.sda_en_box.setChecked(True)
        self.sda_en_box.setDisabled(True)
        sda_setting_layout.addWidget(self.sda_en_box)
        sda_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>SDA</font>")
        sda_label.setFixedWidth(60)
        sda_setting_layout.addWidget(sda_label)
        sda_setting_layout.addWidget(QLabel("label"))
        self.sda_label_box = QLineEdit("SDA")
        sda_setting_layout.addWidget(self.sda_label_box)
        sda_setting_layout.addWidget(QLabel("CH"))
        self.sda_ch_box = QComboBox()
        self.sda_ch_box.setEditable(True)
        self.sda_ch_box.addItems(["1", "2", "3", "4"])
        self.sda_ch_box.setCurrentIndex(0)
        sda_setting_layout.addWidget(self.sda_ch_box)

        scl_setting_layout = QHBoxLayout()
        scl_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        scl_setting_layout.setContentsMargins(0, 0, 0, 0)
        scl_setting_layout.setSpacing(10)
        self.main_layout.addLayout(scl_setting_layout)
        self.scl_en_box = QCheckBox()
        self.scl_en_box.setChecked(True)
        self.scl_en_box.setDisabled(True)
        scl_setting_layout.addWidget(self.scl_en_box)
        scl_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>SCL</font>")
        scl_label.setFixedWidth(60)
        scl_setting_layout.addWidget(scl_label)
        scl_setting_layout.addWidget(QLabel("label"))
        self.scl_label_box = QLineEdit("SCL")
        scl_setting_layout.addWidget(self.scl_label_box)
        scl_setting_layout.addWidget(QLabel("CH"))
        self.scl_ch_box = QComboBox()
        self.scl_ch_box.setEditable(True)
        self.scl_ch_box.addItems(["1", "2", "3", "4"])
        self.scl_ch_box.setCurrentIndex(1)
        scl_setting_layout.addWidget(self.scl_ch_box)

    def load_config(self, config):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

        self.address_box.setText(self.config.protocol_configuration.get("Slave Address", '0x'))
        self.register_box.setText(self.config.protocol_configuration.get("Register Address", '0x'))
        self.data_len_box.setText(self.config.protocol_configuration.get("Data Length", '1'))

        _, sda_ch, sda_label = self.config.channel_list.get("SDA", (True, 1, "SDA"))
        self.sda_label_box.setText(sda_label)
        self.scl_ch_box.setCurrentText(str(sda_ch))
        _, scl_ch, scl_label = self.config.channel_list.get("SCL", (True, 2, "SCL"))
        self.scl_label_box.setText(scl_label)
        self.scl_ch_box.setCurrentText(str(scl_ch))

    def dump_config(self):
        self.config.protocol = "I2C"
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))

        self.config.channel_list = {
            "SDA": (True, int(self.sda_ch_box.currentText()), self.sda_label_box.text()),
            "SCL": (True, int(self.scl_ch_box.currentText()), self.scl_label_box.text())
        }

        self.config.trigger_func = ("SCL", "falling")

        self.config.protocol_configuration = {
            "Slave Address": self.address_box.text(),
            "Register Address": self.register_box.text(),
            "Data Length": self.data_len_box.text()
        }

        return self.config
