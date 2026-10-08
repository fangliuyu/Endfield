
from .main import MainWindow
from src.plugin_manager import register

register(
    name="ADB debug",
    author="Liuyu.fang",
    version="0.0.1",
    category="FA",
    introduction="adb 调试终端"
).handler(MainWindow)

