import argparse, sys, os, getpass, time
from valt.container import FormatError, read_header
from valt.vault import create, open_container, change_password, remove, add
from valt.unpacker import extract_all, verify_compartment
from cryptography.exceptions import InvalidTag


def ask_password(confirm=False, for_name=None):
    who = f" (for '{for_name}')" if for_name else ""

    if not sys.stdin.isatty():
        # input is redirected (script/pipe): getpass would read the console
        # directly and block - take the line from stdin instead
        pw = sys.stdin.readline().rstrip("\r\n")
        if len(pw) < 8:
            print("Password must be at least 8 characters")
            sys.exit(1)
        return pw

    while True:
        pw = getpass.getpass(f"Password{who}: ")

        if len(pw) < 8:
            print("Password must be atleast 8 characters")
            continue
        if not confirm:
            return pw
        
        pw2 = getpass.getpass(f"Confirm password{who}: ")

        if pw2 != pw:
            print("Passwords dont match, try again")
            continue
        
        return pw


def human(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def _tty():
    return sys.stdout.isatty()


def fmt_eta(seconds):
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


class Progress:
    """Percentage + ETA on a single re-used line. No bar, per the plan.

    Pass Progress.update into vault/packer/unpacker as their progress
    callback; the class throttles itself and only draws on a real terminal.
    The compartment name arrives with the first update of each phase and
    is shown next to the percentage."""

    def __init__(self, verb):
        self.verb = verb
        self.name = None
        self.start = None
        self.last_draw = 0.0
        self.drawing = False

    def update(self, done, total, name=None):
        if not _tty():
            return
        if name is not None:
            self.name = name
        now = time.monotonic()

        if done == 0:                        # a new phase begins
            if self.drawing:
                print()                      # close the previous line
            self.start = now

        if self.start is None:
            self.start = now

        if 0 < done < total and now - self.last_draw < 0.1:
            return                           # throttle mid-phase updates
        self.last_draw = now

        pct = 100 * done / total if total else 100
        who = f" '{self.name}'" if self.name else ""
        line = f"\r{self.verb}{who} {pct:.0f}%"
        if 0 < done < total:
            eta = (now - self.start) * (total / done - 1)
            line += f" · ETA {fmt_eta(eta)}"
        print(line + "   ", end="", flush=True)
        self.drawing = True

        if done >= total:
            print()                          # end the line at 100%
            self.drawing = False


def do_create(args):
    print("Forgotten passwords can never be recovered.\n")

    compartments = []

    if args.folders:
        # flag mode: folders and labels come from the command line,
        # only the passwords are asked for
        if args.label and len(args.folders) > 1:
            print("--label works with exactly one --folder.")
            sys.exit(1)
        total = len(args.folders)
        for i, folder in enumerate(args.folders, start=1):
            if not os.path.isdir(folder):
                print(f"Not a valid folder: {folder}")
                sys.exit(1)
            shown = os.path.basename(os.path.normpath(folder))
            print(f"Compartment {i} of {total}: '{shown}'")
            pw = ask_password(confirm=True, for_name=shown)
            compartments.append((folder, pw, args.label or ""))
    else:
        # interactive mode: the classic loop, one compartment at a time
        while True:
            ans = input("Add a compartment? y/n: ").strip().lower()
            if ans in ("n", "no"):
                break
            folder = input("Folder path: ").strip()
            if not os.path.isdir(folder):
                print("Not a valid folder, try again")
                continue
            label = input("Label (Optional, Enter to skip): ").strip()
            if len(label.encode("utf-8")) > 31:
                print("Label too long, try again with a shorter one.")
                continue
            pw = ask_password(confirm=True)
            compartments.append((folder, pw, label))

    if not compartments:
        print("No compartments added")
        return

    progress = Progress("packing")
    create(args.path, compartments, slots=args.slots, progress=progress.update)
    size_mb = os.path.getsize(args.path) / 1024 ** 2
    print(f"Done! - {args.path}: {len(compartments)} compartment(s), {size_mb:.1f} MB")


def do_open(args):
    pw = ask_password()
    progress = Progress("unlocking")
    views = open_container(args.path, pw, progress=progress.update)
    
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    for v in views:
        print(f"\n{v['name']}")
        for entry in v["entries"]:
            print(f"  {entry['name']}  ({human(entry['size'])})")


def do_extract(args):
    pw = ask_password()
    progress = Progress("extracting")
    views = open_container(args.path, pw, progress=progress.update)

    if not views:
        print("No compartments found for this password.")
        sys.exit(1)

    if len(views) == 1:
        comp = views[0]
    elif args.compartment:
        matches = [v for v in views if v["name"] == args.compartment]
        if not matches:
            print(f"No compartment named '{args.compartment}'.")
            sys.exit(1)
        comp = matches[0]
    else:
        for i, v in enumerate(views):
            print(f" {i + 1}. {v['name']}")
        choice = input("Pick a compartment: ").strip()
        try:
            number = int(choice)
        except ValueError:
            print("Invalid choice.")
            sys.exit(1)
        if not 1 <= number <= len(views):
            print("Invalid choice.")
            sys.exit(1)
        comp = views[number - 1]

    if not args.force:
        clashes = [
            e["name"] for e in comp["entries"]
            if os.path.exists(os.path.join(args.dest, e["name"].replace("/", os.sep)))
        ]
        if clashes:
            print("These files already exist (use --force if you want to overwrite):")
            for name in clashes:
                print(f" {name}")
            sys.exit(1)

    os.makedirs(args.dest, exist_ok=True)
    extract_all(
        args.path,
        comp["segment_offset"],
        comp["segment_len"],
        comp["folder_key"],
        comp["index_len"],
        args.dest,
        progress=progress.update,
        label=comp["name"],
    )

    for entry in comp["entries"]:
        print(f" {entry['name']}  ({human(entry['size'])})")


def pick_compartment(views):
    if len(views) == 1:
        return views[0]
    for i, v in enumerate(views):
        print(f" {i + 1}. {v['name']}")
    choice = input("Pick a compartment: ").strip()
    try:
        number = int(choice)
    except ValueError:
        print("Invalid choice.")
        sys.exit(1)
    if not 1 <= number <= len(views):
        print("Invalid choice.")
        sys.exit(1)
    return views[number - 1]


def do_change_pw(args):
    pw = ask_password()
    views = open_container(args.path, pw)
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    comp = pick_compartment(views)
    print(f"Changing the password for '{comp['name']}'.")
    new_pw = ask_password(confirm=True)
    change_password(args.path, pw, new_pw, slot=comp["slot"])
    print(f"Password changed for '{comp['name']}'.")


def do_remove(args):
    pw = ask_password()
    views = open_container(args.path, pw)
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    comp = pick_compartment(views)
    ans = input("Remove this compartment? y/n: ").strip().lower()
    if ans not in ("y", "yes"):
        print("Aborted.")
        return
    name = remove(args.path, pw, comp["slot"])
    if name is None:
        print("No compartments found for this password.")
        sys.exit(1)
    print(f"Removed '{name}'.")


def do_verify(args):
    pw = ask_password()
    progress = Progress("verifying")
    views = open_container(args.path, pw, progress=progress.update)
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    failed = False
    for v in views:
        ok, bad = verify_compartment(args.path, v["segment_offset"],
                                     v["segment_len"], v["folder_key"], v["index_len"],
                                     progress=progress.update, label=v["name"])
        if ok:
            print(f"'{v['name']}': {len(v['entries'])} files verified")
        else:
            print(f"FAILED: '{v['name']}': corrupted at '{bad}'")
            failed = True
    if failed:
        sys.exit(1)


def do_add(args):
    slot_count, data_offset = read_header(args.path)
    progress = Progress("packing")

    # New compartments go into the last slot: spares were appended after the
    # compartments at create time, so it is the likeliest free one.
    slot = slot_count - 1

    if args.folder:
        # flag mode: everything from flags, only the password is asked
        if not os.path.isdir(args.folder):
            print(f"Not a valid folder: {args.folder}")
            sys.exit(1)
        shown = os.path.basename(os.path.normpath(args.folder))
        pw = ask_password(confirm=True, for_name=shown)
        name = add(args.path, args.folder, pw, args.label, slot,
                   progress=progress.update)
    else:
        # interactive mode: folder, label and password are asked
        folder = input("Folder path: ").strip()
        if not os.path.isdir(folder):
            print(f"Not a valid folder: {folder}")
            sys.exit(1)
        label = input("Label (Optional, Enter to skip): ").strip()
        if len(label.encode("utf-8")) > 31:
            print("Label too long, try again with a shorter one.")
            sys.exit(1)
        pw = ask_password(confirm=True, for_name=os.path.basename(os.path.normpath(folder)))

        name = add(args.path, folder, pw, label, slot, progress=progress.update)

    print(f"Added '{name}'.")


def main(argv=None):
    # Windows consoles often use legacy code pages (cp1252 and friends) that
    # cannot encode the check/cross marks in status messages. Degrade to '?'
    # instead of crashing with UnicodeEncodeError mid-command.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        prog="valt",
        description="Valt - one file, many folders, each behind its own password.",
        epilog=(
            "examples:\n"
            "  valt create my.valt --folder C:\\Users\\me\\taxes --folder E:\\Movies --slots 4\n"
            "  valt open my.valt\n"
            "  valt extract my.valt OUT --compartment taxes\n"
            "  valt add my.valt --folder D:\\music --label Songs\n"
            "\n"
            "passwords are always asked for interactively - they are never typed\n"
            "into the command line, so they never land in shell history.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True, title="commands",
                                help="run 'valt COMMAND --help' for details on one")

    p = sub.add_parser("create", help="build a new vault from one or more folders",
                       description="builds a new .valt vault and locks each --folder into "
                                   "its own compartment, behind its own password (asked "
                                   "interactively - never read from the command line). "
                                   "give --folder once or more to pack without further "
                                   "questions; without them, compartments are asked for "
                                   "interactively. the vault is packed: exactly its "
                                   "contents plus a small random overhead.")
    p.add_argument("path", help="vault file to create, e.g. my.valt")
    p.add_argument("--folder", action="append", default=[], dest="folders", metavar="DIR",
                   help="folder to lock into its own compartment (repeat for more)")
    p.add_argument("--label", default="", metavar="NAME",
                   help="compartment label; default: the folder's name (max 31 bytes)")
    p.add_argument("--slots", type=int, default=None, metavar="N",
                   help="total safes in the vault, 2-16; default: compartments + 2 spares")
    p.set_defaults(func=do_create)

    p = sub.add_parser("open", help="unlock and list what a password opens")
    p.add_argument("path", help="vault file to open")
    p.set_defaults(func=do_open)

    p = sub.add_parser("extract", help="stream a compartment's files back out")
    p.add_argument("path", help="vault file")
    p.add_argument("dest", help="destination folder (created if missing)")
    p.add_argument("--compartment", metavar="NAME",
                   help="which compartment to extract; only asked when several are open")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing files in the destination")
    p.set_defaults(func=do_extract)

    p = sub.add_parser("change-pw", help="re-lock a compartment with a new password (instant)")
    p.add_argument("path", help="vault file")
    p.set_defaults(func=do_change_pw)

    p = sub.add_parser("remove", help="wipe a compartment's safe from the vault")
    p.add_argument("path", help="vault file")
    p.set_defaults(func=do_remove)

    p = sub.add_parser("verify", help="re-decrypt everything an unlocked password owns")
    p.add_argument("path", help="vault file")
    p.set_defaults(func=do_verify)

    p = sub.add_parser("add", help="append a new compartment to an existing vault",
                       description="appends a new compartment to an existing vault. "
                                   "with --folder given, no further questions beyond "
                                   "the password; without it, folder and label are "
                                   "asked interactively.")
    p.add_argument("path", help="vault file")
    p.add_argument("--folder", default=None,
                   help="folder to lock into the new compartment "
                        "(without it, folder and label are asked interactively)")
    p.add_argument("--label", default="", metavar="NAME",
                   help="compartment label; default: the folder's name (max 31 bytes)")
    p.set_defaults(func=do_add)

    args = parser.parse_args(argv)

    try:
        args.func(args)
    except FormatError:
        print("Invalid or corrupted container.")
        sys.exit(1)
    except InvalidTag:
        print("Invalid or corrupted container.")
        sys.exit(1)
    except ValueError as e:
        print(e)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Aborted.")
        sys.exit(1)

