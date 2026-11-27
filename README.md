# Valt

One vault file. Many folders. Each folder behind its own password.

Valt packs folders into a single `.valt` file where every folder gets its
own password — opening it with one password shows only that folder, and
there is no way to prove any others exist. The file is packed to exactly
its contents, so it also fits your backups.

Written in Python (Tkinter GUI + CLI), packaged as two Windows executables.

## Install

**PowerShell — one line** (installs to `%LOCALAPPDATA%\Valt`, no other
tools needed; re-running the same line updates):

```powershell
irm https://raw.githubusercontent.com/Stellar5055/Valt/main/install.ps1 | iex
```

**Scoop:**

```powershell
scoop install https://raw.githubusercontent.com/Stellar5055/Valt/main/bucket/valt.json
```

Updates with `scoop update valt`.

**Manual:** download `valt.exe` (GUI) or `valt-cli.exe` (command line) from
the [latest release](https://github.com/Stellar5055/Valt/releases/latest).

Forgotten passwords can never be recovered.

## Usage

Double-click `valt.exe`, or press the Windows key and type *Valt*.

- **Create** — pick folders, set a password for each, choose where the
  vault file goes
- **Unlock** — choose a vault, enter a password; you only see what that
  password opens
- Extract, verify, change password, remove, add — per compartment

Command line (`valt-cli.exe`):

```
valt-cli create my.valt --folder C:\Users\me\taxes --folder E:\Movies
valt-cli open my.valt
valt-cli extract my.valt OUT --compartment taxes
```

Passwords are asked for interactively — they never land in shell history.
Double-clicking any `.valt` file opens Valt with that vault selected.

## Format

One `.valt` file, no slack space: the file size is exactly its contents
plus 0–8 KiB of random overhead. Compartment count and slot layout are
always visible; which slots hold a compartment is indistinguishable from
random junk by design. See [SPEC.md](SPEC.md).

## Build from source

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
build.bat
```

Produces `dist\valt.exe` and `dist\valt-cli.exe`.
