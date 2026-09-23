import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

block_cipher = None
a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[(str(ROOT / "frontend" / "dist"), "frontend/dist"), (str(ROOT / "su1ra.svg"), ".")],
    hiddenimports=[
        "main",
        "store",
        "ollama",
        "runner",
        "ptyrunner",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="su1ra",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="Su1ra")
