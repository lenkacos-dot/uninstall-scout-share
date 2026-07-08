# Uninstall Scout — AI Agent Prompt

> This file tells **any AI agent** (Claude, ChatGPT, DeepSeek, Hermes, etc.) how to understand and use this tool.

## What is Uninstall Scout?

A cross-platform (macOS + Windows) Python tool that:
1. Scans installed applications using native system detection
2. Finds leftover files from **already uninstalled** apps in standard cache/config/data directories
3. Shows a table with: App/Bundle ID → Size → File Count → **Reason why it can be deleted**
4. Lets you interactively pick which leftovers to clean (`1,3-5,a` format)
5. Supports dry-run (default), JSON output, and undo logging

## How it works

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ collect_installed│───>│ scan_leftovers() │───>│ print_report()   │
│ _apps()          │    │ (parallel scan)   │    │ (table + reasons)│
└──────────────────┘    └──────────────────┘    └──────────────────┘
                              │
                         ┌────┴────┐
                         │ interactive_clean()  │── 1,3-5,a selection
                         │ clean_items()        │── undo log
                         └─────────────────────┘
```

## Platform detection

The script detects OS at runtime and switches code paths:

| Feature | macOS (`sys.platform == 'darwin'`) | Windows (`sys.platform == 'win32'`) |
|---------|-----------------------------------|--------------------------------------|
| App detection | /Applications, system_profiler, mdfind, plist scanning | Program Files, registry via PowerShell |
| Leftover paths | ~/Library/{Preferences,Caches,Containers,...} | %APPDATA%, %LOCALAPPDATA%, %USERPROFILE%\\.cache, etc. |
| In-use check | `lsof` command | `msvcrt.locking()` exclusive-lock probe |
| Clean method | AppleScript → Trash | Move to Recycle Bin via ctypes |
| Config format | JSON (~/.uninstall_scout_config.json) | JSON (%USERPROFILE%\\.uninstall_scout_config.json) |

## Command-line interface

```bash
# Dry-run: scan + show table (safe, no deletion)
python3 uninstall_scout.py --show

# Scan + pick what to clean
python3 uninstall_scout.py --clean

# One-app filter
python3 uninstall_scout.py --app "WeChat"

# JSON output (for piping)
python3 uninstall_scout.py --json

# Nuclear option
python3 uninstall_scout.py --clean --force

# Config management
python3 uninstall_scout.py --settings
python3 uninstall_scout.py --config my_settings.json

# Undo log
python3 uninstall_scout.py --undo
```

## If you're an AI agent running this:

1. **Always run with `--show` first** (dry-run, no side effects)
2. Parse the table output to show the user what was found
3. If user wants cleanup, run with `--clean` and pipe selections interactively
4. Check `--settings` before first run to see current configuration
5. For safety: `--clean --force` skips all confirmations — use only after user explicitly requests it

## Classes of leftovers detected

The scanner finds 8 categories of leftovers:
- **plist**: Preference files (macOS `~/Library/Preferences/*.plist`)
- **subdir**: Container/cache/support directories
- **sandbox**: App sandbox containers (`Containers/`)
- **cache**: Cached data (`Caches/`)
- **prefs**: Preference files
- **support**: Application Support data
- **log**: Log files
- **group**: Group containers (shared between apps)

## Safety mechanisms

1. Dry-run by default (no deletion without `--clean`)
2. `lsof`/`msvcrt` real-time in-use check skips locked files
3. Double confirmation: choose items → confirm with `y`
4. Undo log written at first deletion
5. Built-in whitelist: system apps, Apple/Microsoft internal daemons
6. Customizable: extra whitelist via config JSON

## File structure

```
uninstall-scout/
├── README.md         ← Human-readable documentation
├── PROMPT.md         ← ← THIS FILE — AI agent instructions
├── LICENSE
└── scripts/
    └── uninstall_scout.py  ← Main script (cross-platform Python 3.9+)
```

**Python stdlib only** — no pip install required.