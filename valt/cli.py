import argparse, sys, os, getpass
from valt.container import FormatError
from valt.vault import create, open_container
from valt.unpacker import extract_all
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

    create(args.path, compartments)
    size_mb = os.path.getsize(args.path) / 1024 ** 2
    print(f"Done! - {args.path}: {len(compartments)} compartment(s), {size_mb:.1f} MB")


def do_open(args):
    pw = ask_password()
    views = open_container(args.path, pw)
    
    if not views:
        print("No compartments found for this password.")
        sys.exit(1)
    for v in views:
        print(f"\n{v['name']}")
        for entry in v["entries"]:
            print(f"  {entry['name']}  ({human(entry['size'])})")


def do_extract(args):
    pw = ask_password()
    views = open_container(args.path, pw)

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
    )

    for entry in comp["entries"]:
        print(f" {entry['name']}  ({human(entry['size'])})")


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
