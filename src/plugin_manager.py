import ast
import dataclasses
import inspect
import json
import logging
import os
import subprocess
import sys
import traceback
import importlib
from importlib import util, metadata
from typing import Dict, List, Tuple, Optional, Type, Set, Union
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer

from lib.customlog import create_logger
from lib.filetools import scan_file_list
from lib.qtui.terminalWidget import build_terminal_handler

from src.base import builtin_plugins_path

_PID = os.getpid()

# 添加核心模块路径到Python路径
core_path = Path(__file__).parent
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))


@dataclasses.dataclass
class PluginInfo:
    """插件的元数据。"""

    name: Optional[str]
    """插件名"""
    author: Optional[str] = ""
    """插件作者"""
    version: Optional[str] = "0.0.0"
    """插件版本"""
    category: Optional[Union[str, list]] = "Other"
    """插件分类"""
    introduction: Optional[str] = "作者很懒，不写简介"
    """插件简介"""
    parameters: Optional[dict] = dataclasses.field(default_factory=dict)
    """插件启动参数"""
    dependencies: Optional[list] = dataclasses.field(default_factory=list)
    """插件所需的库"""

    root_dir_name: Optional[str] = None
    """插件的目录名称"""
    logo_path: Optional[str] = None
    """插件 Logo 的路径"""
    handler: Optional[Type] = None
    """插件handler"""

    def __str__(self) -> str:
        return f"{self.name}\nversion: {self.version}\nauthor: {self.author}\n{self.introduction}"

    def __repr__(self) -> str:
        return f"{self.name}\nversion: {self.version}\nauthor: {self.author}\n{self.introduction}"


class PluginRegistry:
    """插件注册器，支持链式调用"""

    def __init__(self, name: str, author: str = "", version: str = "0.0.0",
                 category: Optional[Union[str, list]]= "Other", introduction: str = "作者很懒，不写简介", parameters: dict = None, dependencies: list = None):
        """
        初始化插件注册信息

        Args:
            name: 插件名称
            author: 插件作者
            version: 插件版本
            category: 插件分类
            introduction: 插件简介
        """
        self.metadata = PluginInfo(
            name=name,
            author=author,
            version=version,
            category=category,
            introduction=introduction,
            parameters=parameters,
            dependencies=dependencies,
        )

    def handler(self, plugin_class_or_commands: Union[Type, str, List[str]]) -> Type:
        """
        注册插件处理器类

        Args:
            plugin_class_or_commands: 插件的主窗口类；或要发送到终端的命令（字符串/字符串列表），
                为后者时将动态生成一个终端窗口类，启动时按顺序发送这些命令

        Returns:
            返回插件类，不影响独立运行
        """
        if isinstance(plugin_class_or_commands, (str, list)):
            commands = (
                list(plugin_class_or_commands)
                if isinstance(plugin_class_or_commands, list)
                else [plugin_class_or_commands]
            )
            plugin_class = build_terminal_handler(commands)
            # 动态生成的类不在调用方模块的命名空间里，PluginManager.load_plugin
            # 通过 dir(module) 扫描属性来找 handler，需要把它注入调用方模块
            frame = inspect.currentframe()
            if frame is not None:
                caller_globals = frame.f_back.f_globals if frame.f_back else None
                if caller_globals is not None:
                    attr_name = f"_plugin_handler_{self.metadata.name}"
                    caller_globals[attr_name] = plugin_class
        else:
            plugin_class = plugin_class_or_commands

        # 将元数据附加到类上
        plugin_class._plugin_metadata = self.metadata
        plugin_class._plugin_metadata.handler = plugin_class

        return plugin_class


def register(
        name: str,
        author: str = "",
        version: str = "0.0.0",
        category: Optional[Union[str, list]] = "Other",
        introduction: str = "作者很懒，不写简介",
        parameters: dict = None
) -> PluginRegistry:
    """
    注册插件的入口函数
    register(
        name="我的插件",
        author="张三",
        version="1.0.0"
    ).handler(MyPlugin)

    Args:
        name: 插件名称
        author: 插件作者
        version: 插件版本
        category: 插件分类
        introduction: 插件简介
        parameters: 插件自定义的参数

    Returns:
        PluginRegistry 实例，支持链式调用
    """
    return PluginRegistry(name, author, version, category, introduction, parameters)


class DependencyManager:
    # 极小静态表：仅用于系统中根本没安装的极端情况，常规映射由动态发现覆盖
    _PIP_NAME_FALLBACK = {
        "serial": "pyserial",
        "pptx": "python-pptx",
        "PIL": "Pillow",
        "cv2": "opencv-python",
        "yaml": "PyYAML",
        "bs4": "beautifulsoup4",
        "sklearn": "scikit-learn",
        "zmq": "pyzmq",
    }

    # 这些捆绑包已知不完整，发现系统有新版时强制用系统版本
    _FORCE_OVERRIDE = {'PIL'}

    def __init__(self, logger: logging.Logger):
        self.project_root = Path(__file__).parent.parent
        self.logger = logger
        self.local_modules = set()
        self.installed_packages = set()
        self._pip_name_cache: dict = {}  # import名 → pip包名 动态缓存
        # 处理打包环境
        self.local_dirs = {self.project_root / "src", self.project_root / "lib", self.project_root / "ui"}
        if hasattr(sys, '_MEIPASS'):
            meipass_path = Path(sys._MEIPASS)
            # 确保必要的路径在 sys.path 中
            required_paths = [meipass_path, meipass_path / 'lib', meipass_path / 'src']
            for path in required_paths:
                if path.as_posix() not in sys.path:
                    sys.path.insert(0, path.as_posix())
        for local_dir in self.local_dirs:
            if local_dir.exists():
                self._get_local_modules(local_dir)

    def extract_dependencies(self, file_path: Path) -> Set[str]:
        """从Python文件中提取依赖"""
        dependencies = set()

        # 获取项目根目录（假设为当前文件的上层目录）
        project_root = file_path.parent
        while True:
            if project_root.name == "plugins":
                # self.logger.debug(f"{project_root.as_posix()} has scaned to root path, break")
                break
            # self.logger.debug(f"scan {project_root.as_posix()} local modules")
            self._get_local_modules(project_root)
            project_root = project_root.parent

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=file_path)
        except (SyntaxError, FileNotFoundError) as e:
            self.logger.error(e)
            return dependencies

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if self._is_external_dependency(alias.name):
                        dep = alias.name.split('.')[0]
                        if self._is_external_dependency(dep):
                            dependencies.add(dep)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if self._is_external_dependency(node.module):
                    dep = node.module.split('.')[0]
                    if self._is_external_dependency(dep):
                        dependencies.add(dep)

        return dependencies

    def _get_local_modules(self, project_root: Path):
        """获取项目中所有本地模块名"""
        self.local_modules.add(project_root.stem)

        # 添加打包后的资源路径识别
        if hasattr(sys, '_MEIPASS'):
            # 打包后的路径
            meipass_path = Path(sys._MEIPASS)
            if meipass_path.exists():
                self.local_modules.add(meipass_path.stem)
                # 添加可能的子目录
                for subdir in ['lib', 'src', 'ui']:
                    subdir_path = meipass_path / subdir
                    if subdir_path.exists():
                        self.local_modules.add(subdir)
        # 遍历项目目录，收集所有Python模块名
        file_list = project_root.rglob("*.py")
        files = [file for file in file_list]

        # 按路径深度优先，再按名称排序
        files = sorted(files, key=lambda x: (
            -len(str(x).split(os.sep)),  # 路径深度（目录层级数）
            x.name if hasattr(x, 'name') else str(x)            # 文件名
        ))
        for py_file in files:
            if py_file.stem != "__init__":
                self.local_modules.add(py_file.stem)
                # 获取相对路径作为模块名
                relative_path = py_file.relative_to(project_root)
                # 将路径转换为模块名（用点替换路径分隔符，去掉.py）
                module_name = str(relative_path).replace('/', '.').replace('\\', '.')[:-3]
                self.local_modules.add(module_name.split('.')[0])  # 只取第一级

    def _is_external_dependency(self, dep: str) -> bool:
        """判断是否为外部依赖"""
        return (
                dep not in sys.builtin_module_names and
                dep not in self.local_modules and
                not dep.startswith('.')
        )  # 跳过相对导入

    def _find_real_python(self) -> str:
        """在打包环境中查找真实 Python 解释器，并将其 site-packages 加入 sys.path"""
        if not getattr(sys, 'frozen', False):
            return sys.executable

        candidates = []

        # 1. 查找 PATH 中的 python3
        try:
            result = subprocess.run(
                ["which", "python3"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                python_found = result.stdout.strip()
                self.logger.info(f"[PID={_PID}] which python3 → {python_found}")
                candidates.append(python_found)
            else:
                self.logger.info(f"[PID={_PID}] which python3 未找到 (returncode={result.returncode})")
        except Exception as e:
            self.logger.info(f"[PID={_PID}] which python3 异常: {e}")

        # 2. 常见系统路径
        candidates.extend([
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            "/opt/homebrew/bin/python3",
            "/opt/local/bin/python3",
        ])

        # 3. 应用同级目录（如果部署了可移植 Python）
        app_dir = Path(sys.executable).parent
        candidates.extend([
            str(app_dir / "python3"),
            str(app_dir / "python" / "python3"),
        ])

        for candidate in candidates:
            if Path(candidate).exists():
                self.logger.debug(f"找到可用 Python 解释器: {candidate}")
                # 将其 site-packages 加入 sys.path，使打包 APP 能直接导入
                self._add_sitepackages_to_path(candidate)
                return candidate

        self.logger.error("打包环境中未找到可用 Python 解释器，无法安装依赖")
        raise RuntimeError("找不到 Python 解释器")

    def _add_sitepackages_to_path(self, python_exe: str):
        """将指定 Python 的所有 site-packages（系统+用户）加入 sys.path"""
        sp_added = False
        try:
            self.logger.info(f"[PID={_PID}] _add_sitepackages_to_path: python_exe={python_exe}")
            result = subprocess.run([
                python_exe, "-c",
                "import sysconfig, site; "
                "paths = [sysconfig.get_path('purelib'), sysconfig.get_path('platlib')]; "
                "try: paths.append(site.getusersitepackages()); "
                "except Exception: pass; "
                "for p in paths: print(p)"
            ], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    sp = line.strip()
                    if sp and sp not in sys.path:
                        sys.path.insert(0, sp)
                        self.logger.debug(f"已将 site-packages 加入 sys.path: {sp}")
                        sp_added = True
        except Exception as e:
            self.logger.debug(f"获取 site-packages 路径失败: {e}")

        if sp_added:
            importlib.invalidate_caches()
            self._resolve_frozen_conflicts()
            self._build_pip_name_cache(python_exe)

    def _resolve_frozen_conflicts(self):
        """移除已知不完整的捆绑包（如 PIL），强制使用系统 site-packages 中的版本"""
        if not getattr(sys, 'frozen', False):
            return

        site_packages_dirs = [p for p in sys.path if p and 'site-packages' in p]
        popped = []
        for mod_name in list(self._FORCE_OVERRIDE):
            mod = sys.modules.get(mod_name)
            mod_file = getattr(mod, '__file__', '') or ''
            if '.app/Contents' not in mod_file:
                continue  # 不是捆绑的，不用管

            # 检查系统 site-packages 中是否有同名包
            for sp_dir in site_packages_dirs:
                pkg_init = Path(sp_dir) / mod_name / '__init__.py'
                if pkg_init.exists():
                    sys.modules.pop(mod_name, None)
                    for key in list(sys.modules.keys()):
                        if key.startswith(mod_name + '.'):
                            sys.modules.pop(key, None)
                    popped.append(mod_name)
                    break

        if popped:
            importlib.invalidate_caches()
            self.logger.debug(f"已从 sys.modules 移除捆绑包，将使用系统版本: {popped}")

    def _install_and_find(self, pip_name: str, import_name: str) -> bool:
        """pip 安装后，用真实 Python 找到包的实际路径并加入 sys.path"""
        python_exe = self._find_real_python()

        # 安装
        cmd = [python_exe, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", pip_name]
        self.logger.debug(f"执行 pip: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            self.logger.warning(f"pip 安装失败: {pip_name}\n{result.stderr}")
            return False

        # pip 安装成功，用真实 Python 验证并找出实际安装路径
        find = subprocess.run([
            python_exe, "-c",
            "import sys; m = __import__(sys.argv[1]); print(getattr(m, '__file__', '') or '')",
            import_name
        ], capture_output=True, text=True, timeout=10)

        if find.returncode == 0 and find.stdout.strip():
            pkg_path = Path(find.stdout.strip())
            # 往上一级就是 site-packages（如 .../site-packages/pptx/__init__.py）
            for parent in pkg_path.parents:
                if parent.name == 'site-packages':
                    sp = str(parent)
                    if sp not in sys.path:
                        sys.path.insert(0, sp)
                        self.logger.debug(f"安装后加入 sys.path: {sp}")
                        importlib.invalidate_caches()
                        # 新 site-packages 可能有依赖包冲突（如 PIL）
                        self._resolve_frozen_conflicts()
                    break
            return True
        else:
            # 真实 Python 也找不到，fallback：加 user site-packages
            self.logger.warning(f"安装后验证失败: {import_name}，尝试回退路径")
            self._add_sitepackages_to_path(python_exe)
            try:
                importlib.import_module(import_name)
                self.logger.debug(f"已安装: {import_name}")
                return True
            except ImportError:
                self.logger.warning(f"安装验证失败 stderr: {find.stderr}")
                return False

    def _build_pip_name_cache(self, python_exe: str):
        """让真实 Python 扫描自身已安装的包，找出 import名≠pip包名的映射"""
        try:
            result = subprocess.run([
                python_exe, "-c",
                "import importlib.metadata, json; "
                "mapping = {}; "
                "for dist in importlib.metadata.distributions(): "
                "    pkg = (dist.metadata or {}).get('Name', ''); "
                "    if not pkg: continue; "
                "    files = dist.files or []; "
                "    seen = set(); "
                "    for f in files: "
                "        top = str(f).split('/')[0].split('\\\\')[0]; "
                "        if not top or top in seen: continue; "
                "        seen.add(top); "
                "        if top.endswith('.py'): top = top[:-3]; "
                "        if top.startswith('_') or top == '__pycache__': continue; "
                "        pkg_norm = pkg.replace('-','_').replace('.','_'); "
                "        if top != pkg_norm: "
                "            mapping[top] = pkg; "
                "print(json.dumps(mapping))"
            ], capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                parsed = json.loads(result.stdout.strip())
                self._pip_name_cache.update(parsed)
                if parsed:
                    self.logger.debug(f"动态发现 {len(parsed)} 个 import→pip 映射: {parsed}")
        except Exception as e:
            self.logger.debug(f"构建 pip 名缓存失败: {e}")

    def _to_pip_name(self, import_name: str) -> str:
        """import 名 → pip 包名。优先动态缓存，其次静态回退表。"""
        if import_name in self._pip_name_cache:
            return self._pip_name_cache[import_name]
        return self._PIP_NAME_FALLBACK.get(import_name, import_name)

    def install_dependency(self, package: str):
        """安装单个依赖包"""
        # 跳过标准库和已安装的包
        if package in sys.builtin_module_names or package in self.installed_packages:
            return

        try:
            importlib.import_module(package)
            self.installed_packages.add(package)
            return
        except ImportError:
            pass

        # 打包环境下，先加系统 site-packages 再重试一次
        if getattr(sys, 'frozen', False):
            self._add_sitepackages_to_path(self._find_real_python())
            try:
                importlib.import_module(package)
                self.logger.debug(f"通过系统 Python 已安装: {package}")
                self.installed_packages.add(package)
                return
            except ImportError:
                pass

        try:
            # 检查包是否可安装
            try:
                metadata.version(package)
                self.logger.debug(f"已注册: {package}")
                self.installed_packages.add(package)
                return
            except metadata.PackageNotFoundError:
                self.logger.debug(f"开始安装依赖: {package}")

            # import 名转 pip 包名
            pip_name = self._to_pip_name(package)

            # 安装 + 用真实 Python 定位实际路径
            success = self._install_and_find(pip_name, package)

            if success:
                self.installed_packages.add(package)
                self.logger.debug(f"安装成功: {package}")
                # 验证
                try:
                    importlib.import_module(package)
                except ImportError:
                    self.logger.warning(f"安装成功但导入失败: {package}")
            else:
                self.logger.warning(f"安装失败: {package}")

        except subprocess.TimeoutExpired:
            self.logger.warning(f"安装超时: {package}")
        except Exception as e:
            self.logger.warning(f"安装异常: {package} - {e}")

    def import_module_with_deps(self, file_path: Path, module_name: str, dependencies_check: bool = True, extras_require: list = None):
        """导入模块并自动处理依赖"""
        if extras_require:
            # 安装依赖
            for dep in extras_require:
                self.install_dependency(dep)

        # 提取依赖
        if dependencies_check:
            if (file_path.parent/"requirements.txt").exists():
                req_file = file_path.parent / "requirements.txt"
                if getattr(sys, 'frozen', False):
                    python_exe = self._find_real_python()
                    subprocess.run(
                        [python_exe, "-m", "pip", "install", "-r", str(req_file),
                         "--no-input", "--disable-pip-version-check"],
                        capture_output=True, text=True, timeout=120
                    )
                    self._add_sitepackages_to_path(python_exe)
                else:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "-r", str(req_file),
                         "--no-input", "--disable-pip-version-check"]
                    )

            dependencies = set()
            for file in scan_file_list(file_path.parent, "py", with_suffix=True, scan_children=True):
                if file.stem == "__init__":
                    continue
                file_deps = self.extract_dependencies(file_path.parent / file)
                dependencies.update(file_deps)

            # 安装依赖
            for dep in dependencies:
                self.install_dependency(dep)

        # 动态导入插件模块
        spec = importlib.util.spec_from_file_location(
            module_name,
            file_path
        )
        self.logger.info(f"set spec to modulename {module_name} from path {file_path.as_posix()}")
        module = importlib.util.module_from_spec(spec)
        self.logger.info(f"load module from spec successfully")

        # 添加插件目录到sys.path以便相对导入
        plugin_dir_path = file_path.parent
        if plugin_dir_path.as_posix() not in sys.path:
            self.logger.info(f"add {plugin_dir_path} to sys path")
            sys.path.insert(0, plugin_dir_path.as_posix())
        sys.modules[module_name] = module

        # 执行模块
        spec.loader.exec_module(module)
        self.logger.info(f"builder {module} successfully")

        return module


class PluginManager(QObject):
    # 信号定义
    plugin_loaded = Signal(PluginInfo, str)  # 插件, 插件来源(builtin/custom)

    def __init__(self, builtin_plugins_dir: str = "plugins",
                 custom_plugins_dir: str = "custom_plugins",
                 logger: logging.Logger = None):
        super().__init__()
        self.builtin_plugins_dir = Path(builtin_plugins_dir)
        self.custom_plugins_dir = Path(custom_plugins_dir)
        self.builtin_plugins: Dict[str, PluginInfo] = {}
        self.custom_plugins: Dict[str, PluginInfo] = {}
        self.plugin_categories: Dict[str, List[Tuple[str, str]]] = {}  # source(builtin/custom) filename, plugin_name

        self.watcher_timer = QTimer()
        self.watcher_timer.timeout.connect(self.check_for_custom_plugin_changes)
        self.watcher_timer.start(3000)  # 每3秒检查一次自定义插件目录

        self.logger = logger
        if not self.logger:
            self.logger = create_logger(name=__file__, level=logging.DEBUG)

        self.dm = DependencyManager(self.logger)

    def discover_all_plugins(self):
        """发现并加载所有插件（内置 + 自定义）"""
        self.logger.info("discover all plugins...")
        self.logger.info(f"discover builtin plugins at {self.builtin_plugins_dir}")
        self.discover_builtin_plugins()
        self.logger.info(f"discover custom plugins at {self.custom_plugins_dir}")
        self.discover_custom_plugins()
        self.logger.info(f"discover plugins finish, found {len(self.builtin_plugins)} builtin plugins and {len(self.custom_plugins)} custom plugins")

    def discover_builtin_plugins(self):
        """发现并加载内置插件"""
        if getattr(sys, 'frozen', False):
            # 打包环境：从 PYZ 中枚举插件包（.py 文件已编译，不在磁盘上）
            import pkgutil
            import plugins as plugins_pkg

            # 统一使用 iter_modules 只查找第一级插件目录
            modules = pkgutil.iter_modules(
                plugins_pkg.__path__, plugins_pkg.__name__ + '.'
            )
            for importer, modname, ispkg in modules:
                if not ispkg:
                    continue
                plugin_name = modname.split('.')[-1]
                if plugin_name == "example":
                    continue
                self.logger.info(f"load builtin plugin {plugin_name}")
                self.load_plugin(plugin_name, "builtin", dependencies_check=False)
            return

        if not self.builtin_plugins_dir.exists():
            self.logger.error(f"builtin plugin file {self.builtin_plugins_dir} no exist")
            return

        self.logger.info("=" * 50)
        for plugin_dir in self.builtin_plugins_dir.iterdir():
            if plugin_dir.name == "example":
                continue
            if plugin_dir.is_dir() and (plugin_dir / "__init__.py").exists():
                self.logger.info(f"load builtin plugin file {plugin_dir}")
                self.load_plugin(plugin_dir.name, "builtin", dependencies_check=False)
                self.logger.info("=" * 50)
        self.logger.info(f"当前内置插件: {list(self.builtin_plugins.keys())}")

    def discover_custom_plugins(self):
        """发现并加载自定义插件"""
        if not self.custom_plugins_dir.exists():
            os.makedirs(self.custom_plugins_dir, exist_ok=True)
            self.logger.error(f"custom plugin file {self.builtin_plugins_dir} no exist, created.")
            return

        self.logger.info("=" * 50)
        for plugin_dir in self.custom_plugins_dir.iterdir():
            if plugin_dir.name == "example":
                continue
            if plugin_dir.is_dir() and (plugin_dir / "__init__.py").exists():
                self.logger.info(f"load custom plugin file {plugin_dir}")
                self.load_plugin(plugin_dir.name, "custom", dependencies_check=True)
                self.logger.info("=" * 50)
        self.logger.info(f"当前自定义插件: {list(self.custom_plugins.keys())}")

    def load_plugin(self, plugin_name: str, source: str, dependencies_check: bool):
        """加载单个插件"""
        try:
            # 确定插件目录
            if source == "builtin":
                plugins_dir = self.builtin_plugins_dir
                plugins_dict = self.builtin_plugins
            else:
                plugins_dir = self.custom_plugins_dir
                plugins_dict = self.custom_plugins

            # 如果插件已加载，先卸载
            if plugin_name in plugins_dict:
                self.unload_plugin(plugin_name, source)

            if source == "builtin" and getattr(sys, 'frozen', False):
                # PyInstaller 打包环境：插件已编译到 PYZ 中，直接用模块导入
                # 数据文件（如 logo.png）仍然在 sys._MEIPASS/plugins 目录下
                full_module_name = f"plugins.{plugin_name}"
                # 先添加 _MEIPASS 到 sys.path 确保能导入
                meipass = Path(sys._MEIPASS)
                if str(meipass) not in sys.path:
                    sys.path.insert(0, str(meipass))
                # 导入模块（从 PYZ 中加载）
                module = importlib.import_module(full_module_name)
                # 数据文件路径设置为 meipass/plugins（插件数据文件所在的目录）
                builtin_dir_name = self.builtin_plugins_dir.name
                plugins_dir = meipass / builtin_dir_name
            else:
                plugin_init_path = plugins_dir / plugin_name / "__init__.py"
                # 使用更独特的模块名，确保每个插件都有唯一的模块标识
                unique_module_name = f"{source}_{plugin_name}_plugin"

                # 动态导入插件模块
                module = self.dm.import_module_with_deps(
                    plugin_init_path, unique_module_name, dependencies_check
                )

            # 查找注册的插件类
            metadata: PluginInfo = PluginInfo(
                name=plugin_name
            )
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if hasattr(attr, '_plugin_metadata'):
                    metadata = attr._plugin_metadata  # NOQA
                    if metadata.handler == attr:
                        self.logger.info(f"通过 register().handler() 找到插件: {attr_name}")
                        break

            if not metadata.handler:
                self.logger.error(f"插件 {plugin_name} 未找到任何可用的插件类")
                return

            # 创建插件实例信息
            root_dir = plugins_dir / plugin_name
            log_file = root_dir / "logo.png"
            # 把插件目录注入到 handler 类，供 _TerminalHandler 等动态类使用
            try:
                setattr(metadata.handler, "_plugin_dir", root_dir.as_posix())
            except (AttributeError, TypeError):
                pass
            plugin_instance = PluginInfo(
                name=metadata.name or plugin_name,
                author=metadata.author,
                version=metadata.version,
                category=metadata.category,
                introduction=metadata.introduction,
                parameters=metadata.parameters if metadata.parameters else {},
                dependencies=metadata.dependencies if metadata.dependencies else [],
                root_dir_name=root_dir.as_posix(),
                logo_path=log_file.as_posix() if log_file.exists() else (builtin_plugins_path / ".default_logo.png").as_posix(),
                handler=metadata.handler,
            )

            # 分类管理
            plugins_dict[plugin_instance.name] = plugin_instance
            if source not in self.plugin_categories:
                self.plugin_categories[source] = []
            self.plugin_categories[source].append((plugin_name, plugin_instance.name))

            self.logger.info(f"加载来自{source}的插件{plugin_instance.name} 成功")
            self.logger.info(f"插件信息: 名称={plugin_instance.name}, "
                             f"分类={plugin_instance.category}, "
                             f"版本={plugin_instance.version}")
            for dependencies in plugin_instance.dependencies:
                self.dm.install_dependency(dependencies)
            self.plugin_loaded.emit(plugin_instance, source)

        except Exception as e:
            self.logger.error(f"加载{source}插件 {plugin_name} 失败: {e}")
            self.logger.error(traceback.format_exc())

    def unload_plugin(self, plugin_name: str, source: str):
        """卸载插件"""
        plugins_dict = self.builtin_plugins if source == "builtin" else self.custom_plugins

        if plugin_name in plugins_dict:
            del plugins_dict[plugin_name]

            if source in self.plugin_categories:
                plugins = self.plugin_categories[source]
                for i, (name, _) in enumerate(plugins):
                    if name == plugin_name:
                        plugins.pop(i)
                        break
        self.logger.info(f"卸载插件: 请求名={plugin_name}, 来源={source}")

    def get_plugin(self, plugin_name: str, source: str) -> PluginInfo:
        """获取特定插件"""
        plugins_dict = self.builtin_plugins if source == "builtin" else self.custom_plugins

        if plugin_name in plugins_dict:
            plugin = plugins_dict.get(plugin_name)
            self.logger.info(f"获取插件: 请求名={plugin_name}, 来源={source}, 找到={plugin.version}")
            return plugin
        else:
            raise Exception(f"not find plugin {plugin_name} in {source} list ({plugins_dict.keys()})")

    def get_all_plugins(self) -> List[Tuple[PluginInfo, str]]:
        """获取所有插件及其来源"""
        plugins = []
        for name, plugin in self.builtin_plugins.items():
            plugins.append((plugin, "builtin"))
        for name, plugin in self.custom_plugins.items():
            plugins.append((plugin, "custom"))
        return plugins

    def get_plugins_by_type(self, plugin_type: str) -> List[Tuple[str, PluginInfo]]:
        """按类型获取插件

        :return [plugin_name, PluginInfo]
        """
        result = []
        for _, plugin_name in self.plugin_categories.get(plugin_type, []):
            plugin = self.get_plugin(plugin_name, plugin_type)
            if plugin:
                result.append((plugin_name, plugin))
        return result

    def get_all_plugin_types(self) -> List[str]:
        """获取所有插件类型"""
        return list(self.plugin_categories.keys())

    def check_for_custom_plugin_changes(self):
        """检查自定义插件目录的变化（热更新）"""
        if "custom" not in self.plugin_categories:
            current_custom_plugins = set()
        else:
            current_custom_plugins = set(plugin_file for plugin_file, _ in self.plugin_categories["custom"])

        if self.custom_plugins_dir.exists():
            available_plugins = {
                d.name for d in self.custom_plugins_dir.iterdir()
                if d.is_dir() and (not d.name == "example") and (d / "__init__.py").exists()
            }

            # 加载新插件
            new_plugins = available_plugins - current_custom_plugins
            if new_plugins:
                self.logger.info(f"find new plugin list {new_plugins}")
                for new_plugin in new_plugins:
                    self.load_plugin(new_plugin, "custom", True)

            # 卸载已删除的插件
            rm_plugins = current_custom_plugins - available_plugins
            if rm_plugins:
                self.logger.info(f"find remove plugin list {rm_plugins}")
                for removed_plugin in rm_plugins:
                    self.unload_plugin(removed_plugin, "custom")
