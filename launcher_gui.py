import os
import sys

from valt.gui import run_gui


def run(argv=None):
    """The GUI build's entry point. valt.exe is windowed (no console), so it
    never forwards to the CLI - that is valt-cli.exe's job.

    An argument pointing at an existing .valt file (double-click in Explorer)
    selects that vault for unlocking; anything else is ignored."""
    args = sys.argv[1:] if argv is None else argv
    vault = next((a for a in args
                  if a.lower().endswith(".valt") and os.path.isfile(a)), None)
    run_gui(initial_vault=vault)
    return "gui"


if __name__ == "__main__":
    run()
