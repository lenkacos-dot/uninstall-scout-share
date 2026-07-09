# Uninstall Scout — Hermes Skill 🧹

> Cross-platform app uninstall remnants scanner & cleaner. v1.0.0

## Files

```
uninstall-scout/          ← 个人版 (带个人数据)
├── SKILL.md              ← 文档 + 用法
├── PROMPT.md             ← AI agent 指导手册
├── scripts/
│   └── uninstall_scout.py  ← 主脚本 (1423 lines)
└── config/               ← 持久化配置

~/Desktop/AI AGENT SKILL/uninstall-scout-share/  ← 分享版 (干净数据)
```

## Quick Start

```bash
cd ~/.hermes/skills/uninstall-scout/scripts
python3 uninstall_scout.py --show          # dry-run 扫描
python3 uninstall_scout.py --clean         # 交互式清理
python3 uninstall_scout.py --app 微信      # 只看某个 App
```

## v1.0.0

- Thread-safe leftovers collection (threading.Lock)
- Bundle ID 字段修复 (CFBundleIdentifier 代替 _SPCommandLineArguments)
- AppleScript 路径转义防注入
- macOS force-clean 分支精简
- _size_str / _dir_size lru_cache 加速
- Plist Bundle ID 大小写不敏感匹配
- 空目录展示 + type hints 全部补齐
