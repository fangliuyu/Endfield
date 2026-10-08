import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal

from lib.uartSerial.SerialAgent import UARTSerial


class SerialPortManager(QObject):
    """串口管理器类"""

    # 定义信号
    data_received = Signal(dict)  # 串口数据接收信号
    connection_status = Signal(bool, str)  # 连接状态信号

    def __init__(self, parent: Optional[QObject], port: str, baud_rate: int, timeout: float, logger: logging.Logger = None):
        super().__init__(parent)

        self.serial_core = UARTSerial(port, baud_rate, timeout)
        self.serial_core.set_callbacks(
            data_received=self._on_data_received,
            connection_status=self._on_connection_status
        )
        if logger:
            self.serial_core.set_serial_log(logger=logger)

    def _on_data_received(self, data: dict):
        """处理数据接收回调"""
        self.data_received.emit(data)

    def _on_connection_status(self, status: bool, message: str):
        """处理连接状态回调"""
        self.connection_status.emit(status, message)

    def connect_serial(self) -> bool:
        return self.serial_core.connect()

    def disconnect_serial(self):
        self.serial_core.disconnect()

    def set_logger(self, logger: logging.Logger):
        self.serial_core.set_serial_log(logger=logger)

    def send_data(self, command: str) -> bool:
        return self.serial_core.send(command)

    def send_with_response(self, command: str, timeout: float = 0.1) -> str:
        return self.serial_core.send_with_response(command, timeout)

    def is_open(self) -> bool:
        return self.serial_core.is_open()

    @property
    def is_connected(self):
        return self.serial_core.is_connected
