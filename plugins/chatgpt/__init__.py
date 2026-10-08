
from .main import MainWindow
from src.plugin_manager import register

register(
    name="ChatGPT",
    author="Liuyu.fang",
    version="0.0.1",
    category="Other",
    introduction="这是一个简单的AI聊天窗口"
).handler(MainWindow)

