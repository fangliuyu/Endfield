
from .main import MainWindow
from src.plugin_manager import register

register(
    name="Plots",
    author="Liuyu.fang",
    version="0.0.1",
    category="Other",
    introduction="CSV数据可视化工具，支持多Y轴绘制"
).handler(MainWindow)
