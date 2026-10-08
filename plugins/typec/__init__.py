
from .main import MainWindow
from src.plugin_manager import register

register(
    name="Type-C tester",
    author="Liuyu.fang",
    version="2.1.5",
    category="FA",
    introduction="type-C 阻抗测试"
).handler(MainWindow)

