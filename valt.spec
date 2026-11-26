# -*- mode: python ; coding: utf-8 -*-
# One-file build for Valt. Build with:  build.bat   (or: pyinstaller valt.spec --clean --noconfirm)

a = Analysis(
    ["launcher.py"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="valt",
    debug=False,
    strip=False,
    upx=False,          # UPX-packed exes attract antivirus - keep off
    console=True,       # the CLI lives in the console
    icon=None,
)
