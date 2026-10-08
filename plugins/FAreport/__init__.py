
from .main import MainWindow
from src.plugin_manager import register

register(
    name="FAreport",
    author="Liuyu.fang",
    version="0.0.1",
    category="FA",
    introduction="报告生成器"
).handler(MainWindow)

