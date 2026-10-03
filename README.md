# Su1ra (सूत्र)

A local, terminal style desktop gui app for [Ollama][Backend]( : https://ollama.com) models. Removing the hassle of setting up agentic and tool calls externally for Ollama.
Everything runs on your machine, your models, your data, no cloud, no accounts.

```
React + Vite frontend  →  FastAPI backend (:8000)  →  your Ollama server
   (dark console UI)        (also serves the UI)        (localhost:11434)
                                    ↓
                          SQLite at ~/.local/share/su1ra/
```

## Features

- **Streaming chat** with markdown, LaTeX math (KaTeX), and collapsible `// thinking` blocks
- **True tool-calling** — tool-capable models execute Python through a real subprocess and read the output; works proactively (the model decides when to run code)
- **Built-in Python IDE** — real PTY-backed terminal: ANSI colors, progress bars, interactive `input()`, Ctrl-C; auto-opens when the model presents Python code
- **Chat ↔ IDE bridge** — run code from chat with one click, attach IDE runs back into the conversation
- **Command console** — the only navigation surface; tab-complete everything:

  | Command | What it does |
  |---|---|
  | `/help` | list all commands |
  | `/models` | list models; `/models <name|n>` to select |
  | `/newchat` | start a new conversation |
  | `/chats` | list chats; `/chats <n|id>` to open |
  | `/delchat` | delete a chat |
  | `/settings` | open the settings modal |
  | `/stats` | toggle per-reply performance stats |
  | `/eject` | shut down the Ollama server |
  | `/connect` | start / reconnect Ollama |
  | `/ide` | toggle the Python IDE pane |

- 10 accent themes, persistent history in SQLite, per-chat system prompt / temperature / context length

## Requirements

- [Ollama](https://ollama.com/download) installed (the app detects or starts it for you)
- At least one tool-capable model, e.g.:
  ```
  ollama pull qwen2.5-coder:7b
  ```
*I personally use ornith1.5:9b*

## Install

### Windows

Download `Su1ra-setup-x64.exe` from releases and run it. The installer offers to fetch the Ollama server (command-line engine only — Su1ra is the GUI and starts/stops it for you); if you already have Ollama installed, uncheck it. A full Ollama desktop app option (its own chat GUI + tray icon) is available as an alternative.

### Linux

Git pull (Linux users, you know the drill):

```bash
git clone https://github.com/<you>/su1ra.git && cd su1ra
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && yarn && yarn build && cd ..
.venv/bin/python desktop.py
```

Requires GTK + WebKitGTK (present on most desktop distros).

### From source

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && yarn && yarn build && cd ..
.venv/bin/python desktop.py
```

## Building the packages

Linux users run from source (above), so the only packaged artifact is the Windows installer.

Windows (run on a Windows machine in the activated venv, with [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed):

```bat
packaging\build-windows.bat
```
## Acknowledgements
*This project was developed with the assistance of zai/glm5.3-flash for drafting , testing, and debugging and code.*


## Data

Everything lives in `~/.local/share/su1ra/` (SQLite history, settings, IDE scratch). Delete it for a factory reset.

## License

Su1ra is MIT-licensed. Bundled third-party components and their licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
