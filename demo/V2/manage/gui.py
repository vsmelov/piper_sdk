"""
sudo apt install -y python3-tk
"""
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
import logging
import subprocess
import sys
from pathlib import Path
import json
import numpy as np
import math
import time
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from kinematics.piper_fk import C_PiperForwardKinematics
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

        # Embedded visualiser setup -------------------------------------------------
        self._fk = C_PiperForwardKinematics()
        viz_frame = tk.Frame(root, bd=2, relief=tk.GROOVE)
        viz_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        fig = Figure(figsize=(4, 4), dpi=90)
        self._ax = fig.add_subplot(111, projection="3d")  # type: ignore[attr-defined]
        self._line, = self._ax.plot([], [], [], "-o", lw=2)

        lim = 250  # zoom in slightly
        self._ax.set_xlim(-lim, lim)
        self._ax.set_ylim(-lim, lim)
        self._ax.set_zlim(0, lim * 1.2)  # type: ignore[attr-defined]
        self._ax.set_title("Arm preview")

        canvas = FigureCanvasTkAgg(fig, master=viz_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._canvas = canvas
        self._last_draw = 0.0

        # Timeline figure (7 joint tracks) -------------------------------------------------
        timeline_frame = tk.Frame(root, bd=1, relief=tk.GROOVE)
        timeline_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self._timeline_fig = Figure(figsize=(4, 2.5), dpi=90)
        gs = self._timeline_fig.add_gridspec(7, 1)
        self._timeline_axes = [self._timeline_fig.add_subplot(gs[i, 0]) for i in range(7)]
        for ax in self._timeline_axes:
            ax.set_yticks([])
            ax.set_xticks([])
        self._timeline_canvas = FigureCanvasTkAgg(self._timeline_fig, master=timeline_frame)
        self._timeline_canvas.draw()
        self._timeline_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # placeholders for cursor lines
        self._cursor_lines = []
        self._timeline_len = 0
        self._point_counter = 0

        # External visualiser process (started on play)
        self._viz_proc: subprocess.Popen | None = None

        # === Layout ===
        self.listbox = tk.Listbox(root, selectmode=tk.EXTENDED, width=50)
        self.listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=5, fill=tk.X)

        # --- Legacy controls ---
        self.play_btn = tk.Button(btn_frame, text="Play legacy", width=12, command=self._play_selected_legacy)
        self.play_btn.pack(side=tk.LEFT, padx=4)

        self.record_btn = tk.Button(btn_frame, text="Rec legacy", width=12, command=self._record_legacy)
        self.record_btn.pack(side=tk.LEFT, padx=4)

        # --- Hybrid controls ---
        self.play_h_btn = tk.Button(btn_frame, text="Play v2", width=12, command=self._play_selected_hybrid)
        self.play_h_btn.pack(side=tk.LEFT, padx=4)

        self.record_h_btn = tk.Button(btn_frame, text="Rec v2", width=12, command=self._record_hybrid)
        self.record_h_btn.pack(side=tk.LEFT, padx=4)

        # Point duration preset buttons
        preset_frame = tk.Frame(root)
        preset_frame.pack(pady=4)
        for d in (1, 2, 5, 10):
            tk.Button(preset_frame, text=f"{d}s", width=4, command=lambda _d=d: self._add_point_preset(_d)).pack(side=tk.LEFT, padx=2)

        # custom duration
        self.custom_var = tk.StringVar()
        tk.Entry(preset_frame, width=6, textvariable=self.custom_var).pack(side=tk.LEFT, padx=2)
        tk.Button(preset_frame, text="Point", width=6, command=self._add_point_custom).pack(side=tk.LEFT, padx=2)

        # Stop buttons
        self.stop_rec_btn = tk.Button(btn_frame, text="Stop Rec", width=10, command=self._stop_record)
        self.stop_rec_btn.pack(side=tk.LEFT, padx=4)

        self.stop_play_btn = tk.Button(btn_frame, text="Stop Play", width=10, command=self._stop_play)
        self.stop_play_btn.pack(side=tk.LEFT, padx=4)

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

        # --- connect embedded visualiser ---
        self.term.set_point_hook(self._on_new_point)

        # Build timeline plots
        self._prepare_timeline(tracks)

        def worker():
            try:
                self.term.play_tracks(*tracks)
            except Exception as exc:
                logging.exception("Play failure")
                messagebox.showerror("Play error", str(exc))
            finally:
                # Playback finished – detach hook
                self.term.set_point_hook(None)

        threading.Thread(target=worker, daemon=True).start()

    def _prepare_timeline(self, tracks):
        """Load track data and draw 7 joint traces."""
        # Load combined points
        pts = []
        for t in tracks:
            path = (Path(__file__).parent / "tracks" / f"{t}.json").resolve()
            try:
                data = json.loads(path.read_text())
                pts.extend(data)
            except Exception:
                logging.warning("Failed to load track %s", t)

        if not pts:
            return

        arr = np.array(pts)  # shape (N,7)
        self._timeline_len = len(arr)
        self._point_counter = 0

        # Clear old axes
        for ax in self._timeline_axes:
            ax.cla()
        self._cursor_lines = []

        time_axis = np.arange(len(arr))
        for i, ax in enumerate(self._timeline_axes):
            y = arr[:, i]
            ax.plot(time_axis, y, color="black")
            ax.set_xlim(0, len(arr))
            ax.set_ylim(y.min() * 0.95, y.max() * 1.05)
            cursor_ln = ax.axvline(0, color="red")
            self._cursor_lines.append(cursor_ln)
            if i < 6:
                ax.set_xticks([])
        self._timeline_canvas.draw()

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

    def _stop_play(self):
        if not self.term.is_playing():
            messagebox.showinfo("Not playing", "There is no active playback.")
            return
        try:
            self.term.stop_play()
            self.term.set_point_hook(None)
        except Exception as exc:
            logging.exception("Stop play failed")
            messagebox.showerror("Error", str(exc))

    # ---------- New button callbacks ----------
    def _play_selected_legacy(self):
        tracks = [self.listbox.get(i) for i in self.listbox.curselection()]
        if not tracks:
            messagebox.showinfo("No selection", "Select tracks to play")
            return
        threading.Thread(target=lambda: self.term.play_legacy(*tracks), daemon=True).start()

    def _play_selected_hybrid(self):
        tracks = [self.listbox.get(i) for i in self.listbox.curselection()]
        if not tracks:
            messagebox.showinfo("No selection", "Select tracks to play")
            return
        threading.Thread(target=lambda: self.term.play_hybrid(*tracks), daemon=True).start()

    def _record_legacy(self):
        self._record_generic(hybrid=False)

    def _record_hybrid(self):
        self._record_generic(hybrid=True)

    def _record_generic(self, hybrid: bool):
        prompt = "Enter new hybrid track name" if hybrid else "Enter new track name"
        name = simpledialog.askstring("Record", prompt, parent=self.root)
        if not name:
            return
        try:
            if hybrid:
                self.term.start_hybrid_record(name)
            else:
                self.term.start_legacy_record(name)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    # Point buttons --------------------------------------------------
    def _add_point_preset(self, duration: float):
        try:
            self.term.add_hybrid_point(float(duration))
        except Exception as exc:
            logging.warning("Add point failed: %s", exc)

    def _add_point_custom(self):
        try:
            dur = float(self.custom_var.get())
        except ValueError:
            messagebox.showwarning("Bad value", "Enter numeric duration")
            return
        self._add_point_preset(dur)

    # ---------------------------- visualiser ----------------------------
    def _on_new_point(self, pt):
        """Called from PiperTerminal for every sent point."""
        self._point_counter += 1
        # Visualise every 10th point (and always last if known)
        if self._point_counter % 10 != 0 and self._point_counter != self._timeline_len:
            return

        now = time.time()
        if now - self._last_draw < 0.05 and self._point_counter != self._timeline_len:
            return
        self._last_draw = now

        joints_rad = [math.radians(pt[i] / 1000) for i in range(6)]
        positions = self._fk.CalFK(joints_rad)

        xs, ys, zs = [0], [0], [0]
        for pos in positions:
            xs.append(pos[0])
            ys.append(pos[1])
            zs.append(pos[2])

        # --- draw gripper jaws ---
        end_x, end_y, end_z = xs[-1], ys[-1], zs[-1]
        grip_deg = pt[6] / 1000.0
        half_rad = math.radians(grip_deg) / 2.0
        L = 60  # mm length of jaw visual
        jaw1 = (end_x + L * math.cos(half_rad), end_y + L * math.sin(half_rad), end_z)
        jaw2 = (end_x + L * math.cos(-half_rad), end_y + L * math.sin(-half_rad), end_z)

        # Update line data (stick + jaws)
        xs2 = xs + [jaw1[0], end_x, jaw2[0]]
        ys2 = ys + [jaw1[1], end_y, jaw2[1]]
        zs2 = zs + [jaw1[2], end_z, jaw2[2]]

        self._line.set_data(xs2, ys2)
        self._line.set_3d_properties(zs2)  # type: ignore[attr-defined]

        # --- update timeline cursor ---
        if self._cursor_lines:
            for ln in self._cursor_lines:
                ln.set_xdata([self._point_counter, self._point_counter])
        self._canvas.draw_idle()
        self._timeline_canvas.draw_idle()

    # ---------------------------- helpers ----------------------------
    def _terminate_visualiser(self):
        """Terminate external visualiser process if running."""
        if self._viz_proc and self._viz_proc.poll() is None:
            try:
                self._viz_proc.terminate()
            except Exception:
                pass
        self._viz_proc = None

    def _on_close(self):
        """Cleanup and exit."""
        self._terminate_visualiser()
        try:
            self.term.shutdown()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    gui = PiperGUI(root)
    root.mainloop() 