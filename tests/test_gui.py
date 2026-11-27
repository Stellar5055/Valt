"""End-to-end GUI tests: drive the real App through every flow.

Dialogs are auto-answered via monkeypatching; everything else (threading,
progress polling, the vault layer) is the real code the exe runs.

These tests create real Tk windows, so they need a display (they pass in
a normal Windows session). Skip with:  pytest -m "not gui"
"""
import os
import time

import pytest

import valt.gui as gui

pytestmark = pytest.mark.gui


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


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """Folders, passwords and one freshly created vault shared by the flow."""
    root = tmp_path_factory.mktemp("gui")
    vault = root / "flow.valt"
    folder_a = root / "alpha"
    folder_b = root / "beta"
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "a.txt").write_text("alpha contents\n", encoding="utf-8")
    (folder_b / "b.txt").write_text("beta contents\n", encoding="utf-8")
    (root / "out").mkdir()
    return {
        "vault": str(vault),
        "folder_a": str(folder_a),
        "folder_b": str(folder_b),
        "out": str(root / "out"),
        "pw_a": "password-alpha-1",
        "pw_b": "password-beta-2",
    }


class Ui:
    """One App plus the queues the fakes answer from."""

    def __init__(self, env, monkeypatch):
        self.env = env
        self.dialog_results = []      # each start_add pops one (folder, pw, label)
        self.errors = []              # showerror calls - must stay empty by default
        self.real_add_dialog = gui.AddCompartmentDialog

        class FakeAddDialog:
            def __init__(self, parent, title="Add compartment", folder="",
                         password="", label=""):
                f, p, l = self.results.pop(0)
                self.result = (f, p, l) if f else None

            def show(self):
                pass

        FakeAddDialog.results = self.dialog_results
        self.fake_add_dialog = FakeAddDialog
        monkeypatch.setattr(gui, "AddCompartmentDialog", FakeAddDialog)
        monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
        monkeypatch.setattr(gui.messagebox, "showerror",
                            lambda *a, **k: self.errors.append(a))
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        monkeypatch.setattr(gui.filedialog, "askdirectory",
                            lambda **k: self.env["out"])
        monkeypatch.setattr(gui.filedialog, "asksaveasfilename",
                            lambda **k: self.env["vault"])
        self.app = gui.App()

    def close(self):
        self.app.destroy()


@pytest.fixture(scope="module")
def ui(env):
    """One App for the whole ordered scenario (Tk apps are stateful)."""
    holder = Ui(env, _ModuleMonkeypatch())
    yield holder
    gui.AddCompartmentDialog = holder.real_add_dialog      # undo the fake
    holder.close()


class _ModuleMonkeypatch:
    """Minimal monkeypatch stand-in for module-scoped use (undo on exit)."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, old))

    def undo(self):
        for f in self._undo:
            f()
        self._undo.clear()


# ---- ordered scenario: each test is one step, later steps depend on earlier ----


def _reset_staging(ui):
    """Empty the create-tab staging area between tests."""
    ui.app.pending = []
    ui.app.rows_tree.delete(*ui.app.rows_tree.get_children())
    ui.app.rows_tree.selection_remove(*ui.app.rows_tree.selection())


def _use_fake(ui):
    gui.AddCompartmentDialog = ui.fake_add_dialog


def test_01_startup(ui):
    app = ui.app
    pump(app)
    assert not hasattr(app, "vault_var")          # no top vault-file selector
    assert app.vault_path is None
    assert str(app.btn_edit_row["state"]) == "disabled"
    assert str(app.btn_remove_row["state"]) == "disabled"
    assert ui.errors == []


def test_02_start_add_stages(ui):
    app = ui.app
    ui.dialog_results.append((ui.env["folder_a"], ui.env["pw_a"], "alpha"))
    app.start_add()
    ui.dialog_results.append((ui.env["folder_b"], ui.env["pw_b"], "beta"))
    app.start_add()
    assert [r["label"] for r in app.pending] == ["alpha", "beta"]
    assert len(app.rows_tree.get_children()) == 2


def test_03_row_selection_drives_buttons(ui):
    app = ui.app
    first = app.rows_tree.get_children()[0]
    app.rows_tree.selection_set(first)
    app.rows_tree.focus(first)
    pump(app)
    assert str(app.btn_edit_row["state"]) == "normal"
    assert str(app.btn_remove_row["state"]) == "normal"
    app.rows_tree.selection_remove(first)
    pump(app)
    assert str(app.btn_edit_row["state"]) == "disabled"


def test_04_create_vault(ui):
    app = ui.app
    app.create_vault()
    pump(app, busy_wait=True)
    assert os.path.isfile(ui.env["vault"])
    assert app.pending == [] and not app.rows_tree.get_children()
    assert app.vault_path is None                 # created vault is NOT auto-opened
    assert str(app.notebook.select()) == str(app.tab_unlock)   # no tab jump
    assert ui.errors == []


def test_05_unlock_shows_only_matching(ui):
    app = ui.app
    app.vault_path = ui.env["vault"]
    app.vault_label_var.set("flow.valt")
    app.unlock_pw_var.set(ui.env["pw_a"])
    app.unlock_vault()
    pump(app, busy_wait=True)
    assert len(app.views) == 1 and app.views[0]["name"] == "alpha"


def test_06_verify(ui):
    app = ui.app
    first = app.tree.get_children()[0]
    app.tree.selection_set(first)
    app.tree.focus(first)
    app.start_verify()
    pump(app, busy_wait=True)
    assert "verified" in app.status_var.get()


def test_07_extract(ui):
    app = ui.app
    app.start_extract()
    pump(app, busy_wait=True)
    out_file = os.path.join(ui.env["out"], "a.txt")
    assert open(out_file, encoding="utf-8").read() == "alpha contents\n"


def test_08_change_password_then_old_rejected(ui, monkeypatch):
    app = ui.app
    new_pw = "new-alpha-password-9"
    monkeypatch.setattr(gui, "ask_new_password_dialog",
                        lambda parent, context=None: new_pw)
    app.start_change_pw()
    pump(app, busy_wait=True)

    app.lock()
    app.unlock_pw_var.set(new_pw)
    app.unlock_vault()
    pump(app, busy_wait=True)
    assert len(app.views) == 1 and app.views[0]["name"] == "alpha"

    app.lock()
    app.unlock_pw_var.set(ui.env["pw_a"])          # the old one
    app.unlock_vault()
    pump(app, busy_wait=True)
    assert app.views == []
    assert "No compartment matched" in app.status_var.get()
    assert ui.errors == []                         # clean message, no error box


def test_09_remove_empties_vault(ui):
    app = ui.app
    app.unlock_pw_var.set(ui.env["pw_b"])
    app.unlock_vault()
    pump(app, busy_wait=True)
    assert [v["name"] for v in app.views] == ["beta"]
    first = app.tree.get_children()[0]
    app.tree.selection_set(first)
    app.tree.focus(first)
    app.start_remove()
    pump(app, busy_wait=True)
    assert app.views == []


def test_10_remove_selected_deletes_right_row(ui):
    app = ui.app
    for name in ("one", "two", "three"):
        ui.dialog_results.append((ui.env["folder_a"], ui.env["pw_a"], name))
        app.start_add()
    middle = app.rows_tree.get_children()[1]
    app.rows_tree.selection_set(middle)
    app.rows_tree.focus(middle)
    app.remove_selected()
    assert [r["label"] for r in app.pending] == ["one", "three"]


def test_11_real_dialog_ok_closure(ui):
    """The ok() closure must set self.result - the 'dlg' NameError regression."""
    dlg = ui.real_add_dialog(ui.app)
    dlg.folder_var.set(ui.env["folder_b"])
    dlg.label_var.set("beta-dlg")
    dlg.pw_var.set("dlg-password-1")
    dlg.conf_var.set("dlg-password-1")
    dlg.focus_force()
    ui.app.update()
    dlg.event_generate("<KeyPress-Return>")        # the user pressing Enter
    pump(ui.app)
    ui.app.update()
    assert dlg.result == (ui.env["folder_b"], "dlg-password-1", "beta-dlg")
    dlg.destroy()


def test_12_open_button_sets_vault(ui, monkeypatch):
    app = ui.app
    monkeypatch.setattr(gui.filedialog, "askopenfilename",
                        lambda **k: ui.env["vault"])
    app.browse_vault()
    assert app.vault_path == ui.env["vault"]
    assert app.vault_label_var.get() == "flow.valt"


def test_13_start_add_waits_for_dialog(ui):
    """start_add must call show() (wait_window) BEFORE reading .result -
    the 'Add click does nothing' regression."""
    app = ui.app
    shown = []

    class ShowTestDialog(ui.real_add_dialog):
        def show(self):
            shown.append(True)                     # the user "clicked Add"
            self.result = (ui.env["folder_a"], ui.env["pw_a"], "shown")
            self.destroy()

    gui.AddCompartmentDialog = ShowTestDialog          # only this test uses it
    app.start_add()
    assert shown, "start_add never showed the dialog"
    assert app.pending and app.pending[-1]["label"] == "shown", app.pending
    _use_fake(ui)                                      # hand the queue-fake back
    _reset_staging(ui)


def test_14_add_compartment_button_needs_vault(ui):
    app = ui.app
    assert str(app.btn_add_comp["state"]) == "normal"   # vault was opened in test_12
    app.vault_path = None
    app._refresh_buttons()
    assert str(app.btn_add_comp["state"]) == "disabled"
    app.vault_path = ui.env["vault"]                    # restore for the next tests
    app._refresh_buttons()


def test_15_add_compartment_to_vault(ui):
    """CLI-add in the GUI: no questions beyond the dialog, slot auto-picked."""
    app = ui.app
    app.views = []                                      # nothing unlocked
    class SlottedFake:
        def __init__(self, parent, title="Add compartment to vault", folder="",
                     password="", label=""):
            self.result = (ui.env["folder_b"], "brand-new-pw-1", "gamma")
        def show(self):
            pass
    gui.AddCompartmentDialog = SlottedFake
    app.start_add_compartment()
    _use_fake(ui)
    pump(app, busy_wait=True)
    assert ui.errors == []
    assert "Added 'gamma'" in app.status_var.get()
    assert "slot" not in app.status_var.get().lower()   # no slot talk in the UI

    app.lock()
    app.unlock_pw_var.set("brand-new-pw-1")
    app.unlock_vault()
    pump(app, busy_wait=True)
    assert [v["name"] for v in app.views] == ["gamma"]


def test_16_add_into_full_vault_fails_cleanly(ui):
    """Every slot seen occupied -> clear message, no crash, no partial write."""
    app = ui.app
    app.views = list(app.views) + [
        {"slot": s, "name": f"s{s}", "password": "x", "entries": [],
         "segment_offset": 0, "segment_len": 0, "index_len": 0, "folder_key": b""}
        for s in range(16)]                             # pretend all 16 are ours
    class SlottedFake:
        def __init__(self, parent, title="Add compartment to vault", folder="",
                     password="", label=""):
            self.result = (ui.env["folder_a"], "whatever-pw-1", "x")
        def show(self):
            pass
    gui.AddCompartmentDialog = SlottedFake
    app.start_add_compartment()
    _use_fake(ui)
    pump(app, busy_wait=True)
    assert ui.errors, "full vault must surface an error box"
    app.views = [v for v in app.views if v["name"] == "gamma"]


class _DropEvent:
    def __init__(self, data):
        self.data = data


def test_17_drop_valt_file_selects_it(ui):
    app = ui.app
    app.vault_path = None
    app._on_drop(_DropEvent("{%s}" % ui.env["vault"]))   # paths with spaces come braced
    assert app.vault_path == ui.env["vault"]
    assert app.vault_label_var.get() == "flow.valt"
    assert "enter password" in app.status_var.get()


def test_18_drop_folder_stages_compartment(ui):
    app = ui.app
    _reset_staging(ui)
    ui.dialog_results.append((ui.env["folder_b"], "dropped-pw-123", "beta"))
    app._on_drop(_DropEvent(ui.env["folder_b"]))
    assert app.pending and app.pending[-1]["label"] == "beta"
    _reset_staging(ui)


def test_19_drop_junk_only_notes_status(ui):
    app = ui.app
    app.status_var.set("ready")
    app._on_drop(_DropEvent("C:\\definitely\\not\\here.txt"))
    assert app.status_var.get() == "Drop a .valt file or a folder."
    assert app.vault_path == ui.env["vault"]              # unchanged
