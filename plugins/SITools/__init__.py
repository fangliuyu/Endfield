
from .src.gui import MainWindow
from src.plugin_manager import register

register(
    name="SITools",
    author="Liuyu.fang",
    version="1.5.8.20260112",
    category="Validation",
    introduction="标准协议SI测试工具"
).handler(MainWindow)

