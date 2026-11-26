import argparse, sys, os, getpass, time
from valt.container import FormatError, read_header
from valt.vault import create, open_container, change_password, remove, add
from valt.unpacker import extract_all, verify_compartment
from cryptography.exceptions import InvalidTag


def ask_password(confirm=False):
    while True:
        pw = getpass.getpass("Password: ")

        if len(pw) < 8:
            print("Password must be atleast 8 characters")
            continue
        if not confirm:
            return pw
        
        pw2 = getpass.getpass("Confirm password: ")

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
    print("Pick a strong password.")
    print("Forgotten passwords can never be recovered.\n")

    compartments = []
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
    create(args.path, compartments, progress=progress.update)
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
    print(f"✔ Password changed for '{comp['name']}'.")


def do_remove(args):
    pw = ask_password()
    views = open_container(args.path, pw)
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    comp = pick_compartment(views)
    print("Removed from THIS file. Old copies (backups) still contain it.")
    ans = input("Remove this compartment? y/n: ").strip().lower()
    if ans not in ("y", "yes"):
        print("Aborted.")
        return
    name = remove(args.path, pw, comp["slot"])
    if name is None:
        print("No compartments found for this password.")
        sys.exit(1)
    print(f"✔ Removed '{name}'.")


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
            print(f"✔ '{v['name']}': {len(v['entries'])} files verified")
        else:
            print(f"✘ '{v['name']}': corrupted at '{bad}'")
            failed = True
    if failed:
        sys.exit(1)


def do_add(args):
    slot_count, data_offset = read_header(args.path)
    print("You cannot see which slots are secretly occupied. If the slot you")
    print("pick holds a compartment whose password you have forgotten, writing")
    print("here will destroy it.")

    pw_existing = getpass.getpass("Your existing password (Enter to skip): ")
    if pw_existing:
        views = open_container(args.path, pw_existing)
        for v in views:
            print(f" yours: slot {v['slot']} ('{v['name']}')")

    folder = input("Folder path: ").strip()
    if not os.path.isdir(folder):
        print("Not a valid folder, try again")
        sys.exit(1)
    label = input("Label (Optional, Enter to skip): ").strip()
    if len(label.encode("utf-8")) > 31:
        print("Label too long, try again with a shorter one.")
        sys.exit(1)
    pw = ask_password(confirm=True)
    progress = Progress("packing")

    slot = input(f"Slot number to use (0 - {slot_count - 1}): ").strip()
    try:
        slot = int(slot)
    except ValueError:
        print("Invalid choice.")
        sys.exit(1)
    if not 0 <= slot < slot_count:
        print("Invalid choice.")
        sys.exit(1)

    name = add(args.path, folder, pw, label, slot, progress=progress.update)
    print(f"✔ Added '{name}' in slot {slot}.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="valt")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    p = sub.add_parser("create")
    p.add_argument("path")
    p.set_defaults(func=do_create)

    p = sub.add_parser("open")
    p.add_argument("path")
    p.set_defaults(func=do_open)

    p = sub.add_parser("extract")
    p.add_argument("path")
    p.add_argument("dest")
    p.add_argument("--compartment")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=do_extract)

    p = sub.add_parser("change-pw")
    p.add_argument("path")
    p.set_defaults(func=do_change_pw)

    p = sub.add_parser("remove")
    p.add_argument("path")
    p.set_defaults(func=do_remove)

    p = sub.add_parser("verify")
    p.add_argument("path")
    p.set_defaults(func=do_verify)

    p = sub.add_parser("add")
    p.add_argument("path")
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
