import os
import sys
import traceback
from pathlib import Path
from src.base import root_log
from lib.instruments.visa_env import ensure_visa
from ui.app import TrayApp

# ── 子进程诊断 ─────────────────────────────────────────────
_PID = os.getpid()
_APP_EXE = sys.executable  # 打包后是 .app 二进制路径

def _install_subprocess_audit():
    """包装 subprocess.Popen，检测所有进程启动"""
    import subprocess as _sp
    _original_init = _sp.Popen.__init__

    def _audited_init(self, args, **kwargs):
        cmd = args if isinstance(args, (list, tuple)) else [str(args)]
        cmd_str = ' '.join(str(c) for c in cmd)
        # 检查是否调用了 .app 二进制
        if _APP_EXE in cmd_str or ('.app/' in cmd_str and 'Endfield' in cmd_str):
            root_log.critical(
                f"[PID={_PID}] *** 检测到 APP 二进制调用! *** 命令={cmd_str}"
            )
            # 打印调用栈
            root_log.critical(
                f"[PID={_PID}] 调用栈:\n{''.join(traceback.format_stack()[:-1])}"
            )
        return _original_init(self, args, **kwargs)

    _sp.Popen.__init__ = _audited_init


def _ensure_single_instance():
    """使用 PID 文件锁确保打包后只有一个 APP 实例在运行"""
    if not getattr(sys, 'frozen', False):
        return None  # 开发模式允许多实例

    import tempfile
    import time as _time
    lock_file = Path(tempfile.gettempdir()) / "Endfield.lock"
    waited = False

    # 阶段1：检查锁 — 如果另一个实例存活，等待而不是退出
    # 避免 os._exit(0) 被 macOS launchd 误判为"异常退出"而自动重启
    while True:
        try:
            if lock_file.exists():
                old_pid = int(lock_file.read_text().strip())
                try:
                    os.kill(old_pid, 0)
                    if not waited:
                        root_log.warning(
                            f"[PID={_PID}] 检测到 APP 已在运行 (PID={old_pid})，等待其退出..."
                        )
                        waited = True
                    _time.sleep(2)
                    continue
                except OSError:
                    pass  # 旧进程已死
            break
        except (ValueError, OSError):
            break

    # 阶段2：获取锁
    lock_file.write_text(str(os.getpid()))

    if waited:
        # 我们是等待实例，原来的 APP 已经退出了
        # 但不要创建新窗口（否则关闭后又重开）
        # 只需启动一个纯后台进程来清理并退出
        root_log.info(f"[PID={_PID}] 原始 APP 已退出，本次实例用于清理并退出")
        # 先删除锁，再退出
        _cleanup_lock(lock_file)
        os._exit(0)

    return lock_file


def main():
    # macOS: 以 Regular 策略运行，Dock 图标始终显示。
    # 之前尝试过动态切换 Accessory/Regular 来按需显示/隐藏 Dock 图标，
    # 但 macOS 对运行时 setActivationPolicy 支持不可靠（启动时设 Accessory 不生效，
    # 运行中切换方向也不稳定），改为始终 Regular，Dock 图标常驻。
    # 用户可通过 Dock 图标或 Cmd+Tab 前置应用。
    if sys.platform == "darwin":
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.setActivationPolicy(
                QGuiApplication.ActivationPolicy.Regular
            )
        except Exception:
            pass
    # ── 单例锁 ────────────────────────────────────────────────
    try:
        _install_subprocess_audit()
    except Exception:
        pass

    _lock_file = _ensure_single_instance()

    # ── VISA 驱动检测/自动安装 ────────────────────────────────
    # 在 Qt 事件循环启动前检测,确保即使 GUI 没起来日志也已写入
    try:
        from src.base import main_path
        visa_download_dir = main_path / "downloads"
        ensure_visa(
            logger=root_log,
            download_dir=visa_download_dir,
            auto_install=True,
        )
    except Exception as visa_ex:
        root_log.exception(f"[VISA] 自动安装流程异常: {visa_ex}")

    # ── 进程诊断 ─────────────────────────────────────────────
    pid = os.getpid()
    ppid = os.getppid()
    frozen = getattr(sys, 'frozen', False)
    exe = sys.executable
    root_log.info(f"[PID={pid}] Endfield 启动, 父进程 PID={ppid}, frozen={frozen}, exe={exe}")
    root_log.info(f"[PID={pid}] sys._MEIPASS={getattr(sys, '_MEIPASS', 'N/A')}")
    # 记录父进程信息（macOS 上通过 ps 获取）
    try:
        import subprocess as _sp
        parent_info = _sp.run(
            ["ps", "-p", str(ppid), "-o", "command="],
            capture_output=True, text=True, timeout=3
        )
        if parent_info.returncode == 0 and parent_info.stdout.strip():
            root_log.info(f"[PID={pid}] 父进程命令: {parent_info.stdout.strip()}")
    except Exception:
        pass

    try:
        app = TrayApp()
        app.run()
    except Exception as e:
        root_log.exception(traceback.format_exc())
        root_log.exception(str(e))
    finally:
        # 清理 PID 锁文件
        if _lock_file is not None and _lock_file.exists():
            try:
                _lock_file.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
