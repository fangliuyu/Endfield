
from .main import MainWindow
from src.plugin_manager import register

register(
    name="IVCurves",
    author="Liuyu.fang",
    version="0.0.1",
    category="FA",
    introduction="IV曲线（电流-电压曲线）测试工具"
).handler(MainWindow)

