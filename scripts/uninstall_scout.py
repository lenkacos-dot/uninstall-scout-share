#!/usr/bin/env python3
"""
uninstall_scout.py — Cross-platform App Uninstall Remnants Scanner & Cleaner (v1.0.0)

Inspired by Tencent Lemon Cleaner (macOS) concept: scan standard paths for
orphaned files → match by bundle ID/app name → filter whitelist → report.

Cross-platform: macOS (primary) + Windows (secondary).
Python 3.9+ stdlib only — no pip dependencies.

Changes in v1.0.0:
  - main() decomposed into _run_settings, _run_undo, _run_scan, _run_clean_force
  - _size_str / _dir_size memoized via functools.lru_cache
  - Case-insensitive plist bundle ID matching
  - Thread-safe leftovers collection via threading.Lock
  - Empty directories now reported instead of skipped
  - macOS force-clean branch redundancy removed
  - AppleScript path escaping for osascript
  - POSIX folder/file type differentiation for AppleScript delete

Usage:
  python3 uninstall_scout.py                     # dry-run 扫描 + 表格
  python3 uninstall_scout.py --show              # 只显示报告（不清理）
  python3 uninstall_scout.py --clean             # 扫描 + 交互式多选清理
  python3 uninstall_scout.py --app "WeChat"      # 只看指定 App
  python3 uninstall_scout.py --json              # JSON 输出
  python3 uninstall_scout.py --clean --force     # 一键清所有（跳过选择）
  python3 uninstall_scout.py --settings          # 查看/编辑持久化配置
  python3 uninstall_scout.py --undo              # 查看撤销记录
"""

import json
import os
import shutil
import subprocess
import sys
import time
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, Dict, List, Any, Tuple

# ──────────────────────────────────────────────
# 平台检测
# ──────────────────────────────────────────────
IS_MACOS = sys.platform == 'darwin'
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform == 'linux'

if not (IS_MACOS or IS_WINDOWS):
    print(f"⚠️  未完全测试的平台: {sys.platform} — 将尝试 macOS 兼容模式", file=sys.stderr)

def _resolve(path: str) -> str:
    """解析 ~、%VAR% 和环境变量，返回绝对路径"""
    p = path
    if IS_WINDOWS:
        # Windows: expand %APPDATA%, %LOCALAPPDATA%, etc.
        p = os.path.expandvars(p)
    return str(Path(p).expanduser().resolve())


# ──────────────────────────────────────────────
# 平台特定导入
# ──────────────────────────────────────────────
if IS_MACOS:
    import plistlib
    from collections import Counter

# Windows ctypes 只在需要时惰性导入


# ──────────────────────────────────────────────
# 默认扫描路径
# ──────────────────────────────────────────────

MACOS_SCAN_PATHS = [
    {"path": "~/Library/Preferences",          "type": "plist",  "desc": "偏好设置"},
    {"path": "~/Library/Preferences/ByHost",   "type": "plist",  "desc": "主机偏好"},
    {"path": "~/Library/Caches",               "type": "subdir", "desc": "缓存"},
    {"path": "~/Library/Application Support",  "type": "subdir", "desc": "应用支持数据"},
    {"path": "~/Library/Logs",                 "type": "subdir", "desc": "日志"},
    {"path": "~/Library/Saved Application State",
                                               "type": "subdir", "desc": "窗口状态"},
    {"path": "~/Library/Containers",           "type": "subdir", "desc": "沙盒容器"},
    {"path": "~/Library/Group Containers",     "type": "subdir", "desc": "群组容器"},
    {"path": "~/Library/HTTPStorages",         "type": "subdir", "desc": "HTTP 存储"},
    {"path": "~/Library/WebKit/Domains",       "type": "subdir", "desc": "WebKit 网站数据"},
    {"path": "~/Library/LaunchAgents",         "type": "plist",  "desc": "自启动代理"},
]

WINDOWS_SCAN_PATHS = [
    {"path": "%APPDATA%",                      "type": "subdir", "desc": "Roaming AppData"},
    {"path": "%LOCALAPPDATA%",                 "type": "subdir", "desc": "Local AppData"},
    {"path": "%LOCALAPPDATA%\\Programs",       "type": "subdir", "desc": "用户程序"},
    {"path": "%LOCALAPPDATA%\\Packages",       "type": "subdir", "desc": "APPX/UWP 包"},
    {"path": "%USERPROFILE%\\.cache",          "type": "subdir", "desc": "缓存"},
    {"path": "%LOCALAPPDATA%\\Temp",           "type": "subdir", "desc": "临时文件"},
    {"path": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
                                               "type": "subdir", "desc": "启动项"},
]

SCAN_PATHS = MACOS_SCAN_PATHS if IS_MACOS else WINDOWS_SCAN_PATHS


# ──────────────────────────────────────────────
# 白名单（系统级保护）
# ──────────────────────────────────────────────

WHITELIST_BUNDLE_PREFIXES = [
    "com.apple.", "com.apple.preference", "com.apple.print.",
    "com.apple.helpd", "com.apple.SoftwareUpdate", "com.apple.store",
    "com.apple.iTunes", "com.apple.Music", "com.apple.TV",
    "com.apple.Photos", "com.apple.mail", "com.apple.MobileSMS",
    "com.apple.mobileslideshow", "com.apple.stocks", "com.apple.news",
    "com.apple.weather", "com.apple.reminders", "com.apple.mobilenotes",
    "com.apple.Preferences", "com.apple.systemevents", "com.apple.Siri",
    "com.apple.spotlight", "com.apple.dock", "com.apple.finder",
    "com.apple.systempreferences", "com.apple.screensharing",
    "com.apple.SMJobBless", "com.apple.Safari",
    "com.apple.Safari.SafeBrowsing", "com.apple.Terminal",
    "com.apple.ActivityMonitor", "com.apple.DiskUtility", "com.apple.Console",
    "com.apple.ScriptEditor2", "com.apple.KeychainAccess",
    "com.apple.archiveutility", "com.apple.TelephonyUtilities",
    "com.apple.nsurlsessiond", "com.apple.rapportd", "com.apple.sharingd",
    "com.apple.icloud", "com.apple.cloudd", "com.apple.security.",
]

WHITELIST_APP_NAMES = [
    "Safari", "Safari Technology Preview", "Xcode", "Terminal",
    "Finder", "System Settings", "System Preferences",
    "Console", "Activity Monitor", "Disk Utility",
    "Keychain Access", "Script Editor", "Archive Utility",
    "Photos", "Music", "TV", "Podcasts", "Books",
    "Notes", "Reminders", "Calendar", "Contacts",
    "Messages", "FaceTime", "Mail", "Maps",
    "App Store", "Calculator", "Chess", "Dictionary",
    "Font Book", "Image Capture", "Preview", "QuickTime Player",
    "Stickies", "TextEdit", "Time Machine", "Voice Memos",
    "Siri", "Mission Control", "Launchpad",
    "Pages", "Numbers", "Keynote",
]

# Windows 白名单 — 系统组件不清理
WINDOWS_WHITELIST_DIRS = [
    "Microsoft", "MicrosoftEdge", "Microsoft.Windows", "Windows",
    "WindowsPowerShell", "Common Files", "Mozilla Firefox",
    "Google\\Chrome", "Notepad++",
]

WHITELIST_SYSTEM_CACHE_DIRS = [
    "GeoServices", "diagnostics_agent", "com.apple.helpd",
    "sharedfilelistd", "icloudmailagent", "osanalyticshelper",
    "appleinbox", "corespeechd",
]


# ──────────────────────────────────────────────
# 持久化配置
# ──────────────────────────────────────────────

def _config_path() -> str:
    if IS_WINDOWS:
        return _resolve("%USERPROFILE%\\.uninstall_scout_config.json")
    return _resolve("~/.uninstall_scout_config.json")


def _undo_path() -> str:
    if IS_WINDOWS:
        return _resolve("%USERPROFILE%\\.uninstall_scout_undo.json")
    return _resolve("~/.uninstall_scout_undo.json")


DEFAULT_CONFIG_PATH = _config_path()
UNDO_LOG_PATH = _undo_path()

DEFAULT_CONFIG = {
    "clean_method": "trash",           # "trash" (回收站) 或 "rm" (永久删除)
    "auto_skip_in_use": True,          # 清理时自动跳过正在使用的文件
    "max_scan_workers": 8,             # 并行扫描线程数
    "sort_by": "size",                 # 排序: "size" 或 "name"
    "show_only_cleanable": False,      # 表格只显示可清理项
    "scan_paths": None,                # 自定义扫描路径（None=使用默认）
    "extra_whitelist_bundles": [],     # 额外白名单 bundle 前缀
    "extra_whitelist_apps": [],        # 额外白名单 App 名称
}


def save_config(config: dict, path: str = None) -> bool:
    """保存配置到 JSON 文件"""
    if path is None:
        path = DEFAULT_CONFIG_PATH
    try:
        with open(path, "w") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"⚠️  无法写入配置 {path}: {e}", file=sys.stderr)
        return False


def load_config(path: str = None) -> dict:
    """加载配置，不存在则返回空字典"""
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def merge_config(defaults: dict, overrides: dict) -> dict:
    """递归合并配置（override 覆盖默认值）"""
    result = dict(defaults)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge_config(result[k], v)
        else:
            result[k] = v
    return result


def get_active_scan_paths(config: dict) -> List[dict]:
    """返回生效的扫描路径（配置覆盖默认）"""
    cp = config.get("scan_paths")
    if cp:
        return cp
    return SCAN_PATHS


def get_active_whitelist_bundles(config: dict) -> List[str]:
    """返回生效的 bundle ID 白名单"""
    return WHITELIST_BUNDLE_PREFIXES + config.get("extra_whitelist_bundles", [])


def get_active_whitelist_apps(config: dict) -> List[str]:
    """返回生效的 App 名称白名单"""
    wl = list(WHITELIST_APP_NAMES)
    if IS_WINDOWS:
        wl.extend(WINDOWS_WHITELIST_DIRS)
    return wl + config.get("extra_whitelist_apps", [])


# ──────────────────────────────────────────────
# 工具函数（跨平台）
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=128)
def _size_str(byte_count: int) -> str:
    """人类可读的文件大小"""
    if byte_count < 1024:
        return f"{byte_count} B"
    elif byte_count < 1024 ** 2:
        return f"{byte_count / 1024:.1f} KB"
    elif byte_count < 1024 ** 3:
        return f"{byte_count / 1024 ** 2:.1f} MB"
    else:
        return f"{byte_count / 1024 ** 3:.2f} GB"


@functools.lru_cache(maxsize=4096)
def _dir_size(path: str) -> int:
    """递归计算目录总大小（不跟随符号链接）"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.islink(fp):
                        continue
                    total += os.lstat(fp).st_size
                except OSError:
                    continue
    except PermissionError:
        pass
    return total


def _get_mtime(path: str) -> float:
    """获取最后修改时间"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _fmt_time(ts: float) -> str:
    """时间戳 → 可读日期"""
    if ts == 0:
        return "未知"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# macOS 工具函数
# ──────────────────────────────────────────────

def _read_plist(path: str) -> Optional[dict]:
    """安全读取 plist 文件"""
    if not IS_MACOS:
        return None
    try:
        import plistlib
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def _is_in_use_macos(path: str) -> bool:
    """用 lsof 检查文件/目录是否被进程占用"""
    try:
        r = subprocess.run(
            ["lsof", path],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _is_in_use_windows(path: str) -> bool:
    """Windows: 用 msvcrt 排他锁检测文件是否被占用"""
    try:
        if os.path.isdir(path):
            # Windows 目录锁定检测不可靠，默认返回 False
            return False
        import msvcrt
        with open(path, 'rb') as f:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            except (IOError, OSError):
                return True
    except (ImportError, IOError, OSError, PermissionError):
        # 无法访问时保守认为未被占用
        return False


def _is_in_use(path: str) -> bool:
    """跨平台文件占用检测"""
    if IS_MACOS:
        return _is_in_use_macos(path)
    elif IS_WINDOWS:
        return _is_in_use_windows(path)
    return False


# ──────────────────────────────────────────────
# 收集已安装 App
# ──────────────────────────────────────────────

def collect_installed_apps() -> Dict[str, dict]:
    """
    返回 {bundle_id_or_name: {name, path, version, built_in}}
    macOS: /Applications, system_profiler, mdfind
    Windows: Program Files, registry via PowerShell
    """
    if IS_MACOS:
        return _collect_installed_macos()
    elif IS_WINDOWS:
        return _collect_installed_windows()
    return {}


def _collect_installed_macos() -> Dict[str, dict]:
    """macOS: 扫描 /Applications + system_profiler + mdfind"""
    installed = {}

    def _extract_bundle_info(app_path: str, dest: dict, built_in: bool) -> None:
        plist_path = os.path.join(app_path, "Contents", "Info.plist")
        if not os.path.isfile(plist_path):
            return
        pl = _read_plist(plist_path)
        if pl is None:
            return
        bid = pl.get("CFBundleIdentifier", "")
        if not bid:
            return
        name = (pl.get("CFBundleName", "") or
                pl.get("CFBundleDisplayName", "") or
                os.path.splitext(os.path.basename(app_path))[0])
        if bid not in dest:
            dest[bid] = {
                "name": name,
                "path": app_path,
                "version": pl.get("CFBundleShortVersionString", ""),
                "built_in": built_in,
            }

    def _scan_app_dir(base_dir: str, built_in: bool = False) -> List[dict]:
        base = _resolve(base_dir)
        if not os.path.isdir(base):
            return
        try:
            for entry in sorted(os.listdir(base)):
                app_path = os.path.join(base, entry)
                if not entry.endswith(".app") or not os.path.isdir(app_path):
                    continue
                _extract_bundle_info(app_path, installed, built_in)
        except PermissionError:
            pass

    _scan_app_dir("/Applications")
    _scan_app_dir("~/Applications")
    _scan_app_dir("/System/Applications", built_in=True)

    # system_profiler 补充
    try:
        r = subprocess.run(
            ["system_profiler", "SPApplicationsDataType", "-json"],
            capture_output=True, timeout=30, text=True,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            apps = data.get("SPApplicationsDataType", [])
            for app in apps:
                info = app.get("info") or {}
                if isinstance(info, str):
                    info = {}
                bid = info.get("CFBundleIdentifier", "")
                if not bid:
                    continue
                if bid not in installed:
                    installed[bid] = {
                        "name": app.get("_name", ""),
                        "path": app.get("path", ""),
                        "version": app.get("version", ""),
                        "built_in": False,
                    }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    # mdfind 补漏
    try:
        r = subprocess.run(
            ["mdfind", "kMDItemContentType == 'com.apple.application-bundle'"],
            capture_output=True, timeout=15, text=True,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if not line or not line.endswith(".app"):
                    continue
                if not os.path.isdir(line):
                    continue
                _extract_bundle_info(line, installed, line.startswith("/System/"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return installed


def _collect_installed_windows() -> Dict[str, dict]:
    """Windows: 扫描 Program Files + 注册表 (PowerShell)"""
    installed = {}

    def _scan_pf_dir(base_dir: str) -> int:
        """扫描 Program Files 等标准安装目录"""
        if not os.path.isdir(base_dir):
            return 0
        count = 0
        try:
            for entry in sorted(os.listdir(base_dir)):
                fp = os.path.join(base_dir, entry)
                if not os.path.isdir(fp):
                    continue
                # 检查目录下是否有 .exe 主程序
                key = entry.lower()
                if key not in installed:
                    installed[key] = {
                        "name": entry,
                        "path": fp,
                        "version": "",
                        "built_in": key.startswith("windows") or key.startswith("microsoft ")
                    }
                    count += 1
        except PermissionError:
            pass
        return count

    pf_dirs = [
        os.environ.get("PROGRAMFILES", "C:\\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
    ]
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        pf_dirs.append(os.path.join(la, "Programs"))

    for d in pf_dirs:
        _scan_pf_dir(d)

    # PowerShell 注册表扫描补充
    ps_script = (
        'Get-ItemProperty '
        'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, '
        'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, '
        'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* '
        '| Where-Object { $_.DisplayName } '
        '| Select-Object DisplayName, DisplayVersion, InstallLocation '
        '| ConvertTo-Json -Compress'
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=15, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            items = data if isinstance(data, list) else [data]
            for item in items:
                name = item.get("DisplayName", "")
                loc = item.get("InstallLocation", "") or ""
                ver = item.get("DisplayVersion", "") or ""
                if not name:
                    continue
                key = name.lower().strip()
                if key not in installed:
                    installed[key] = {
                        "name": name,
                        "path": loc,
                        "version": ver,
                        "built_in": False,
                    }
    except (subprocess.TimeoutExpired, json.JSONDecodeError,
            FileNotFoundError, OSError):
        pass

    return installed


# ──────────────────────────────────────────────
# 扫描残留（跨平台）
# ──────────────────────────────────────────────

def scan_leftovers(
    installed_bundles: Dict[str, dict],
    scan_paths: Optional[List[dict]] = None,
    app_filter: Optional[str] = None,
    config: Optional[dict] = None,
) -> Dict[str, List[dict]]:
    """
    扫描标准化路径，找出已卸载 App 的残留文件。
    返回 {group_key: [{path, size, mtime, in_use, type, desc, bundle_id}]}
    """
    if config is None:
        config = {}
    if scan_paths is None:
        scan_paths = get_active_scan_paths(config)

    known_keys = set(installed_bundles.keys())
    known_keys_lower = {k.lower() for k in known_keys}

    known_names: set = set()
    for info in installed_bundles.values():
        if info["name"]:
            known_names.add(info["name"].lower())
        p = info.get("path", "")
        if p:
            base = os.path.splitext(os.path.basename(p))[0]
            known_names.add(base.lower())

    wl_bundles = get_active_whitelist_bundles(config)
    wl_apps = get_active_whitelist_apps(config)

    leftovers: Dict[str, List[dict]] = {}
    seen_paths: set = set()
    scan_lock = Lock()

    def _match_key(candidate: str) -> Optional[str]:
        """检查 candidate 是否为已知 App 的 key（大小写不敏感）"""
        cl = candidate.lower()
        if cl in known_keys_lower:
            return "built_in" if installed_bundles.get(candidate, {}).get("built_in") else "installed"
        for prefix in wl_bundles:
            if cl.startswith(prefix.lower()):
                return "built_in"
        if IS_WINDOWS:
            for wl_dir in WINDOWS_WHITELIST_DIRS:
                if wl_dir.lower() in cl:
                    return "built_in"
        return None

    def _match_app_name(candidate_name: str) -> Optional[str]:
        cl = candidate_name.lower()
        for d in WHITELIST_SYSTEM_CACHE_DIRS:
            if d.lower() == cl:
                return "built_in"
        for pfx in wl_apps:
            if pfx.lower() == cl:
                return "built_in"
        if cl in known_names:
            return "installed"
        return None

    def _add_leftover(group_key: str, item: dict) -> None:
        if app_filter:
            fl = app_filter.lower()
            if fl not in group_key.lower():
                return
        with scan_lock:
            if item["path"] in seen_paths:
                return
            seen_paths.add(item["path"])
            if group_key not in leftovers:
                leftovers[group_key] = []
            leftovers[group_key].append(item)

    def _scan_plist(scan_dir: str, desc: str) -> List[dict]:
        """macOS: 扫描 plist 文件"""
        results = []
        d = _resolve(scan_dir)
        if not os.path.isdir(d):
            return results
        try:
            for entry in os.listdir(d):
                fp = os.path.join(d, entry)
                if not os.path.isfile(fp):
                    continue
                if not entry.endswith(".plist") or entry.endswith(".plist.lockfile"):
                    continue
                bid = os.path.splitext(entry)[0]
                status = _match_key(bid)
                if status in ("installed", "built_in"):
                    continue
                sz = os.path.getsize(fp)
                mt = _get_mtime(fp)
                in_use = _is_in_use(fp)
                results.append({
                    "path": fp,
                    "size": sz,
                    "mtime": mt,
                    "in_use": in_use,
                    "type": "plist",
                    "desc": desc,
                    "bundle_id": bid,
                })
        except PermissionError:
            pass
        return results

    def _scan_subdir(scan_dir: str, desc: str) -> List[dict]:
        """扫描子目录（跨平台）"""
        results = []
        d = _resolve(scan_dir)
        if not os.path.isdir(d):
            return results
        try:
            for entry in os.listdir(d):
                fp = os.path.join(d, entry)
                if not os.path.isdir(fp):
                    continue
                status = _match_key(entry)
                if status in ("installed", "built_in"):
                    continue
                if status is None:
                    status = _match_app_name(entry)
                    if status in ("installed", "built_in"):
                        continue
                sz = _dir_size(fp)
                mt = _get_mtime(fp)
                in_use = _is_in_use(fp)
                results.append({
                    "path": fp,
                    "size": sz,
                    "mtime": mt,
                    "in_use": in_use,
                    "type": "subdir",
                    "desc": desc,
                    "bundle_id": entry,
                    "empty_dir": sz == 0,
                })
        except PermissionError:
            pass
        return results

    max_workers = config.get("max_scan_workers", 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for sp in scan_paths:
            stype = sp.get("type", "subdir")
            sdir = sp["path"]
            sdesc = sp.get("desc", "")
            if stype == "plist" and IS_MACOS:
                futures.append(pool.submit(_scan_plist, sdir, sdesc))
            elif stype == "subdir" or stype == "plist":
                # plist on Windows → treat as subdir (no .plist extension check)
                if stype == "plist" and not IS_MACOS:
                    continue  # skip plist paths on Windows
                futures.append(pool.submit(_scan_subdir, sdir, sdesc))

        for fut in as_completed(futures):
            items = fut.result()
            for item in items:
                gk = item["bundle_id"]
                _add_leftover(gk, item)

    return leftovers


# ──────────────────────────────────────────────
# 残留理由生成（跨平台）
# ──────────────────────────────────────────────

KNOWN_APP_NAMES = {
    "com.tencent": "腾讯",
    "com.miHoYo": "米哈游/原神/崩坏",
    "com.netease": "网易",
    "com.bilibili": "哔哩哔哩",
    "com.alibaba": "阿里巴巴",
    "com.bytedance": "字节跳动/抖音",
    "com.google": "Google",
    "com.microsoft": "Microsoft",
    "com.adobe": "Adobe",
    "com.spotify": "Spotify",
    "com.slack": "Slack",
    "com.discord": "Discord",
    "com.telegram": "Telegram",
    "com.whatsapp": "WhatsApp",
    "com.zoom": "Zoom",
    "com.figma": "Figma",
    "com.notion": "Notion",
    "com.obsproject": "OBS Studio",
    "com.valvesoftware": "Steam/Valve",
    "org.mozilla": "Mozilla/Firefox",
    "org.videolan": "VLC",
    "io.redis": "Redis",
    "io.docker": "Docker",
    "io.apollographql": "Apollo",
}

# Windows 已知公司名称
WINDOWS_KNOWN_PUBLISHERS = {
    "tencent": "腾讯",
    "netease": "网易",
    "bilibili": "哔哩哔哩",
    "alibaba": "阿里巴巴",
    "bytedance": "字节跳动",
    "google": "Google",
    "microsoft": "Microsoft",
    "adobe": "Adobe",
    "spotify": "Spotify",
    "discord": "Discord",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp/Meta",
    "zoom": "Zoom",
    "notion": "Notion",
    "slack": "Slack/Salesforce",
    "obsidian": "Obsidian",
    "docker": "Docker",
    "firefox": "Mozilla Firefox",
    "chrome": "Google Chrome",
    "brave": "Brave",
    "nodejs": "Node.js",
    "python": "Python",
    "git": "Git",
}


def _clean_reason(group_key: str, items: List[dict]) -> str:
    """分析一组残留文件，返回简洁的中文理由"""
    bid_lower = group_key.lower()

    # 检查是否全是空目录
    if all(item.get("empty_dir") for item in items):
        return "已卸载 → 空目录残留（0 B）"

    # 1. 已知公司匹配 (macOS bundle ID)
    for prefix, cn_name in KNOWN_APP_NAMES.items():
        if bid_lower.startswith(prefix):
            return f"({cn_name}) 已卸载 → 应用数据残留"

    # 2. 已知公司匹配 (Windows 名称)
    for kw, cn_name in WINDOWS_KNOWN_PUBLISHERS.items():
        if kw in bid_lower:
            return f"({cn_name}) 已卸载 → 应用数据残留"

    # 3. 路径类型分析
    paths = [i["path"] for i in items]
    path_flags = []
    for p in paths:
        if IS_MACOS:
            if "/Containers/" in p:
                path_flags.append("sandbox")
            if "/Caches/" in p:
                path_flags.append("cache")
            if "/Preferences/" in p or p.endswith(".plist"):
                path_flags.append("prefs")
            if "/Application Support/" in p:
                path_flags.append("support")
            if "/Logs/" in p:
                path_flags.append("log")
            if "/Group Containers/" in p:
                path_flags.append("group")
        else:
            # Windows 路径类型推断
            p_lower = p.lower()
            if "\\cache\\" in p_lower or "\\caches\\" in p_lower:
                path_flags.append("cache")
            if "\\appdata\\roaming" in p_lower:
                path_flags.append("support")
            if "\\appdata\\local" in p_lower and "\\temp" in p_lower:
                path_flags.append("temp")
            if "\\temp\\" in p_lower:
                path_flags.append("temp")
            if "\\packages\\" in p_lower:
                path_flags.append("sandbox")

    type_map = {
        "sandbox": "沙盒容器",
        "cache": "缓存文件",
        "prefs": "偏好设置",
        "support": "应用支持数据",
        "log": "日志文件",
        "group": "群组容器",
        "temp": "临时文件",
    }

    if path_flags:
        from collections import Counter
        top_type = Counter(path_flags).most_common(1)[0][0]
        type_cn = type_map.get(top_type, "数据")
    else:
        type_cn = "应用数据"

    # 3. 检查最后修改时间
    mtimes = [i.get("mtime", 0) for i in items if i.get("mtime", 0) > 0]
    stale_hint = ""
    if mtimes:
        oldest = min(mtimes)
        days_old = (time.time() - oldest) / 86400
        if days_old > 180:
            stale_hint = f"，最后更新 {_fmt_time(oldest)}（{int(days_old)} 天前）"

    return f"已卸载 → {type_cn}残留{stale_hint}"


# ──────────────────────────────────────────────
# 输出格式化（表格 + 理由）
# ──────────────────────────────────────────────

def _build_report(leftovers: Dict[str, List[dict]]) -> List[dict]:
    """整理成按 App 分组的报告，按大小降序"""
    report = []
    for group, items in leftovers.items():
        total_size = sum(i["size"] for i in items)
        in_use_count = sum(1 for i in items if i["in_use"])
        report.append({
            "app": group,
            "total_size": total_size,
            "total_size_str": _size_str(total_size),
            "file_count": len(items),
            "in_use_count": in_use_count,
            "reason": _clean_reason(group, items),
            "files": sorted(items, key=lambda x: -x["size"]),
        })
    report.sort(key=lambda x: -x["total_size"])
    return report


def print_report(report: List[dict], json_out: bool = False,
                 show_only_cleanable: bool = False):
    """打印报告到终端 — 表格格式 + 理由列"""
    if json_out:
        print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        return

    os_name = "macOS" if IS_MACOS else ("Windows" if IS_WINDOWS else sys.platform)

    if not report:
        print("✅ 未发现残留文件，系统很干净。")
        return

    if show_only_cleanable:
        report = [r for r in report if r["in_use_count"] == 0]

    total_size = sum(r["total_size"] for r in report)
    total_files = sum(r["file_count"] for r in report)
    cleanable_size = sum(r["total_size"] for r in report if r["in_use_count"] == 0)
    in_use_groups = sum(1 for r in report if r["in_use_count"] > 0)

    print("=" * 80)
    print(f"  Uninstall Scout — {os_name} 卸载残留扫描报告")
    print("=" * 80)
    print(f"  发现 {len(report)} 组残留，共 {total_files} 个文件，{_size_str(total_size)}")
    if in_use_groups:
        print(f"  ⚠️  其中 {in_use_groups} 组有文件正在使用中（已标注 [IN USE]）")
    print()

    header = f"  {'#':>3}  {'App / Bundle ID':<32} {'大小':>10} {'文件':>6} {'理由'}"
    print(header)
    print("  " + "-" * 78)

    for idx, row in enumerate(report, 1):
        app = row["app"]
        app_display = app[:28] + "…" if len(app) > 30 else app
        in_use_mark = " ⚠️" if row["in_use_count"] > 0 else "  "
        size_str = row["total_size_str"]
        file_count = row["file_count"]
        reason = row["reason"]

        print(f"  [{idx:>2}] {app_display:<30} {size_str:>10} {file_count:>5}  {reason}{in_use_mark}")

    print("  " + "-" * 78)
    print(f"  {'':>3}  {'合计':<30} {_size_str(total_size):>10} {total_files:>5}  可释放 {_size_str(cleanable_size)}")
    if in_use_groups:
        print(f"  ⚠️  [IN USE] = 文件正在被进程占用，不建议清理")
    print("=" * 80)
    print("  提示: 使用 --clean 进入交互式选择清理")
    print("=" * 80)


# ──────────────────────────────────────────────
# 交互式选择清理
# ──────────────────────────────────────────────

def _parse_selection(input_str: str, max_num: int) -> List[int]:
    """解析用户输入的选择范围: 1,3-5,a → [1,3,4,5]"""
    raw = input_str.strip().lower()
    if raw in ("a", "all"):
        return list(range(1, max_num + 1))

    selected: List[int] = []
    parts = [p.strip() for p in raw.split(",")]
    for part in parts:
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s.strip()), int(end_s.strip())
                if start < 1 or end > max_num or start > end:
                    print(f"  ⚠️  无效范围: {part}", file=sys.stderr)
                    continue
                selected.extend(range(start, end + 1))
            except ValueError:
                print(f"  ⚠️  无法解析: {part}", file=sys.stderr)
        else:
            try:
                n = int(part)
                if n < 1 or n > max_num:
                    print(f"  ⚠️  越界: {n} (1-{max_num})", file=sys.stderr)
                    continue
                selected.append(n)
            except ValueError:
                print(f"  ⚠️  无法解析: {part}", file=sys.stderr)

    return sorted(set(selected))


def interactive_clean(report: List[dict], config: dict) -> int:
    """交互式多选清理"""
    if not report:
        print("没有可清理的残留。")
        return 0

    print_report(report, show_only_cleanable=config.get("show_only_cleanable", False))

    cleanable = [r for r in report if r["in_use_count"] == 0]
    in_use_groups = [r for r in report if r["in_use_count"] > 0]

    print()
    print("=" * 80)
    print("  交互式清理 — 选择要删除的残留组")
    print("=" * 80)
    print(f"  可清理: {len(cleanable)} 组  |  使用中(跳过): {len(in_use_groups)} 组")
    print()

    for idx, row in enumerate(cleanable, 1):
        app = row["app"]
        app_display = app[:30] + "…" if len(app) > 32 else app
        size_str = row["total_size_str"]
        files = row["file_count"]
        reason = row["reason"]
        print(f"  [{idx:>2}] 【{app_display}】  {size_str:>10}  {files:>4} 件  — {reason}")

    print()
    print("  输入要清理的编号，支持:  1,3-5,7  或  a=全部,  空输入=取消")
    choice = input(f"  选择 [1-{len(cleanable)}, a, ENTER=取消]: ").strip()

    if not choice:
        print("\n已取消，未执行任何删除。")
        return 0

    selected_indices = _parse_selection(choice, len(cleanable))
    if not selected_indices:
        print("\n未选择任何项，已取消。")
        return 0

    selected_items = []
    selected_size = 0
    print()
    print(f"  已选中 {len(selected_indices)} 个软件名下的文件:")
    print()
    for idx in selected_indices:
        row = cleanable[idx - 1]
        app = row["app"]
        size_str = row["total_size_str"]
        files = row["file_count"]
        reason = row["reason"]
        print(f"  [{idx:>2}] 【{app:<30}】  {size_str:>10}  {files:>4} 件  — {reason}")
        for f in row["files"]:
            selected_items.append(f)
            selected_size += f["size"]

    print()
    print(f"  合计: {len(selected_items)} 个文件，可释放 {_size_str(selected_size)}")
    confirm = input(f"\n确认删除以上 {len(selected_items)} 个文件? (y/N): ").strip().lower()
    if confirm != "y":
        print("已取消。")
        return 0

    ok = clean_items(selected_items, force=True, config=config)
    if ok > 0:
        print(f"\n✅ 已清理 {ok} 个文件，释放 {_size_str(selected_size)}")
        print(f"   如需恢复，查看: {UNDO_LOG_PATH}")
    else:
        print("未执行任何删除。")
    return ok


# ──────────────────────────────────────────────
# 清理引擎（跨平台）
# ──────────────────────────────────────────────

def _clean_windows_trash(items: List[dict]) -> Tuple[int, List[dict], List[tuple]]:
    """
    Windows: 用 ctypes shell32.SHFileOperationW 移到回收站
    回退: shutil.move 到临时回收目录
    
    Returns: (success_count, undo_records, errors)
    """
    success = 0
    undo_records = []
    errors = []

    # 统一的回收目录（不是真的回收站，但支持回滚）
    recycle_dir = _resolve("%USERPROFILE%\\.uninstall_scout_trash")
    try:
        os.makedirs(recycle_dir, exist_ok=True)
    except OSError:
        pass

    for item in items:
        fp = item["path"]
        if not os.path.exists(fp):
            continue
        is_dir = os.path.isdir(fp)
        try:
            basename = os.path.basename(fp.rstrip("\\/"))
            dest = os.path.join(recycle_dir, f"{int(time.time())}_{basename}")
            shutil.move(fp, dest)
            undo_records.append({
                "path": fp,
                "moved_to": dest,
                "is_dir": is_dir,
                "deleted_at": time.time(),
                "timestamp": datetime.now().isoformat(),
                "method": "trash",
            })
            success += 1
        except Exception as e:
            errors.append((fp, str(e)))

    if success > 0:
        print(f"  📦 文件已移动到回收目录: {recycle_dir}")
        print(f"  🗑️  如需彻底删除，请手动清空该目录")

    return success, undo_records, errors


def _clean_macos_trash(items: List[dict]) -> Tuple[int, List[dict], List[tuple]]:
    """macOS: 用 osascript 移废纸篓，回退 shutil.rmtree/os.remove
    
    Returns: (success_count, undo_records, errors)
    """
    success = 0
    undo_records = []
    errors = []
    
    def _escape_apple(s: str) -> str:
        """转义 AppleScript 字符串：\\ → \\\\, \" → \\\", 换行→空格"""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    for item in items:
        fp = item["path"]
        if not os.path.exists(fp):
            continue
        is_dir = os.path.isdir(fp)
        escaped = _escape_apple(fp)
        try:
            # macOS has a 31-character posix_path limit in osascript sometimes
            if is_dir:
                cmd = f'tell application "Finder" to delete POSIX folder "{escaped}"'
            else:
                cmd = f'tell application "Finder" to delete POSIX file "{escaped}"'
            result = subprocess.run(
                ["osascript", "-e", cmd],
                capture_output=True, timeout=30, text=True,
            )
            deleted_by_osa = result.returncode == 0
            # 验证文件真的被删了
            if deleted_by_osa:
                deleted_by_osa = not os.path.exists(fp)
            if not deleted_by_osa:
                # 回退
                if is_dir:
                    shutil.rmtree(fp, ignore_errors=True)
                else:
                    os.remove(fp)
                deleted_by_fallback = not os.path.exists(fp)
            else:
                deleted_by_fallback = False

            if deleted_by_osa or deleted_by_fallback:
                undo_records.append({
                    "path": fp,
                    "is_dir": is_dir,
                    "deleted_at": time.time(),
                    "timestamp": datetime.now().isoformat(),
                    "method": "trash",
                    "method_detail": "osascript" if deleted_by_osa else "fallback",
                })
                success += 1
        except Exception as e:
            errors.append((fp, str(e)))

    return success, undo_records, errors


def clean_items(items: List[dict], force: bool = False,
                config: Optional[dict] = None) -> int:
    """
    删除指定残留文件/目录。
    写 undo log 到 ~/.uninstall_scout_undo.json
    返回成功删除的条数。
    """
    if config is None:
        config = {}
    clean_method = config.get("clean_method", "trash")

    if not force:
        print("\n即将删除以下文件/目录：")
        for i, item in enumerate(items, 1):
            flag = " [IN USE - 不建议删]" if item.get("in_use") else ""
            print(f"  {i}. {item['path']}{flag}")
        confirm = input(f"\n确认删除这 {len(items)} 个? (y/N): ").strip().lower()
        if confirm != "y":
            print("已取消。")
            return 0

    if clean_method == "rm":
        # 永久删除（跨平台）
        success = 0
        undo_records = []
        errors = []
        for item in items:
            fp = item["path"]
            if not os.path.exists(fp):
                continue
            is_dir = os.path.isdir(fp)
            try:
                if is_dir:
                    shutil.rmtree(fp, ignore_errors=True)
                else:
                    os.remove(fp)
                undo_records.append({
                    "path": fp,
                    "is_dir": is_dir,
                    "deleted_at": time.time(),
                    "timestamp": datetime.now().isoformat(),
                    "method": "rm",
                })
                success += 1
            except Exception as e:
                errors.append((fp, str(e)))
        run_undo_records = undo_records
        if errors:
            print(f"\n⚠️  {len(errors)} 个文件删除失败：")
            for fp, err in errors:
                print(f"  · {fp}: {err}")

    elif IS_MACOS:
        success, run_undo_records, errors = _clean_macos_trash(items)
    elif IS_WINDOWS:
        success, run_undo_records, errors = _clean_windows_trash(items)
    else:
        # Linux / unknown: 直接永久删除
        success = 0
        run_undo_records = []
        errors = []
        for item in items:
            fp = item["path"]
            if not os.path.exists(fp):
                continue
            try:
                if os.path.isdir(fp):
                    shutil.rmtree(fp, ignore_errors=True)
                else:
                    os.remove(fp)
                run_undo_records.append({
                    "path": fp,
                    "is_dir": os.path.isdir(fp),
                    "deleted_at": time.time(),
                    "timestamp": datetime.now().isoformat(),
                    "method": "rm",
                })
                success += 1
            except Exception as e:
                errors.append((fp, str(e)))

    # 打印错误
    if errors:
        print(f"\n⚠️  {len(errors)} 个文件删除失败：")
        for fp, err in errors:
            print(f"  · {fp}: {err}")

    # 写 undo log
    if run_undo_records:
        old_undo = []
        if os.path.exists(UNDO_LOG_PATH):
            try:
                with open(UNDO_LOG_PATH) as f:
                    old_undo = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        old_undo.extend(run_undo_records)
        try:
            with open(UNDO_LOG_PATH, "w") as f:
                json.dump(old_undo, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    return success


# ──────────────────────────────────────────────
# 设置查看
# ──────────────────────────────────────────────

def show_settings(config: dict) -> None:
    """显示当前配置"""
    print("=" * 72)
    print("  Uninstall Scout — 配置")
    print("=" * 72)
    print(f"  配置文件: {DEFAULT_CONFIG_PATH}")
    print(f"  运行平台: {'macOS' if IS_MACOS else 'Windows' if IS_WINDOWS else sys.platform}")
    print()
    for key, default_val in DEFAULT_CONFIG.items():
        current = config.get(key, default_val)
        if current is None:
            current_display = "默认值"
        else:
            current_display = json.dumps(current, ensure_ascii=False)
        default_display = json.dumps(default_val, ensure_ascii=False)
        print(f"  {key}")
        print(f"    当前值: {current_display}")
        print(f"    默认值: {default_display}")
    print()
    print("  编辑: 直接编辑 JSON 文件，或用 --config <path> 指定外部配置")
    print("=" * 72)


def edit_settings_interactive(config: dict) -> dict:
    """交互式编辑配置提示"""
    print(f"编辑配置: {DEFAULT_CONFIG_PATH}")
    print("请直接编辑该 JSON 文件后重新运行本工具。")
    print()
    print("配置项说明:")
    print(f'  clean_method:          "trash"(移回收站) 或 "rm"(永久删除)')
    print(f'  auto_skip_in_use:      true=自动跳过使用中文件')
    print(f'  max_scan_workers:      并行扫描线程数')
    print(f'  sort_by:               "size"(按大小) 或 "name"(按名称)')
    print(f'  show_only_cleanable:   true=表格只显示可清理项')
    print(f'  scan_paths:            自定义路径列表 (null=默认)')
    print(f'  extra_whitelist_bundles: 额外白名单 bundle 前缀')
    print(f'  extra_whitelist_apps:    额外白名单 App 名称')
    return config


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def _run_settings(config: dict) -> None:
    """--settings / --edit 命令处理"""
    show_settings(config)


def _run_undo() -> None:
    """--undo 命令处理"""
    if os.path.exists(UNDO_LOG_PATH):
        with open(UNDO_LOG_PATH) as f:
            records = json.load(f)
        print(f"Undo log 共 {len(records)} 条记录:\n")
        for r in records:
            path = r.get("path", "?")
            ts = r.get("timestamp", "?")
            method = r.get("method", "trash")
            print(f"  [{ts}] [{method}] {path}")
    else:
        print("没有 undo 记录。")


def _run_scan(config: dict, app_filter: Optional[str] = None) -> List[dict]:
    """执行扫描并返回报告"""
    os_name = "macOS" if IS_MACOS else ("Windows" if IS_WINDOWS else sys.platform)
    print(f"🔍 正在收集已安装 App 列表 ({os_name})...", file=sys.stderr)
    t0 = time.time()
    installed = collect_installed_apps()
    t1 = time.time()
    print(f"   ✓ 发现 {len(installed)} 个已安装 App ({t1 - t0:.1f}s)", file=sys.stderr)

    print("🔍 正在扫描残留...", file=sys.stderr)
    scan_paths = get_active_scan_paths(config)
    leftovers = scan_leftovers(installed, scan_paths, app_filter=app_filter, config=config)
    t2 = time.time()
    print(f"   ✓ 扫描完成 ({t2 - t1:.1f}s)", file=sys.stderr)

    return _build_report(leftovers)


def _run_clean_force(report: List[dict], config: dict) -> None:
    """--clean --force: 一键清理所有可清理项"""
    all_items = []
    for row in report:
        for f in row["files"]:
            if not f["in_use"] or not config.get("auto_skip_in_use", True):
                all_items.append(f)

    if not all_items:
        print("没有可清理的文件。")
        return

    total_sz = sum(i["size"] for i in all_items)
    print(f"\n  一键清理: {len(all_items)} 个文件，释放 {_size_str(total_sz)}")

    ok = clean_items(all_items, force=True, config=config)
    if ok > 0:
        print(f"\n✅ 已清理 {ok} 个文件，释放 {_size_str(total_sz)}")
        print(f"   如需恢复，查看: {UNDO_LOG_PATH}")


def main():
    """主入口：解析参数、加载配置、分发子命令"""
    import argparse

    os_name = "macOS" if IS_MACOS else ("Windows" if IS_WINDOWS else sys.platform)

    parser = argparse.ArgumentParser(
        description=f"Uninstall Scout — {os_name} 卸载残留扫描清理 (跨平台)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python3 uninstall_scout.py                     # dry-run 扫描 + 表格
  python3 uninstall_scout.py --show              # 只显示报告
  python3 uninstall_scout.py --app 微信          # 只看指定 App
  python3 uninstall_scout.py --clean             # 扫描 + 交互式多选清理
  python3 uninstall_scout.py --clean --force     # 扫描 + 一键清理全部
  python3 uninstall_scout.py --json              # JSON 输出
  python3 uninstall_scout.py --settings          # 查看/编辑配置
  python3 uninstall_scout.py --undo              # 查看 undo 日志
  python3 uninstall_scout.py --config my.json    # 使用外部配置
        """,
    )
    parser.add_argument("--app", help="只扫描指定 App 的残留 (模糊匹配)")
    parser.add_argument("--clean", action="store_true", help="扫描后交互式多选清理")
    parser.add_argument("--force", action="store_true", help="跳过选择 + 确认 (需配合 --clean)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出报告")
    parser.add_argument("--show", action="store_true", help="只显示报告表格（不进入清理流程）")
    parser.add_argument("--config", help="外部配置文件路径 (JSON)")
    parser.add_argument("--settings", action="store_true", help="查看/编辑持久化配置")
    parser.add_argument("--edit", action="store_true", help="交互式编辑配置")
    parser.add_argument("--undo", action="store_true", help="显示 undo log 记录")
    parser.add_argument("--restore-undo", action="store_true", help="从 undo log 恢复 (复制回来)")

    args = parser.parse_args()

    # ── 加载配置 ──
    config = merge_config(dict(DEFAULT_CONFIG), load_config())

    # 外部配置文件覆盖
    if args.config:
        cp = _resolve(args.config)
        if os.path.isfile(cp):
            ext_conf = load_config(cp)
            config = merge_config(config, ext_conf)
            print(f"📋 已加载外部配置: {cp}", file=sys.stderr)

    # ── 无参数子命令（无需扫描）──
    if args.settings or args.edit:
        _run_settings(config)
        return

    if args.undo:
        _run_undo()
        return

    # ── 需要扫描的子命令 ──
    report = _run_scan(config, app_filter=args.app)

    if args.show or not args.clean:
        print_report(report, json_out=args.json,
                     show_only_cleanable=config.get("show_only_cleanable", False))
        return

    # ── --clean ──
    if args.clean:
        if args.force:
            print_report(report, json_out=args.json,
                         show_only_cleanable=config.get("show_only_cleanable", False))
            _run_clean_force(report, config)
        else:
            interactive_clean(report, config)


if __name__ == "__main__":
    main()