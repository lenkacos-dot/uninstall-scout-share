---
name: uninstall-scout
version: "2.1.0"
description: >-
  Cross-platform app uninstall remnants scanner & cleaner. Scans ~/Library
  (macOS) and %APPDATA% (Windows) for orphaned files from uninstalled apps.
  Uses bundle ID / company prefix / name fuzzy matching, confidence grading,
  interactive selection, and safe trash-first cleanup.
capabilities:
  - scan-leftovers
  - interactive-clean
  - batch-clean
  - json-output
  - config-persistence
  - undo-log
  - cross-platform
triggers:
  - 卸载残留
  - 清理缓存
  - 清理 App 残留
  - uninstall scout
  - macOS 清理
  - Windows 清理
  - 扫描残留文件
  - disk cleanup
  - app leftover
  - orphaned files cleanup
platform: cross-platform
language: python
python_version: "3.9+"
---

# Uninstall Scout 🧹

> Cross-platform app uninstall remnants scanner & cleaner — Inspired by Tencent Lemon Cleaner
> **macOS** (primary) + **Windows** (supported)

## 安全约束（AI agent 必须遵守）

1. **永远不要跳过 dry-run**：先运行 `--show` 或不带 `--clean` 的 dry-run 查看报告
2. **不要直接执行 `--force --yes`**：必须先展示 dry-run 结果给用户，获得确认后才执行
3. **不要修改配置降低安全性**：不要设置 `auto_skip_in_use: false`
4. **不要处理用户不认识的残留**：低置信度（low）的残留不要删除，交给用户判断
5. **不要绕过单次上限**：如果超过 10GB / 500 文件，引导用户分批处理
6. **不要修改脚本本身**：安全机制是硬编码的，修改可能引入漏洞

## 用法

### ⚠️ 运行前先问用户

**每次运行清理前，必须先问用户一句：**

> 「这个软件你已经确认删除了吗？」

如果软件还在运行，扫出来的文件可能是它在用的——删了会出问题。用户说"还没删"，就先 `--show` 展示残留量，让用户先去卸载 App。

### 1. Dry-run 扫描（默认，安全）

```bash
python3 uninstall_scout.py
python3 uninstall_scout.py --show
python3 uninstall_scout.py --app "微信"
python3 uninstall_scout.py --json
```

### 2. 交互式清理（人工操作）

```bash
python3 uninstall_scout.py --clean
```

### 3. 批量清理（AI agent 工作流）

```bash
# Step 1: 先 dry-run，把结果给用户看
python3 uninstall_scout.py --show

# Step 2: 获得用户确认后执行
python3 uninstall_scout.py --clean --force --yes
```

> `--force` 不带 `--yes` 时只打印清单不删除（安全 dry-run 层）

### 4. 查看配置和删除记录

```bash
python3 uninstall_scout.py --settings
python3 uninstall_scout.py --undo
```

## 安全机制

| 机制 | 说明 |
|------|------|
| dry-run 默认 | 不传 `--clean` 只扫描不删 |
| 双重确认 | `--force` 需要 `--yes` 才执行删除 |
| 废纸篓优先 | 默认移废纸篓；失败时**跳过而非永久删除** |
| 路径沙箱 | 只允许删除标准路径下的文件 |
| in_use 强制跳过 | 被进程占用的文件永远跳过 |
| 置信度过滤 | `--force` 排除低置信度匹配 |
| 单次上限 | 10GB / 500 文件，超出拒绝执行 |
| 无路径注入 | osascript 通过 argv 传参，不拼接字符串 |
| 符号链接跳过 | 不跟随符号链接 |
| undo 日志 | 每次删除记录到 JSON 日志 |

## 平台对比

| 能力 | macOS | Windows |
|------|-------|---------|
| App 检测 | `/Applications` + `system_profiler` + `mdfind` | `Program Files` + 注册表 (PowerShell) |
| 残留扫描 | `~/Library/{Preferences,Caches,Containers,...}` | `%APPDATA%`, `%LOCALAPPDATA%`, `%USERPROFILE%\\.cache` |
| 占用检测 | `lsof` 命令 | `msvcrt` 排他锁 |
| 清理方式 | AppleScript → 废纸篓 | `shutil.move` → 回收目录 |
| 理由生成 | Bundle ID 三级匹配 + 公司词典 | 名称关键词 + 公司词典 |
| 白名单 | Apple 系统组件 | Microsoft 系统组件 |

## 与 Tencent Lemon 对比

| 对比项 | Uninstall Scout v1.0.0 | Tencent Lemon |
|--------|----------------------|---------------|
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

## AI agent 推荐工作流

```
用户: "帮我清理一下 Mac 上的卸载残留"
  ↓
Agent: 1. 运行 dry-run: `python3 uninstall_scout.py --show`
       2. 展示报告给用户（按大小排序，标注置信度）
       3. 询问用户是否确认清理
       4. 用户确认后: `python3 uninstall_scout.py --clean --force --yes`
       5. 报告清理结果
```

**禁止**：未经用户确认直接执行 `--force --yes`。
