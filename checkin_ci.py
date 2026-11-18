# -*- coding: utf-8 -*-
"""GitHub Actions 专用签到入口：Qoder 国际版 / Qoder CN / Trae CN / WorkBuddy。

不读取本机安装目录，也不修改本机签到脚本：
- Qoder 设备身份：从 QODER_MACHINE_JSON（runtime-info 输出，裸 JSON 或 base64）注入
- Trae 登录态：从 TRAE_STORAGE_B64（storage.json 的 base64）还原到临时 APPDATA
- WorkBuddy 登录态：从 WORKBUDDY_AUTH_B64（workbuddy-desktop.info 的 base64）还原

用法：
  python checkin_ci.py

退出码：全部成功（或未配置而跳过）0，任一失败 1。
"""
import base64
import json
import os
import sys
import tempfile
from datetime import datetime

# Windows 控制台默认 GBK，中文日志会花屏；Actions/Unix 环境本就是 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# runtime-info 输出字段 -> 请求头（与 qoder_checkin.MACHINE_HEADERS 一致）
MACHINE_FIELDS = (
    ("machineToken", "Cosy-MachineToken"),
    ("machineCode", "Cosy-MachineCode"),
    ("machineType", "Cosy-MachineType"),
)


def log(message):
    print(message, flush=True)


def parse_json_blob(raw, name):
    """解析裸 JSON 或 base64 编码的 JSON，失败抛 ValueError。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("%s 为空" % name)
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        decoded = base64.b64decode(text).decode("utf-8-sig")
        return json.loads(decoded)
    except Exception:
        raise ValueError("%s 既不是合法 JSON，也不是 base64 编码的 JSON" % name)


def machine_headers_from_json(raw):
    """把 runtime-info JSON 转成 Cosy-Machine* 请求头。"""
    doc = parse_json_blob(raw, "QODER_MACHINE_JSON")
    if not isinstance(doc, dict):
        raise ValueError("QODER_MACHINE_JSON 顶层必须是对象")
    headers, missing = {}, []
    for source, header in MACHINE_FIELDS:
        value = doc.get(source)
        if isinstance(value, str) and value:
            headers[header] = value
        else:
            missing.append(source)
    if missing:
        raise ValueError("QODER_MACHINE_JSON 缺少字段：%s" % ", ".join(missing))
    return headers


def materialize_trae_storage(raw):
    """把 TRAE_STORAGE_B64 还原成临时 APPDATA 下的 Trae CN storage.json，返回 APPDATA。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("未配置 TRAE_STORAGE_B64")
    try:
        data = base64.b64decode(text)
        json.loads(data.decode("utf-8-sig"))
    except Exception:
        raise ValueError("TRAE_STORAGE_B64 不是有效的 base64 JSON")

    appdata = tempfile.mkdtemp(prefix="trae-appdata-")
    target = os.path.join(
        appdata, "Trae CN", "User", "globalStorage", "storage.json"
    )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)
    return appdata


def materialize_workbuddy_auth(raw):
    """把 WORKBUDDY_AUTH_B64 还原成临时凭据文件，返回路径。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("未配置 WORKBUDDY_AUTH_B64")
    try:
        data = base64.b64decode(text)
        json.loads(data.decode("utf-8-sig"))
    except Exception:
        raise ValueError("WORKBUDDY_AUTH_B64 不是有效的 base64 JSON")

    path = os.path.join(
        tempfile.mkdtemp(prefix="workbuddy-auth-"), "workbuddy-desktop.info"
    )
    with open(path, "wb") as f:
        f.write(data)
    return path


def run_qoder():
    import qoder_checkin

    raw = os.environ.get("QODER_MACHINE_JSON", "").strip()
    if raw:
        try:
            headers = machine_headers_from_json(raw)
        except ValueError as exc:
            log("[ci] ERROR: %s" % exc)
            return 1
        qoder_checkin._runtime_info_cache = headers
        qoder_checkin._runtime_info_loaded = True
        log("[ci] 已注入设备身份（%d 个请求头）" % len(headers))
    else:
        log("[ci] ⚠️ 未配置 QODER_MACHINE_JSON，Qoder 国际版可能拿不到每日活动")
    return qoder_checkin.main()


def run_trae():
    try:
        appdata = materialize_trae_storage(os.environ.get("TRAE_STORAGE_B64", ""))
    except ValueError as exc:
        log("[ci] ERROR: %s" % exc)
        return 1
    # trae_checkin.scan_targets() 在运行时读取 APPDATA
    os.environ["APPDATA"] = appdata
    import trae_checkin

    return trae_checkin.main()


def run_workbuddy():
    raw = os.environ.get("WORKBUDDY_AUTH_B64", "").strip()
    if not raw:
        log("[ci] 未配置 WORKBUDDY_AUTH_B64，跳过 WorkBuddy")
        return None
    try:
        path = materialize_workbuddy_auth(raw)
    except ValueError as exc:
        log("[ci] ERROR: %s" % exc)
        return 1
    os.environ["WORKBUDDY_AUTH_FILE"] = path
    import signin

    # signin.main() 从 sys.argv 取命令，这里固定为 auto（签到 + 成长中心）
    original = sys.argv
    sys.argv = [original[0], "auto"]
    try:
        return signin.main()
    finally:
        sys.argv = original


def write_summary(rows):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## 签到结果", "", "| 入口 | 结果 |", "|---|---|"]
    for name, ok in rows:
        result = "✅ 成功" if ok else ("⏭ 跳过" if ok is None else "❌ 失败")
        lines.append("| %s | %s |" % (name, result))
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        log("[ci] ⚠️ 写入 Step Summary 失败：%s" % exc.__class__.__name__)


def _run(name, func):
    try:
        code = func()
    except Exception as exc:
        log("[ci] ERROR: %s 执行异常：%s: %s" % (name, exc.__class__.__name__, exc))
        return False
    return None if code is None else code == 0


def main():
    started = datetime.now()
    log("[%s] [ci] 开始签到：Qoder / Qoder CN / Trae CN / WorkBuddy"
        % started.strftime("%Y-%m-%d %H:%M:%S"))

    rows = [
        ("Qoder / Qoder CN", _run("Qoder", run_qoder)),
        ("Trae CN", _run("Trae CN", run_trae)),
        ("WorkBuddy", _run("WorkBuddy", run_workbuddy)),
    ]

    write_summary(rows)
    print()
    log("[ci] 汇总：")
    for name, ok in rows:
        log("  %s %s" % ("✅" if ok else ("⏭" if ok is None else "❌"), name))
    elapsed = (datetime.now() - started).total_seconds()
    log("[ci] 用时 %.0fs" % elapsed)
    return 0 if all(ok is not False for _, ok in rows) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已手动中断")
        sys.exit(130)
