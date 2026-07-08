# Uninstall Scout 🧹

> 跨平台卸载残留扫描清理工具 — Inspired by Tencent Lemon Cleaner
> **macOS** (主) + **Windows** (支持)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-13+-000000?logo=apple&logoColor=white)](https://apple.com)
[![Windows](https://img.shields.io/badge/Windows-10+-0078D6?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![AI Agent Friendly](https://img.shields.io/badge/AI_Agent-Friendly-FF6B6B)](PROMPT.md)

---

## 跨平台架构

| 能力 | macOS | Windows |
|------|-------|---------|
| App 检测 | `/Applications` + `system_profiler` + `mdfind` | `Program Files` + 注册表 (PowerShell) |
| 残留扫描 | `~/Library/{Preferences,Caches,Containers,...}` | `%APPDATA%`, `%LOCALAPPDATA%`, `%USERPROFILE%\\.cache` |
| 占用检测 | `lsof` 命令 | `msvcrt` 排他锁 |
| 清理方式 | AppleScript → 废纸篓 | `shutil.move` → 回收目录 |
| 理由生成 | Bundle ID 三级匹配 + 公司词典 | 名称关键词 + 公司词典 |
| 白名单 | Apple 系统组件 | Microsoft 系统组件 |

**自动检测** — 脚本启动时自动识别 `sys.platform`，切换对应代码路径。

---

## 为什么需要它？

卸载 App 后残留文件散落各处：

| 路径 (macOS) | 路径 (Windows) | 类型 | 典型大小 |
|-------------|---------------|------|----------|
| `~/Library/Containers/` | `%LOCALAPPDATA%\Packages\` | 沙盒容器 | **几十 GB** |
| `~/Library/Caches/` | `%LOCALAPPDATA%\Cache\` | 缓存 | 几百 MB |
| `~/Library/Application Support/` | `%APPDATA%\..\` | 应用支持数据 | 几百 MB |
| `~/Library/Preferences/` | 注册表 (仅 macOS) | 偏好设置 | 几 KB |

**你的数据举例 (macOS):** 扫出 95 组残留 / 1.37 GB

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **跨平台** | macOS + Windows 自动识别，统一 CLI |
| **并行扫描** | 8 线程同时扫描 11 个标准路径 |
| **三级匹配** | bundle ID → 公司前缀 → 名称模糊 |
| **表格 + 理由** | 每项残留都列出「为什么可以删」|
| **交互式选择** | 输入 `1,3-5,7` 或 `a` 选要清的组 |
| **实时检查** | macOS: `lsof` / Windows: 排他锁检测占用 |
| **undo 日志** | 每次清理写入 JSON |
| **持久化配置** | `~/.uninstall_scout_config.json` (`%USERPROFILE%\...`) |
| **AI Agent 友好** | 附带 `PROMPT.md` 指导任何 AI 使用 |

---

## 安装

```bash
# 1. 克隆
git clone https://github.com/lenkacos-dot/uninstall-scout-share

# 2. 直接运行（零依赖，stdlib only）
python3 uninstall-scout/scripts/uninstall_scout.py --show
```

---

## 用法

```bash
# 干跑 — 只扫描，显示表格 + 理由
python3 uninstall_scout.py --show

# 交互式多选清理（推荐）
python3 uninstall_scout.py --clean

# 只看某个 App 的残留
python3 uninstall_scout.py --app 微信

# 一键清理所有
python3 uninstall_scout.py --clean --force

# JSON 输出（用于管道）
python3 uninstall_scout.py --json

# 查看/编辑配置
python3 uninstall_scout.py --settings

# 查看以前删了什么
python3 uninstall_scout.py --undo
```

---

## 交互式选择示例

```
  Uninstall Scout — macOS 卸载残留扫描报告
================================================================================
  发现 29 组残留，共 32 个文件，1.42 GB

    #  App / Bundle ID                    大小    文件  理由
  ──────────────────────────────────────────────────────────────────────────────
  [ 1] com.workbuddy.workbuddy.Bund…  1.13 GB    1   已卸载 → 缓存文件残留
  [ 2] bilibili                       222 MB     2   (哔哩哔哩) 已卸载 → ...
  [ 3] group.com.apple.chronod       71.7 MB     1   已卸载 → 群组容器残留
  ...

  输入要清理的编号 (支持: 1,3-5,7 或 a=全部, ENTER=取消)
  选择 [1-17, a, ENTER=取消]: 1,3-5

  选中的残留 (4 组):
    [ 1] com.workbuddy...  1.13 GB  1 件  已卸载 → 缓存文件残留
    [ 3] Google            531 KB   1 件  (Google) 已卸载 → 应用数据残留
    ...

  确认删除以上 5 个文件? (y/N): y
```

---

## 配置 (`~/.uninstall_scout_config.json` / `%USERPROFILE%\...`)

```json
{
  "clean_method": "trash",
  "auto_skip_in_use": true,
  "max_scan_workers": 8,
  "show_only_cleanable": false,
  "extra_whitelist_bundles": [],
  "extra_whitelist_apps": []
}
```

---

## 与 Tencent Lemon 对比

| 对比项 | Uninstall Scout v1.0.0 | Tencent Lemon |
|--------|----------------|---------------|
| 平台 | macOS + Windows | macOS only |
| 扫描 | 并行 8 线程 | 顺序 NSEnumerator |
| 占用检测 | ✅ lsof / msvcrt | ❌ 无 |
| 理由列 | ✅ 每项生成 | ❌ 只标大小 |
| 交互选择 | ✅ `1,3-5,a` | ✅ 勾选 |
| 持久化配置 | ✅ JSON | ❌ 无 |
| undo 日志 | ✅ JSON | ❌ 废纸篓 |
| 跨 AI Agent | ✅ PROMPT.md | ❌ |
| 语言 | Python 3.9+ (stdlib) | Objective-C |
| 依赖 | 无 | macOS SDK |

---

## 文件结构

```
uninstall-scout/
├── README.md        ← 本文档
├── PROMPT.md        ← AI Agent 指导手册
├── LICENSE
└── scripts/
    └── uninstall_scout.py  ← 主脚本 (跨平台)
```

---

## AI Agent 兼容

任何 AI agent (Claude, ChatGPT, DeepSeek, Hermes, Cursor 等) 读取 `PROMPT.md` 后即可理解并使用本工具：

- `--show`: 干跑无副作用
- `--json`: 机器可读输出
- 无需任何外部依赖，纯 stdlib

---

## 安全机制

1. **dry-run 默认** — 不传 `--clean` 只扫描不删
2. **实时占用检测** — 被使用的文件跳过
3. **双重确认** — 选择 + `y` 确认
4. **undo 日志** — 恢复路径
5. **白名单** — 系统组件全部保护

---

## 已知局限

- macOS: 部分容器有 SIP 保护须 `sudo`
- Windows: 回收站用 shutil.move 替代原生 Shell API
- 只扫描用户级路径，不处理系统级残留

---

MIT © zhenqingsu