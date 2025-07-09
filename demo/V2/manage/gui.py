import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
import logging
from demo.V2.manage.terminal_v2 import PiperTerminal


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s")


class PiperGUI:
    """Simple cross-platform GUI for recording and playing Piper tracks."""

    REFRESH_MS = 2000  # list refresh interval

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Piper Track Manager")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.term = PiperTerminal()

        # === Layout ===
        self.listbox = tk.Listbox(root, selectmode=tk.EXTENDED, width=50)
        self.listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=5)

        self.play_btn = tk.Button(btn_frame, text="Play", width=10, command=self._play_selected)
        self.play_btn.pack(side=tk.LEFT, padx=5)

        self.record_btn = tk.Button(btn_frame, text="Record…", width=10, command=self._record_new)
        self.record_btn.pack(side=tk.LEFT, padx=5)

        self.stop_rec_btn = tk.Button(btn_frame, text="Stop Rec", width=10, command=self._stop_record)
        self.stop_rec_btn.pack(side=tk.LEFT, padx=5)

        # Initial population + auto-refresh
        self._refresh_tracks()

    # ---------------------------- Callbacks ----------------------------
    def _refresh_tracks(self):
        tracks = self.term.list_tracks()
        current_selection = [self.listbox.get(i) for i in self.listbox.curselection()]

        self.listbox.delete(0, tk.END)
        for t in tracks:
            self.listbox.insert(tk.END, t)

        # Restore previous selection (if items still present)
        for idx, t in enumerate(tracks):
            if t in current_selection:
                self.listbox.selection_set(idx)

        self.root.after(self.REFRESH_MS, self._refresh_tracks)

    def _play_selected(self):
        tracks = [self.listbox.get(i) for i in self.listbox.curselection()]
        if not tracks:
            messagebox.showinfo("No selection", "Please select one or more tracks to play.")
            return

        def worker():
            try:
                self.term.play_tracks(*tracks)
            except Exception as exc:
                logging.exception("Play failure")
                messagebox.showerror("Play error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _record_new(self):
        if self.term.is_recording():
            messagebox.showinfo("Recording", "Already recording. Stop current session first.")
            return

        name = simpledialog.askstring("Record track", "Enter new track name (e.g. left__my_move):", parent=self.root)
        if not name:
            return
        try:
            self.term.start_record(name)
        except Exception as exc:
            logging.exception("Record start failed")
            messagebox.showerror("Error", str(exc))

    def _stop_record(self):
        if not self.term.is_recording():
            messagebox.showinfo("Not recording", "There is no active recording session.")
            return
        try:
            self.term.stop_record()
        except Exception as exc:
            logging.exception("Stop record failed")
            messagebox.showerror("Error", str(exc))

    def _on_close(self):
        """Cleanup and exit."""
        try:
            self.term.shutdown()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    gui = PiperGUI(root)
    root.mainloop() 