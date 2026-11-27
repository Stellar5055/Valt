"""End-to-end GUI smoke test: drives the real App through every flow.

Dialogs are auto-answered by monkeypatching; everything else (threading,
progress polling, vault layer) is the real code the exe will run.
Run:  .venv\\Scripts\\python.exe smoke_gui.py
"""

import os
import shutil
import sys
import tempfile
import time

import valt.gui as gui

PASS = []


def ok(label):
    PASS.append(label)
    print(f"  PASS  {label}")


def pump(app, busy_wait=False, timeout=60.0):
    """Pump the Tk event loop; if busy_wait, until the worker finishes."""
    start = time.monotonic()
    while True:
        app.update()
        if not busy_wait or not app.busy:
            return
        if time.monotonic() - start > timeout:
            raise RuntimeError("worker timed out")
        time.sleep(0.01)


def main():
    tmp = tempfile.mkdtemp(prefix="valt_smoke_")
    vault_path = os.path.join(tmp, "smoke.valt")
    folder_a = os.path.join(tmp, "alpha")
    folder_b = os.path.join(tmp, "beta")
    for d in (folder_a, folder_b):
        os.makedirs(d)
    with open(os.path.join(folder_a, "a.txt"), "w", encoding="utf-8") as f:
        f.write("alpha contents\n")
    with open(os.path.join(folder_b, "b.txt"), "w", encoding="utf-8") as f:
        f.write("beta contents\n")

    pw_a, pw_b = "password-alpha-1", "password-beta-2"

    # Auto-answer dialogs BEFORE building the app.
    dialog_results = []
    RealAddDialog = gui.AddCompartmentDialog

    class FakeAddDialog:
        def __init__(self, parent, title="Add compartment", folder="", password="", label=""):
            folder, pw, lab = dialog_results.pop(0)
            self.result = (folder, pw, lab) if folder else None

        def show(self):
            pass

    gui.AddCompartmentDialog = FakeAddDialog
    gui.messagebox.showinfo = lambda *a, **k: None
    gui.messagebox.showerror = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError(f"showerror: {a}"))
    gui.messagebox.askyesno = lambda *a, **k: True
    gui.filedialog.askdirectory = lambda **k: os.path.join(tmp, "out")
    gui.filedialog.asksaveasfilename = lambda **k: vault_path

    app = gui.App()
    try:
        pump(app)
        ok("app builds, no startup crash")

        # ---- no vault-file selector at the top: vault starts unknown ----
        assert not hasattr(app, "vault_var")
        assert app.vault_path is None
        assert str(app.btn_edit_row["state"]) == "disabled"
        assert str(app.btn_remove_row["state"]) == "disabled"
        ok("no top selector; Edit/Remove start disabled")

        # ---- Create tab: stage two compartments via the real button path ----
        dialog_results.append((folder_a, pw_a, "alpha"))
        app.start_add()
        dialog_results.append((folder_b, pw_b, "beta"))
        app.start_add()
        assert len(app.pending) == 2, app.pending
        assert len(app.rows_tree.get_children()) == 2
        ok("start_add stages two compartments")

        # ---- selecting a row enables Edit/Remove, deselect disables ----
        first = app.rows_tree.get_children()[0]
        app.rows_tree.selection_set(first)
        app.rows_tree.focus(first)
        pump(app)
        assert str(app.btn_edit_row["state"]) == "normal"
        assert str(app.btn_remove_row["state"]) == "normal"
        app.rows_tree.selection_remove(first)
        pump(app)
        assert str(app.btn_edit_row["state"]) == "disabled"
        ok("row selection drives Edit/Remove state")

        # ---- Create vault: location comes from the save-as popup ----
        app.create_vault()
        pump(app, busy_wait=True)
        assert os.path.isfile(vault_path)
        assert app.pending == [] and not app.rows_tree.get_children()
        assert app.vault_path is None            # created vault is NOT auto-opened
        assert str(app.notebook.select()) == str(app.tab_unlock)   # no tab jump
        ok("create_vault packs, clears staging, stays put")

        # ---- Unlock with alpha's password: pick the vault explicitly ----
        app.vault_path = vault_path
        app.vault_label_var.set("smoke.valt")
        app.unlock_pw_var.set(pw_a)
        app.unlock_vault()
        pump(app, busy_wait=True)
        assert len(app.views) == 1 and app.views[0]["name"] == "alpha", app.views
        ok("unlock shows only the matching compartment")

        # ---- Verify ----
        app.tree.selection_set(app.tree.get_children()[0])
        app.tree.focus(app.tree.get_children()[0])
        app.start_verify()
        pump(app, busy_wait=True)
        assert "verified" in app.status_var.get(), app.status_var.get()
        ok(f"verify: {app.status_var.get()}")

        # ---- Extract ----
        out = os.path.join(tmp, "out")
        app.start_extract()
        pump(app, busy_wait=True)
        with open(os.path.join(out, "a.txt"), encoding="utf-8") as f:
            assert f.read() == "alpha contents\n"
        ok("extract writes the original file back")

        # ---- Change password (alpha) ----
        new_pw = "new-alpha-password-9"
        gui.ask_new_password_dialog = lambda parent, context=None: new_pw
        app.start_change_pw()
        pump(app, busy_wait=True)
        ok("change_password completes")

        # Lock, re-unlock with the NEW password
        app.lock()
        app.unlock_pw_var.set(new_pw)
        app.unlock_vault()
        pump(app, busy_wait=True)
        assert len(app.views) == 1 and app.views[0]["name"] == "alpha"
        ok("new password unlocks, old one is gone")

        # Old password must now fail cleanly: no compartments, clear message
        errors = []
        gui.messagebox.showerror = lambda *a, **k: errors.append(a)
        app.lock()
        app.unlock_pw_var.set(pw_a)
        app.unlock_vault()
        pump(app, busy_wait=True)
        assert app.views == []
        assert "No compartment matched" in app.status_var.get(), app.status_var.get()
        assert not errors, f"unexpected error box: {errors}"
        ok("old password rejected with a clear message, no crash")

        # ---- Unlock with beta's password, then remove beta ----
        app.unlock_pw_var.set(pw_b)
        app.unlock_vault()
        pump(app, busy_wait=True)
        assert len(app.views) == 1 and app.views[0]["name"] == "beta"
        app.tree.selection_set(app.tree.get_children()[0])
        app.tree.focus(app.tree.get_children()[0])
        app.start_remove()
        pump(app, busy_wait=True)
        assert app.views == []
        ok("remove empties the vault")

        # ---- remove_selected index bug: stage 3, delete middle ----
        for name in ("one", "two", "three"):
            dialog_results.append((folder_a, pw_a, name))
            app.start_add()
        assert [r["label"] for r in app.pending] == ["one", "two", "three"]
        app.rows_tree.selection_set(app.rows_tree.get_children()[1])
        app.rows_tree.focus(app.rows_tree.get_children()[1])
        app.remove_selected()
        assert [r["label"] for r in app.pending] == ["one", "three"], app.pending
        ok("remove_selected deletes the right row")

        # ---- Real AddCompartmentDialog ok-closure (was the dlg NameError) ----
        real = RealAddDialog(app)
        real.folder_var.set(folder_b)
        real.label_var.set("beta-dlg")
        real.pw_var.set("dlg-password-1")
        real.conf_var.set("dlg-password-1")
        real.focus_force()                          # the dialog must have focus
        app.update()
        real.event_generate("<KeyPress-Return>")    # invokes the ok() closure
        pump(app)
        app.update()
        assert real.result == (folder_b, "dlg-password-1", "beta-dlg"), real.result
        real.destroy()
        ok("AddCompartmentDialog OK sets result (no NameError)")

        # ---- Unlock tab Open… button routes through vault_path ----
        gui.filedialog.askopenfilename = lambda **k: vault_path
        app.browse_vault()
        assert app.vault_path == vault_path
        assert app.vault_label_var.get() == "smoke.valt"
        ok("Open… sets the vault and shows its name")

        # ---- start_add must WAIT for the dialog (show/wait_window) before
        # reading .result - the "Add click does nothing" regression ----
        shown = []

        class ShowTestDialog(RealAddDialog):
            def show(self):
                shown.append(True)                       # user "clicked Add"
                self.result = (folder_a, pw_a, "shown")
                self.destroy()

        gui.AddCompartmentDialog = ShowTestDialog
        app.start_add()
        gui.AddCompartmentDialog = FakeAddDialog
        assert shown, "start_add never showed the dialog"
        assert app.pending and app.pending[-1]["label"] == "shown", app.pending
        app.remove_selected()                            # clean up the staged row
        ok("start_add waits for the dialog and stages the result")

        print(f"\nAll {len(PASS)} GUI smoke checks passed.")
    finally:
        app.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    sys.exit(0)

