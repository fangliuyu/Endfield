
from .main import MainWindow
from src.plugin_manager import register

register(
    name="ExcelMatch",
    author="Liuyu.fang",
    version="2.3.3",
    category="Other",
    introduction="Excel文件整合与对比工具"
).handler(MainWindow)
