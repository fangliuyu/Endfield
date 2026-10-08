
from lib.qtui.terminalWidget import MainWindow
from src.plugin_manager import register

register(
    name="LikeTerminal",
    author="Liuyu.fang",
    version="0.0.1",
    category="Other",
    introduction="终端模拟器"
).handler(MainWindow)

