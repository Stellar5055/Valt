import sys

from valt.gui import run_gui
from valt.cli import main


def run(argv=None):
    """The full build's entry point: arguments -> CLI, no arguments -> GUI.

    argv is forwarded to the CLI main so both entry points behave alike."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        main(args)
        return "cli"
    run_gui()
    return "gui"


if __name__ == "__main__":
    run()
