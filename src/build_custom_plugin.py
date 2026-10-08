import re
import shutil
from pathlib import Path
from typing import Optional, List

from src.plugin_manager import PluginInfo

# example 插件目录，作为 QT 类型的骨架模板
EXAMPLE_PLUGIN_DIR = Path(__file__).parent.parent / "plugins" / "example"

# __init__.py 模板 - QT 类方式：handler 引用 main.py 中的 MainWindow
init_file_text_class = """
from .{packet_name} import {module_name}
from src.plugin_manager import register

register(
    name="{name}",
    author="{author}",
    version="{version}",
    category="{category}",
    introduction="{introduction}",
    parameters={parameters}
).handler({module_name})


"""

# __init__.py 模板 - Command 字符串/列表方式：handler 直接接收命令
init_file_text_commands = """
from src.plugin_manager import register

register(
    name="{name}",
    author="{author}",
    version="{version}",
    category="{category}",
    introduction="{introduction}",
    parameters={parameters}
).handler({commands})


"""


def quick_replace(text, **kwargs):
    """快速替换register参数的一行代码方案"""
    for key, value in kwargs.items():
        text = re.sub(rf'({key}\s*=\s*)"[^"]*"', rf'\1"{value}"', text)
    return text


class build_plugin:
    def __init__(self, name: str, author: str, version: str, category: str, introduction: str):
        self.root_dir: Optional[Path] = None
        self.packet_name = ""
        self.module_name = ""
        self.handler_commands: Optional[List[str]] = None
        self.plugin_info = PluginInfo(
            name=name,
            author=author,
            version=version,
            category=category,
            introduction=introduction
        )

    def set_root_dir(self, root_dir: Path):
        self.root_dir = root_dir
        self.plugin_info.root_dir_name = self.root_dir.name

    def set_handler_path(self, packet_path: str, module_name: str):
        """QT 类型：指定插件主窗口的模块路径和类名"""
        self.packet_name = packet_path
        self.module_name = module_name
        self.handler_commands = None

    def set_terminal_handler(self, commands: List[str]):
        """Command 类型：用字符串列表方式注册 handler，不再生成 main.py"""
        self.handler_commands = [cmd for cmd in commands if cmd and cmd.strip()]
        self.packet_name = ""
        self.module_name = ""

    def _render_init_text(self) -> str:
        """根据 handler 类型渲染 __init__.py 内容"""
        parameters = self.plugin_info.parameters or {}
        if self.handler_commands is not None:
            return init_file_text_commands.format(
                name=self.plugin_info.name,
                author=self.plugin_info.author,
                version=self.plugin_info.version,
                category=self.plugin_info.category,
                introduction=self.plugin_info.introduction,
                parameters=f"{parameters}",
                commands=f"{self.handler_commands}",
            )
        return init_file_text_class.format(
            packet_name=self.packet_name,
            module_name=self.module_name,
            name=self.plugin_info.name,
            author=self.plugin_info.author,
            version=self.plugin_info.version,
            category=self.plugin_info.category,
            introduction=self.plugin_info.introduction,
            parameters=f"{parameters}",
        )

    def add_init_file(self):
        """生成 __init__.py（覆盖写入）"""
        if (not self.root_dir) or (not self.root_dir.exists()):
            return
        with open(self.root_dir / "__init__.py", 'w', encoding='utf-8') as f:
            f.write(self._render_init_text())

    def update_init_file(self):
        """更新已有 __init__.py 的元数据（保留 handler 注册方式）"""
        with open(self.root_dir / "__init__.py", 'r', encoding='utf-8') as f:
            txt = f.read()
        txt = quick_replace(
            txt,
            name=self.plugin_info.name,
            author=self.plugin_info.author,
            version=self.plugin_info.version,
            category=self.plugin_info.category,
            introduction=self.plugin_info.introduction,
            parameters=self.plugin_info.parameters,
        )
        with open(self.root_dir / "__init__.py", 'w', encoding='utf-8') as f:
            f.write(txt)

    def build_from_template(self):
        """无文件夹时以 example 插件为模板创建插件骨架

        - QT 类型：复制 example 的 main.py，并生成引用 MainWindow 的 __init__.py
        - Command 类型：仅生成直接 handler([...]) 的 __init__.py
        """
        if (not self.root_dir) or (not self.root_dir.exists()):
            return

        if self.handler_commands is not None:
            # Command 类型：命令通过 handler([...]) 传入，不需要 main.py
            self.add_init_file()
            return

        # QT 类型：复制 example 的 main.py 作为骨架，并强制 handler 指向 MainWindow
        shutil.copy(EXAMPLE_PLUGIN_DIR / "main.py", self.root_dir / "main.py")
        self.packet_name = "main"
        self.module_name = "MainWindow"
        self.add_init_file()
