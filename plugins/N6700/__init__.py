
from .main import MainWindow
from src.plugin_manager import register

register(
    name="N6700",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="N6700系列直流电源分析仪控制"
).handler(MainWindow)

