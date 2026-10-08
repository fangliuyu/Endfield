import functools
import traceback

from PySide6.QtWidgets import QMessageBox


def auto_connected(func):
    """装饰器方法，检查设备连接状态"""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not (self.device and self.connected):
                self.connect_device()
            if not self.connected:
                raise Exception("the device cannot connect!")
            return func(self, *args, **kwargs)
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(None, "错误", f"[{type(e).__name__}] {e}")
            return None

    return wrapper


def check_error(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(self, "错误", f"[{type(e).__name__}] {e}")
            return None

    return wrapper
