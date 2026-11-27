@echo off
rem Build both one-file executables with PyInstaller.
rem Prefers the local .venv; falls back to pyinstaller on PATH (CI).
cd /d "%~dp0"
if exist .venv\Scripts\pyinstaller.exe (
    .venv\Scripts\pyinstaller.exe valt.spec --clean --noconfirm
) else (
    pyinstaller valt.spec --clean --noconfirm
)
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)
echo.
echo Build finished:
echo   dist\valt.exe       ^(GUI + CLI^)
echo   dist\valt-cli.exe   ^(CLI only^)
