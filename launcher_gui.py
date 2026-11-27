import os
import sys

from valt.gui import run_gui
from valt.cli import main


def run(argv=None):
    """The full build's entry point.

    One existing .valt file -> GUI with that vault selected (double-click
    in Explorer). Any other arguments -> CLI. No arguments -> GUI."""
    args = sys.argv[1:] if argv is None else argv
    if (len(args) == 1 and args[0].lower().endswith(".valt")
            and os.path.isfile(args[0])):
        run_gui(initial_vault=args[0])
        return "gui-file"
    if args:
        main(args)
        return "cli"
    run_gui()
    return "gui"


if __name__ == "__main__":
    run()
