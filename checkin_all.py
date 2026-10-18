# -*- coding: utf-8 -*-
"""一次签三个：Qoder CN / Trae CN / WorkBuddy 统一入口。

依次调用同目录下的三个签到脚本（子进程隔离，互不影响），最后汇总：
  1. qoder_checkin.py          Qoder CN 每日签到（需环境变量 QODERCN_PAT）
  2. trae_checkin.py           Trae CN / TRAE SOLO CN 签到（读本机客户端登录态）
  3. signin.py auto            WorkBuddy 签到 + 成长中心（读本机客户端登录态）

用法：
  python checkin_all.py          # 三个全跑
  python checkin_all.py 2 3      # 只跑第 2、3 个（支持指定序号子集）

任一失败退出码为 1，全部成功为 0。单个任务超时按失败处理，不拖死整体。
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 900  # WorkBuddy 内部预算 420s，这里只兜底防卡死

# (显示名, 脚本文件, 额外参数)
TASKS = [
    ("Qoder CN", "qoder_checkin.py", []),
    ("Trae CN", "trae_checkin.py", []),
    ("WorkBuddy", "signin.py", ["auto"]),
]


def _reconfigure_stdout():
    # Windows 控制台默认 GBK，中文/emoji 日志会花屏或抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _ensure_qoder_pat():
    """QODERCN_PAT 缺失时回退读注册表用户环境变量。

    解决「保存到用户环境变量后，先启动的常驻 shell 读不到新值」的问题；
    非 Windows 平台或读取失败则跳过，交给 qoder_checkin.py 自己报错。
    """
    if os.environ.get("QODERCN_PAT"):
        return
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "QODERCN_PAT")
        if value:
            os.environ["QODERCN_PAT"] = value
    except OSError:
        pass


def _print_header(title):
    print()
    print("=" * 56)
    print(f"  {title}")
    print("=" * 56)


def run_task(display_name, script_name, extra_args):
    """跑单个签到脚本，返回 (是否成功, 说明)。"""
    script_path = BASE_DIR / script_name
    _print_header(f"{display_name} —— python {script_name} {' '.join(extra_args)}".strip())
    if not script_path.is_file():
        return False, f"脚本不存在：{script_path}"
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), *extra_args],
            cwd=str(BASE_DIR),
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"超时（>{TIMEOUT_SECONDS}s），已强制终止"
    except OSError as exc:
        return False, f"无法启动子进程：{exc}"
    if completed.returncode == 0:
        return True, "成功"
    return False, f"脚本退出码 {completed.returncode}"


def main():
    _reconfigure_stdout()
    _ensure_qoder_pat()

    # 可选：用序号指定子集，如 python checkin_all.py 2 3
    selected = sys.argv[1:]
    tasks = TASKS
    if selected:
        try:
            tasks = [TASKS[int(i) - 1] for i in selected]
        except (ValueError, IndexError):
            print(f"参数无效：{' '.join(selected)}（可用 1~{len(TASKS)} 指定任务子集）")
            return 2

    started = datetime.now()
    print(f"[{started:%Y-%m-%d %H:%M:%S}] 开始签到，共 {len(tasks)} 项")

    results = []
    for display_name, script_name, extra_args in tasks:
        ok, note = run_task(display_name, script_name, extra_args)
        results.append((display_name, ok, note))

    _print_header("汇总")
    for display_name, ok, note in results:
        mark = "✅" if ok else "❌"
        print(f"{mark} {display_name:<12} {note}")
    all_ok = all(ok for _, ok, _ in results)
    elapsed = (datetime.now() - started).total_seconds()
    print(f"\n总计：{sum(ok for _, ok, _ in results)}/{len(results)} 成功，用时 {elapsed:.0f}s")
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断")
        sys.exit(130)
