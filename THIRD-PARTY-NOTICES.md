# Third-party components distributed with Su1ra

Su1ra bundles the following open-source components, redistributed in binary
form. All are under permissive licenses that require this notice be preserved.

## Ollama (server binary, bundled by the Windows installer)

MIT License — Copyright (c) Ollama contributors
https://github.com/ollama/ollama

The Ollama server is downloaded during installation from the official Ollama
releases and is not modified. Ollama is a trademark of its respective owners;
Su1ra is an independent client and is not affiliated with or endorsed by the
Ollama project.

## Python backend

- FastAPI — MIT — https://github.com/fastapi/fastapi
- Uvicorn — BSD-3-Clause — https://github.com/klaviyo/uvicorn (upstream: https://github.com/encode/uvicorn)
- httpx — BSD-3-Clause — https://github.com/encode/httpx
- pywebview — BSD-3-Clause — https://github.com/r0x0r/pywebview
- PyInstaller — GPL with bootloader redistribution exception; applications
  packaged with PyInstaller are not subject to the GPL
  (https://pyinstaller.org/en/stable/license.html)

## Frontend

- React — MIT — https://react.dev
- Vite — MIT — https://vite.dev
- react-markdown, remark-gfm, remark-math, rehype-katex — MIT — https://github.com/remarkjs
- KaTeX (incl. bundled fonts) — MIT — https://katex.org
- @xterm/xterm, @xterm/addon-fit — MIT — https://github.com/xtermjs/xterm.js
- Tabler / self-hosted assets — see individual upstream licenses

## Models

Language models are not distributed with Su1ra. They are pulled by the user
from the Ollama registry at runtime and remain subject to their own licenses
(for example, qwen2.5-coder under the Apache 2.0 license, deepseek-r1 under
its MIT model license).
