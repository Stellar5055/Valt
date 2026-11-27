"""Valt GUI - a small ttk front end over the vault library.

Two tabs (light theme, compact): Unlock and Create. Everything heavy
runs in a worker thread; the main thread polls a queue for progress and
results. The format layer never renders anything.
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from cryptography.exceptions import InvalidTag

from valt.container import FormatError, read_header
from valt.safes import resolve_label
from valt.unpacker import extract_all, verify_compartment
from valt.vault import create, open_container, change_password, remove, add
from valt.cli import human, fmt_eta

CHUNK = 65536
NAME_LIMIT = 31


def hide_console_if_owned():
    """When the packaged exe is double-clicked it spawns its own console;
    hide that window. Launched from a real terminal, leave it alone."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        buf = (ctypes.c_uint * 1)()
        if kernel32.GetConsoleProcessList(buf, 1) == 1:
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 0)          # SW_HIDE
    except Exception:
        pass


class Track:
    """Holds the latest progress report; polled by the UI thread."""

    def __init__(self, verb):
        self.verb = verb
        self.done = 0
        self.total = 0
        self.name = None
        self.start = None

    def update(self, done, total, name=None):
        self.done, self.total = done, total
        if name is not None:
            self.name = name
        if done == 0:
            self.start = time.monotonic()           # new phase: reset the ETA clock

    def text(self):
        if not self.total:
            return self.verb
        who = f" '{self.name}'" if self.name else ""
        pct = 100 * self.done / self.total
        line = f"{self.verb}{who}: {pct:.0f}%"
        if 0 < self.done < self.total and self.start:
            eta = (time.monotonic() - self.start) * (self.total / self.done - 1)
            line += f" · ETA {fmt_eta(eta)}"
        return line


def _center(win, parent):
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


class Dialog(tk.Toplevel):
    """Small modal with OK/Cancel; the result lands in self.result."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.body = ttk.Frame(self, padding=10)
        self.body.grid()
        self.bind("<Escape>", lambda e: self.destroy())

    def show(self):
        self.grab_set()
        _center(self, self.master)
        self.wait_window()


def ask_new_password_dialog(parent, context=None):
    """Small modal: password + confirm, at least 8 characters.
    Returns the password, or None on cancel."""
    dlg = Dialog(parent, "Set compartment password")
    frm = dlg.body
    frm.columnconfigure(0, weight=1)
    text = f"Password for '{context}':" if context else "Password:"
    ttk.Label(frm, text=text).grid(row=0, column=0, sticky="w", pady=(0, 4))
    e1 = ttk.Entry(frm, show="*", width=32)
    e1.grid(row=1, column=0, sticky="ew")
    ttk.Label(frm, text="Confirm:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    e2 = ttk.Entry(frm, show="*", width=32)
    e2.grid(row=3, column=0, sticky="ew", pady=(6, 0))
    msg = tk.StringVar()
    ttk.Label(frm, textvariable=msg, foreground="#a00000").grid(row=4, column=0, sticky="w")
    e1.focus_set()

    def ok(event=None):
        pw = e1.get()
        if len(pw) < 8:
            msg.set("Use at least 8 characters.")
            return
        if pw != e2.get():
            msg.set("The two passwords do not match.")
            return
        dlg.result = pw
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=2)
    ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left", padx=2)
    dlg.bind("<Return>", ok)

    dlg.show()
    return dlg.result


class AddCompartmentDialog(Dialog):
    """The smaller add/edit window: folder, optional label, password + confirm.
    Returns (folder, password, label) or None on cancel."""

    def __init__(self, parent, title="Add compartment", folder="", password="", label=""):
        super().__init__(parent, title)
        frm = self.body
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Folder:").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=folder)
        ttk.Entry(frm, textvariable=self.folder_var, width=38).grid(
            row=1, column=0, sticky="ew")
        ttk.Button(frm, text="Browse…", command=self.browse).grid(
            row=2, column=0, sticky="e", pady=(2, 0))

        ttk.Label(frm, text="Label (optional):").grid(row=3, column=0, sticky="w",
                                                      pady=(6, 0))
        self.label_var = tk.StringVar(value=label)
        ttk.Entry(frm, textvariable=self.label_var, width=38).grid(row=4, column=0,
                                                                   sticky="ew")

        ttk.Label(frm, text="Password:").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.pw_var = tk.StringVar(value=password)
        ttk.Entry(frm, textvariable=self.pw_var, show="*", width=38).grid(
            row=6, column=0, sticky="ew")
        ttk.Label(frm, text="Confirm:").grid(row=7, column=0, sticky="w", pady=(6, 0))
        self.conf_var = tk.StringVar(value=password)
        ttk.Entry(frm, textvariable=self.conf_var, show="*", width=38).grid(
            row=8, column=0, sticky="ew", pady=(6, 0))
        msg = tk.StringVar()
        ttk.Label(frm, textvariable=msg, foreground="#a00000").grid(row=9, column=0,
                                                                    sticky="w")

        def ok(event=None):
            folder = self.folder_var.get().strip()
            pw = self.pw_var.get()
            if not folder or not os.path.isdir(folder):
                msg.set("Choose a valid folder.")
                return
            if len(pw) < 8:
                msg.set("Use at least 8 characters.")
                return
            if pw != self.conf_var.get():
                msg.set("The two passwords do not match.")
                return
            self.result = (folder, pw, self.label_var.get().strip()[:NAME_LIMIT])
            self.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Add" if title == "Add compartment" else "Save",
                   command=ok).pack(side="left", padx=2)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=2)
        self.bind("<Return>", ok)

        self.folder_var.trace_add("write", lambda *a: None)   # keep traces harmless

    def browse(self):
        picked = filedialog.askdirectory(parent=self, title="Folder to lock")
        if picked:
            self.folder_var.set(os.path.normpath(picked))

    def show(self):
        self.grab_set()
        _center(self, self.master)
        self.wait_window()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Valt")
        self.geometry("420x300")
        self.minsize(380, 260)

        self.views = []              # unlocked compartment views
        self.password = None         # in-memory only (P7)
        self.vault_path = None
        self.slot_count = None
        self.busy = False
        self.events = queue.Queue()
        self.track = Track("working")
        self._comp_by_item = {}
        self.pending = []            # create tab: staged compartments
        self._last_result = None     # worker's return value, shown by on_done

        self._build()
        self._refresh_buttons()
        self.status_var.set("Open a vault, or create a new one.")

    # ---------- layout ----------

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self.tab_unlock = ttk.Frame(self.notebook)
        self.tab_create = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_unlock, text="Unlock")
        self.notebook.add(self.tab_create, text="Create")

        self._build_unlock_tab(self.tab_unlock)
        self._build_create_tab(self.tab_create)

        self.status_var = tk.StringVar(value="Open a vault, or create a new one.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken",
                  anchor="w").pack(fill="x", padx=5, pady=(0, 5))

        self.action_buttons = [self.btn_unlock, self.btn_open_vault,
                               self.btn_create_vault, self.btn_edit_row,
                               self.btn_remove_row, *self.op_buttons.values()]

    def _build_unlock_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        row = ttk.Frame(tab)
        row.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 3))
        self.btn_open_vault = ttk.Button(row, text="Open…", command=self.browse_vault,
                                         width=7)
        self.btn_open_vault.pack(side="left")
        self.vault_label_var = tk.StringVar(value="(no vault chosen)")
        ttk.Label(row, textvariable=self.vault_label_var).pack(side="left", padx=6)

        prow = ttk.Frame(tab)
        prow.grid(row=1, column=0, sticky="ew", padx=5, pady=3)
        ttk.Label(prow, text="Password:").pack(side="left")
        self.unlock_pw_var = tk.StringVar()
        e = ttk.Entry(prow, textvariable=self.unlock_pw_var, show="*")
        e.pack(side="left", fill="x", expand=True, padx=6)
        self.btn_unlock = ttk.Button(prow, text="Unlock", command=self.unlock_vault)
        self.btn_unlock.pack(side="left")
        e.bind("<Return>", lambda event: self.unlock_vault())

        self.tree = ttk.Treeview(tab, columns=("size",), height=5, selectmode="browse")
        self.tree.heading("#0", text="Compartment / file")
        self.tree.heading("size", text="Size")
        self.tree.column("#0", stretch=True)
        self.tree.column("size", width=70, anchor="e", stretch=False)
        self.tree.grid(row=2, column=0, sticky="nsew", padx=5, pady=3)

        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, sticky="ew", padx=5, pady=3)
        self.op_buttons = {}
        for text, command in (
            ("Extract…", self.start_extract),
            ("Verify", self.start_verify),
            ("Change password…", self.start_change_pw),
            ("Remove…", self.start_remove),
        ):
            b = ttk.Button(actions, text=text, command=command, state="disabled")
            b.pack(side="left", padx=2)
            self.op_buttons[text] = b
        self.btn_lock = ttk.Button(actions, text="Lock", command=self.lock, state="disabled")
        self.btn_lock.pack(side="right", padx=2)

    def _build_create_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self.rows_tree = ttk.Treeview(tab, columns=("folder", "password"), height=4,
                                      show="tree headings", selectmode="browse")
        self.rows_tree.heading("#0", text="Compartment label")
        self.rows_tree.heading("folder", text="Folder")
        self.rows_tree.heading("password", text="Password")
        self.rows_tree.column("#0", stretch=True)
        self.rows_tree.column("folder", width=170, stretch=True)
        self.rows_tree.column("password", width=70, anchor="e", stretch=False)
        self.rows_tree.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.rows_tree.bind("<<TreeviewSelect>>",
                            lambda event: self._refresh_buttons())

        btns = ttk.Frame(tab)
        btns.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
        ttk.Button(btns, text="＋ Add", command=self.start_add).pack(side="left", padx=2)
        self.btn_edit_row = ttk.Button(btns, text="Edit", command=self.edit_selected,
                                       state="disabled")
        self.btn_edit_row.pack(side="left", padx=2)
        self.btn_remove_row = ttk.Button(btns, text="Remove", command=self.remove_selected,
                                         state="disabled")
        self.btn_remove_row.pack(side="left", padx=2)
        self.btn_create_vault = ttk.Button(btns, text="Create vault",
                                           command=self.create_vault)
        self.btn_create_vault.pack(side="right", padx=2)

    # ---------- actions ----------

    def start_add(self):
        """The ＋Add button: the smaller add window, staged until Create vault."""
        dlg = AddCompartmentDialog(self)
        dlg.show()          # modal: wait here until the user closes the window
        if dlg.result is None:
            return
        folder, pw, label = dlg.result
        self.pending.append({"folder": folder, "password": pw, "label": label})
        self.rows_tree.insert("", "end", text=label, values=(folder, "●●●●●●"))
        self._refresh_buttons()

    def edit_selected(self):
        item = self.rows_tree.focus()
        if not item:
            messagebox.showinfo("Valt", "Select a compartment row first.")
            return
        index = self.rows_tree.index(item)
        row = self.pending[index]
        dlg = AddCompartmentDialog(self, title="Edit compartment", folder=row["folder"],
                                   password=row["password"], label=row["label"])
        dlg.show()          # modal: wait here until the user closes the window
        if dlg.result is None:
            return
        folder, pw, label = dlg.result
        self.pending[index] = {"folder": folder, "password": pw, "label": label}
        self.rows_tree.item(item, text=label, values=(folder, "●●●●●●"))
        self._refresh_buttons()

    def remove_selected(self):
        item = self.rows_tree.focus()
        if not item:
            return
        index = self.rows_tree.index(item)      # index BEFORE delete
        self.rows_tree.delete(item)
        self.pending.pop(index)
        self._refresh_buttons()

    def create_vault(self):
        if not self.pending:
            messagebox.showinfo("Valt", "Add at least one compartment.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Where to save the vault",
            defaultextension=".valt", filetypes=[("Valt vault", "*.valt")])
        if not path:
            return                                  # cancelled: keep the staging
        path = os.path.normpath(path)
        compartments = [(r["folder"], r["password"], r["label"]) for r in self.pending]

        def work(update):
            create(path, compartments, progress=update)

        def done():
            self.pending = []
            self.rows_tree.delete(*self.rows_tree.get_children())
            self._refresh_buttons()
            self.status_var.set(f"Created {path} — open it from the Unlock tab.")

        self._run(work, "packing", done)

    # ---------- helpers ----------

    def browse_vault(self):
        picked = filedialog.askopenfilename(
            parent=self, title="Open vault file",
            filetypes=[("Valt vault", "*.valt"), ("All files", "*.*")])
        if picked:
            self.vault_path = os.path.normpath(picked)
            self.vault_label_var.set(os.path.basename(self.vault_path))
            self.status_var.set(f"Vault: {self.vault_path}")

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for b in self.action_buttons:
            b.configure(state=state)

    def _refresh_buttons(self):
        if self.busy:
            return
        state = "normal" if self.views else "disabled"
        for b in self.op_buttons.values():
            b.configure(state=state)
        self.btn_lock.configure(state=state)
        # create tab: Edit/Remove only make sense with a selected row
        sel = "normal" if self.rows_tree.selection() else "disabled"
        self.btn_edit_row.configure(state=sel)
        self.btn_remove_row.configure(state=sel)
        self.btn_create_vault.configure(
            state="normal" if self.pending else "disabled")

    def _run(self, work, verb, on_done):
        """Runs `work(update)` in a worker thread. `update(done, total, name)`
        feeds the Track; the queue reports completion to the UI thread."""
        if self.busy:
            return
        self.busy = True
        self.track = Track(verb)
        self.events = queue.Queue()
        self._set_busy(True)
        self.status_var.set(self.track.text())

        def worker():
            try:
                self._last_result = work(self.track.update) or None
                self.events.put(("done", None))
            except FormatError:
                self.events.put(("done", "Invalid or corrupted container."))
            except InvalidTag:
                self.events.put(("done", "Invalid or corrupted container."))
            except ValueError as e:
                self.events.put(("done", str(e)))
            except Exception as e:
                self.events.put(("done", f"Unexpected error: {e}"))

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, lambda: self._poll(on_done))

    def _poll(self, on_done):
        self.status_var.set(self.track.text())
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "done":
                    self.busy = False
                    self._set_busy(False)
                    if payload:
                        self.status_var.set(payload)
                        messagebox.showerror("Valt", payload)
                    on_done()
                    return
        except queue.Empty:
            pass
        self.after(80, lambda: self._poll(on_done))

    def _show_views(self):
        self.tree.delete(*self.tree.get_children())
        self._comp_by_item = {}
        for v in self.views:
            parent = self.tree.insert("", "end", open=True,
                                      text=f"'{v['name']}' — {len(v['entries'])} file(s)")
            self._comp_by_item[parent] = v
            for e in v["entries"]:
                child = self.tree.insert(parent, "end", text="    " + e["name"],
                                         values=(human(e["size"]),))
                self._comp_by_item[child] = v

    def _selected_comp(self):
        item = self.tree.focus()
        while item:
            comp = self._comp_by_item.get(item)
            if comp:
                return comp
            item = self.tree.parent(item)
        return None

    # ---------- actions ----------

    def unlock_vault(self):
        if not self.vault_path:
            messagebox.showinfo("Valt", "Choose a vault file first.")
            return
        pw = self.unlock_pw_var.get()
        if not pw:
            messagebox.showinfo("Valt", "Enter the password first.")
            return

        def work(update):
            self.views = open_container(self.vault_path, pw, progress=update)
            for v in self.views:
                v["password"] = pw          # in-memory only (P7): each view knows its own
            slot_count, data_offset = read_header(self.vault_path)
            self.slot_count = slot_count

        def done():
            self._show_views()
            if not self.views:
                self.status_var.set("No compartment matched this password.")
            else:
                self.status_var.set(f"Unlocked {len(self.views)} compartment(s).")

        self._run(work, "unlocking", done)

    def lock(self):
        self.views = []
        self.password = None
        self._show_views()
        self._refresh_buttons()
        self.status_var.set("Vault locked.")

    def start_extract(self):
        comp = self._selected_comp()
        if comp is None:
            messagebox.showinfo("Valt", "Unlock a compartment first, then select it.")
            return
        dest = filedialog.askdirectory(parent=self, title="Extract to folder")
        if not dest:
            return

        def work(update):
            extract_all(self.vault_path, comp["segment_offset"], comp["segment_len"],
                        comp["folder_key"], comp["index_len"], dest, progress=update)

        def done():
            self.status_var.set(f"Extracted '{comp['name']}' to '{dest}'.")

        self._run(work, "extracting", done)

    def start_verify(self):
        def work(update):
            for v in self.views:
                ok, bad = verify_compartment(self.vault_path, v["segment_offset"],
                                             v["segment_len"], v["folder_key"],
                                             v["index_len"], progress=update)
                if not ok:
                    return f"FAILED '{v['name']}': corrupted at '{bad}'"
            return "All unlocked compartments verified."

        def done():
            self.status_var.set(self._last_result or "Verify finished.")

        self._run(work, "verifying", done)

    def start_change_pw(self):
        comp = self._selected_comp()
        if comp is None:
            messagebox.showinfo("Valt", "Unlock a compartment first.")
            return
        new_pw = ask_new_password_dialog(self, context=comp["name"])
        if new_pw is None:
            return

        def work(update):
            change_password(self.vault_path, comp["password"], new_pw, slot=comp["slot"])

        def done():
            comp["password"] = new_pw
            self.status_var.set(f"Password changed for '{comp['name']}'.")

        self._run(work, "changing password", done)

    def start_remove(self):
        comp = self._selected_comp()
        if comp is None:
            messagebox.showinfo("Valt", "Unlock a compartment first.")
            return
        if not messagebox.askyesno(
                "Valt", f"Remove '{comp['name']}' from this vault?\n\n"
                        "Old copies (backups) still contain it."):
            return
        if not messagebox.askyesno(
                "Valt", f"Remove '{comp['name']}' from this vault?\n\n"
                        "Old copies (backups) still contain it."):
            return

        def work(update):
            remove(self.vault_path, comp["password"], comp["slot"])

        def done():
            self.views = [v for v in self.views if v["slot"] != comp["slot"]]
            self._show_views()
            self.status_var.set(f"Removed '{comp['name']}' from this vault.")

        self._run(work, "removing", done)


class CreateVaultDialog(Dialog):
    """W2 - returns (vault_path, compartments) or None."""

    def __init__(self, parent):
        super().__init__(parent, "Create vault and parameters")
        frm = self.body
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Vault file:").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.path_var, width=40).grid(row=0, column=1,
                                                                  sticky="ew", padx=6)
        ttk.Button(frm, text="Browse…", command=self.browse_save).grid(row=0, column=2)

        ttk.Label(frm, text="Folders to lock (one compartment each):").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.tree = ttk.Treeview(frm, columns=("folder",), height=5,
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Compartment label")
        self.tree.heading("folder", text="Folder")
        self.tree.column("folder", stretch=True)
        self.tree.grid(row=2, column=0, columnspan=3, sticky="ew")

        rowbtns = ttk.Frame(frm)
        rowbtns.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Button(rowbtns, text="Add folder…", command=self.add_folder).pack(side="left")
        ttk.Button(rowbtns, text="Remove selected",
                   command=self.remove_selected).pack(side="left", padx=6)

        self.rows = []          # dicts: {"folder", "password", "name"}

        ttk.Label(frm, text="Slot count is derived automatically "
                            "(compartments + 2 spares).").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        okc = ttk.Frame(frm)
        okc.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(okc, text="OK", command=self.ok).pack(side="left", padx=2)
        ttk.Button(okc, text="Cancel", command=self.destroy).pack(side="left", padx=2)

    def browse_save(self):
        picked = filedialog.asksaveasfilename(
            parent=self, title="New vault file", defaultextension=".valt",
            filetypes=[("Valt vault", "*.valt")])
        if picked:
            self.path_var.set(picked)

    def add_folder(self):
        picked = filedialog.askdirectory(parent=self, title="Folder to lock")
        if not picked:
            return
        picked = os.path.normpath(picked)
        label = resolve_label(picked, "")            # auto from the folder name
        pw = ask_new_password_dialog(self, context=label)
        if pw is None:
            return
        self.rows.append({"folder": picked, "password": pw, "label": label})
        self.tree.insert("", "end", text=label, values=(picked,))

    def remove_selected(self):
        item = self.tree.selection()
        if item:
            index = self.tree.index(item[0])
            self.tree.delete(item[0])
            self.rows.pop(index)

    def ok(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showinfo("Valt", "Choose a vault file first.")
            return
        if not self.rows:
            messagebox.showinfo("Valt", "Add at least one folder.")
            return
        compartments = [(r["folder"], r["password"], r["label"]) for r in self.rows]
        self.result = (path, compartments)
        self.destroy()


def run_gui():
    hide_console_if_owned()
    App().mainloop()
