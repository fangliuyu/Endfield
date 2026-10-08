"""VISA 后端管理:NI-VISA 优先,pyvisa-py 回退;检测/下载/静默安装 NI-VISA Runtime。"""
import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyvisa

# NI-VISA Runtime 下载地址(NI 官方,版本可按需更新)
NIVISA_RUNTIME_URL = "https://www.ni.com/zh-cn/support/downloads/drivers/download.ni-visa.html"
# 如有确定直链,可替换为直链;否则引导用户打开下载页
NIVISA_RUNTIME_FALLBACK_URL = "https://www.ni.com/zh-cn/support/downloads/drivers/download.ni-visa.html"


def _log(logger, level, msg):
    if logger is None:
        return
    try:
        logger.log(level, msg)
    except Exception:
        pass


def get_resource_manager(logger: logging.Logger = None):
    """获取 ResourceManager,优先 NI-VISA,失败回退 pyvisa-py。"""
    try:
        return pyvisa.ResourceManager()
    except Exception as ex:
        _log(logger, logging.WARNING,
             f"[VISA] NI-VISA 后端不可用({type(ex).__name__}: {ex}),回退到 pyvisa-py")
        try:
            return pyvisa.ResourceManager("@py")
        except Exception as ex2:
            _log(logger, logging.ERROR,
                 f"[VISA] pyvisa-py 后端也不可用: {type(ex2).__name__}: {ex2}")
            raise


def check_visa_installed() -> bool:
    """检测本机是否已安装 NI-VISA。"""
    # Windows: 尝试加载 visa32.dll
    if sys.platform == "win32":
        try:
            ctypes.CDLL("visa32.dll")
            return True
        except OSError:
            pass
        # 注册表兜底
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\National Instruments\NI-VISA\CurrentVersion"):
                return True
        except (FileNotFoundError, OSError):
            pass
        return False
    # macOS: 检测 VISA.framework
    if sys.platform == "darwin":
        return os.path.exists("/Library/Frameworks/VISA.framework") or \
            os.path.exists("/System/Library/Frameworks/VISA.framework")
    # Linux: 检测 libvisa.so
    return shutil.which("visa") is not None or os.path.exists("/usr/lib/libvisa.so.7")


def _download(url: str, dest: Path, logger: logging.Logger = None) -> bool:
    """下载文件到 dest,返回是否成功。"""
    import requests
    _log(logger, logging.INFO, f"[VISA] 开始下载: {url}")
    try:
        with requests.get(url, stream=True, timeout=30, allow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        _log(logger, logging.DEBUG,
                             f"[VISA] 下载进度: {downloaded}/{total} ({downloaded*100//total}%)")
        _log(logger, logging.INFO, f"[VISA] 下载完成: {dest} ({downloaded} bytes)")
        return True
    except Exception as ex:
        _log(logger, logging.ERROR, f"[VISA] 下载失败: {type(ex).__name__}: {ex}")
        return False


def _install_windows(installer: Path, logger: logging.Logger = None) -> bool:
    """Windows 静默安装 NI-VISA Runtime,需要 UAC 提权。返回是否成功启动安装。"""
    if not installer.exists():
        _log(logger, logging.ERROR, f"[VISA] 安装包不存在: {installer}")
        return False

    # 检查当前是否管理员
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False

    args = [str(installer), "/q", "/noreboot"]
    _log(logger, logging.INFO, f"[VISA] 启动静默安装: {' '.join(args)} (admin={is_admin})")

    try:
        if is_admin:
            # 直接运行
            proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
            _log(logger, logging.INFO,
                 f"[VISA] 安装进程退出码: {proc.returncode}")
            if proc.stdout:
                _log(logger, logging.DEBUG, f"[VISA] 安装 stdout: {proc.stdout[:2000]}")
            if proc.stderr:
                _log(logger, logging.DEBUG, f"[VISA] 安装 stderr: {proc.stderr[:2000]}")
            return proc.returncode == 0
        else:
            # 通过 ShellExecuteW 弹 UAC,runas 会触发新进程,无法直接拿退出码
            # 用 wait=True 让 ShellExecuteW 阻塞等待安装完成
            import ctypes.wintypes
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(installer), "/q /noreboot", None, 0)
            # ShellExecuteW 返回 > 32 表示成功
            success = ret > 32
            _log(logger, logging.INFO,
                 f"[VISA] ShellExecuteW 返回: {ret} (success={success})")
            return success
    except subprocess.TimeoutExpired:
        _log(logger, logging.ERROR, "[VISA] 安装超时(>10 分钟)")
        return False
    except Exception as ex:
        _log(logger, logging.ERROR, f"[VISA] 安装异常: {type(ex).__name__}: {ex}")
        return False


def _install_mac(installer: Path, logger: logging.Logger = None) -> bool:
    """macOS 下 pkg 无法自动 sudo,记录日志并提示用户手动安装。"""
    _log(logger, logging.WARNING,
         f"[VISA] macOS 需要手动安装: {installer} (pkg 需要 sudo,无法自动执行)")
    # 可以选择触发打开命令
    try:
        subprocess.run(["open", str(installer)], check=False)
        _log(logger, logging.INFO, f"[VISA] 已打开安装包: {installer}")
    except Exception as ex:
        _log(logger, logging.ERROR, f"[VISA] 打开安装包失败: {ex}")
    return False


def ensure_visa(logger: logging.Logger = None,
                download_dir: Path = None,
                auto_install: bool = True,
                installer_url: str = None) -> bool:
    """
    检测并(可选)自动安装 NI-VISA Runtime。
    返回 True 表示已安装或安装已启动;False 表示不可用。
    无论如何都会记录日志。
    """
    _log(logger, logging.INFO, "[VISA] 开始检测 NI-VISA 安装状态")
    if check_visa_installed():
        _log(logger, logging.INFO, "[VISA] NI-VISA 已安装,跳过安装")
        return True

    _log(logger, logging.WARNING, "[VISA] NI-VISA 未安装,将尝试回退到 pyvisa-py 并引导安装 NI-VISA")

    if not auto_install:
        _log(logger, logging.INFO, "[VISA] auto_install=False,仅记录,不自动安装")
        return False

    # 没有直链时,引导用户到下载页
    url = installer_url or NIVISA_RUNTIME_FALLBACK_URL
    if download_dir is None:
        download_dir = Path.cwd() / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # 判断 URL 是不是直链(简单启发:以 .exe/.pkg/.msi/.dmg 结尾)
    suffix = ""
    for ext in (".exe", ".msi", ".pkg", ".dmg"):
        if url.lower().endswith(ext):
            suffix = ext
            break

    if not suffix:
        # 没有直链,打开浏览器到下载页
        _log(logger, logging.WARNING,
             f"[VISA] 无直链安装包,请手动下载: {url}")
        try:
            import webbrowser
            webbrowser.open(url)
            _log(logger, logging.INFO, f"[VISA] 已打开浏览器: {url}")
        except Exception as ex:
            _log(logger, logging.ERROR, f"[VISA] 打开浏览器失败: {ex}")
        return False

    # 有直链,下载并安装
    installer = download_dir / f"NIVISA_Runtime{suffix}"
    if not _download(url, installer, logger):
        return False

    if sys.platform == "win32":
        return _install_windows(installer, logger)
    elif sys.platform == "darwin":
        return _install_mac(installer, logger)
    else:
        _log(logger, logging.WARNING,
             f"[VISA] 当前平台 {sys.platform} 不支持自动安装,请手动安装: {installer}")
        return False
