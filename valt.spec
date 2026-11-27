# -*- mode: python ; coding: utf-8 -*-
# Two one-file builds from one spec:
#   dist\valt.exe       GUI + CLI (no arguments opens the GUI)
#   dist\valt-cli.exe   CLI only (smallest, no Tcl/Tk bundled)
# Build with:  build.bat   (or: pyinstaller valt.spec --clean --noconfirm)

gui_a = Analysis(
    ["launcher_gui.py"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["unittest", "pydoc_data"],
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure)

cli_a = Analysis(
    ["launcher_cli.py"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc_data"],   # the CLI exe ships without the GUI runtime
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure)

exe_full = EXE(
    gui_pyz,
    gui_a.scripts,
    gui_a.binaries,
    gui_a.datas,
    [],
    name="valt",
    debug=False,
    strip=False,
    upx=False,          # UPX-packed exes attract antivirus - keep off
    console=False,      # pure GUI app: no terminal window, ever
    icon=None,
)

exe_cli = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name="valt-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)
