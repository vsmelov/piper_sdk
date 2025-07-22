from __future__ import annotations

"""High-level terminal that delegates управление каждой роборукой отдельному
процессу с `PiperTerminal`. Сохраняет почти все команды старого REPL.
"""

import logging
import threading
import time
from pathlib import Path
from typing import List, Optional, Any, cast, Dict, Tuple

from demo.V2.manage.arm_ipc import ArmProxy
from demo.V2.settings import CAN_LEFT, CAN_RIGHT

# для автоподстановки файлов
from demo.V2.manage.terminal_v2 import (
    _track_path,  # noqa: F401 – re-export для совместимости
    TRACK_DIR,
    PiperTerminal as _InnerTerminal,  # типы для подсказок
)


class PiperTerminalV3:
    """Orchestrator REPL: управляет двумя ArmProxy (LEFT/RIGHT).

    Команды совпадают с PiperTerminal v2, но внутренняя работа выполняется в
    отдельных процессах, поэтому GIL не блокирует вторую руку.
    """

    def __init__(self) -> None:
        self.left: Optional[ArmProxy] = None
        self.right: Optional[ArmProxy] = None
        # Default duration for hybrid (r2) recording when user presses Enter
        self._default_duration: float = 2.0
        # store last 10 entered commands for quick repeat ("_", "__", ...)
        self._cmd_history: list[str] = []
        if CAN_LEFT is not None:
            self.left = ArmProxy(CAN_LEFT, side="left")
            logging.info("Left arm proxy ready (%s)", CAN_LEFT)
        if CAN_RIGHT is not None:
            self.right = ArmProxy(CAN_RIGHT, side="right")
            logging.info("Right arm proxy ready (%s)", CAN_RIGHT)

    # --------------------- util helpers ---------------------
    def _proxy_for_track(self, name: str) -> ArmProxy:
        name = self._canon_name(name)
        if name.startswith("left__"):
            if not self.left:
                raise RuntimeError("Left arm not initialised")
            return self.left
        if name.startswith("right__"):
            if not self.right:
                raise RuntimeError("Right arm not initialised")
            return self.right
        raise ValueError("track name must start with left__ or right__")

    def _call_both(self, method: str, *args, **kwargs):
        """Invoke *method* on both proxies if they exist (fire-and-forget)."""
        for proxy in (self.left, self.right):
            if proxy is None:
                continue
            try:
                getattr(proxy, method)(*args, **kwargs)
            except Exception:
                # Логируем, но продолжаем – команды могут быть специфичны для руки
                logging.debug("proxy error", exc_info=True)

    # --------------------- commands (delegation) ---------------------
    def cmd_record(self, *args):
        if not args:
            logging.info("record: требуется имя трека")
            return
        full = self._canon_name(args[0])
        proxy = self._proxy_for_track(full)
        proxy.cmd_record(full)

    # alias
    cmd_r = cmd_record  # type: ignore[assignment]

    def cmd_record_v2(self, *args):
        """Start hybrid (v2) recording on correct arm with overwrite handled here."""
        if not args:
            logging.info("record_v2: требуется имя трека")
            return

        full_name: str
        if len(args) == 1:
            full_name = args[0]
        elif len(args) == 2:
            parent, child = args
            if "__" in child:
                logging.info("В child_name запрещено '__'.")
                return
            full_name = f"{parent}__{child}"
        else:
            logging.info("record_v2: требуется 1 или 2 аргумента.")
            return

        # Resolve file paths
        trk_path = _track_path(full_name)
        details_path = trk_path.with_suffix(".details.json")

        if trk_path.exists():
            try:
                ans = input(f"Файл {trk_path.name} уже существует. Перезаписать? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                logging.info("Отмена.")
                return
            if ans != "y":
                logging.info("Отмена.")
                return
            # Remove old files so что _confirm_overwrite в дочернем процессе не спросит снова
            try:
                trk_path.unlink()
            except Exception:
                pass
            if details_path.exists():
                try:
                    details_path.unlink()
                except Exception:
                    pass

        proxy = self._proxy_for_track(full_name)
        proxy.cmd_record_v2(full_name)

    # alias
    cmd_r2 = cmd_record_v2  # type: ignore[assignment]

    def cmd_s(self, *args):
        """Dual-purpose alias:

        • s           – stop recording (как раньше)
        • s <args...> – alias for set <args...>
        """
        if args:
            self.cmd_set(*args)
        else:
            self._call_both("cmd_s")

    # ----------------------- play -----------------------
    def cmd_play(self, *tracks: str):
        if not tracks:
            logging.info("play: требуется >=1 трек")
            return
        # Группируем треки по рукам
        tracks = tuple(self._canon_name(t) for t in tracks)
        left_tracks: List[str] = []
        right_tracks: List[str] = []
        for t in tracks:
            if t.startswith("left__"):
                left_tracks.append(t)
            elif t.startswith("right__"):
                right_tracks.append(t)
            else:
                logging.error("Неверное имя трека %s", t)
                return
        threads = []
        if left_tracks and self.left:
            threads.append(threading.Thread(target=self.left.cmd_play, args=left_tracks, daemon=True))
        if right_tracks and self.right:
            threads.append(threading.Thread(target=self.right.cmd_play, args=right_tracks, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # alias
    cmd_p = cmd_play  # type: ignore[assignment]

    def cmd_play_parallel(self, left_track: str = "", right_track: str = ""):
        if not left_track or not right_track:
            logging.info("pp: нужно 2 трека – левый и правый")
            return
        left_track = self._canon_name(left_track)
        right_track = self._canon_name(right_track)
        if not (left_track.startswith("left__") and right_track.startswith("right__")):
            logging.error("pp: треки должны начинаться с left__/right__")
            return
        th_left = threading.Thread(target=self.left.cmd_play, args=(left_track,), daemon=True) if self.left else None
        th_right = threading.Thread(target=self.right.cmd_play, args=(right_track,), daemon=True) if self.right else None
        if th_left:
            th_left.start()
        if th_right:
            th_right.start()
        if th_left:
            th_left.join()
        if th_right:
            th_right.join()

    # alias
    cmd_pp = cmd_play_parallel  # type: ignore[assignment]

    def cmd_play_v2(self, *tracks: str):
        # Аналогично cmd_play, но вызываем cmd_play_v2 на прокси
        if not tracks:
            logging.info("play_v2: требуется >=1 трек")
            return
        tracks = tuple(self._canon_name(t) for t in tracks)
        left_tracks: List[str] = []
        right_tracks: List[str] = []
        for t in tracks:
            if t.startswith("left__"):
                left_tracks.append(t)
            elif t.startswith("right__"):
                right_tracks.append(t)
            else:
                logging.error("Неверное имя трека %s", t)
                return
        th: List[threading.Thread] = []
        if left_tracks and self.left:
            th.append(threading.Thread(target=self.left.cmd_play_v2, args=left_tracks, daemon=True))
        if right_tracks and self.right:
            th.append(threading.Thread(target=self.right.cmd_play_v2, args=right_tracks, daemon=True))
        for t in th:
            t.start()
        for t in th:
            t.join()

    # alias
    cmd_p2 = cmd_play_v2  # type: ignore[assignment]

    # ----------------------- zero helpers routed to left arm -----------------------
    def cmd_r_0_pos(self):
        if self.left:
            self.left.cmd_r_0_pos()

    def cmd_r_0_track(self, *args):
        if self.left:
            self.left.cmd_r_0_track(*args)

    def cmd_check_0_pos(self):
        if self.left:
            self.left.cmd_check_0_pos()

    def cmd_check_0_track(self):
        if self.left:
            self.left.cmd_check_0_track()

    # --------------------------- reset commands ---------------------------
    def cmd_reset(self, target: str = "all"):
        self._cmd_reset_once(target)
        self._cmd_reset_once(target)

    def _cmd_reset_once(self, target: str = "all"):
        """Reset arms.

        Usage:
            reset all   – обе руки
            reset left  – только левая
            reset right – только правая
        По умолчанию сбрасываются обе руки.
        """
        target = self._norm_side(target) or target.lower()
        if target in {"all", "both"}:
            self._call_both("cmd_reset")
            return
        if target == "left":
            if self.left:
                self.left.cmd_reset()
            else:
                logging.warning("Left arm not initialised.")
            return
        if target == "right":
            if self.right:
                self.right.cmd_reset()
            else:
                logging.warning("Right arm not initialised.")
            return
        logging.error("reset: аргумент должен быть all/left/right")

    # --------------------------- Scene helpers ---------------------------
    def _track_duration(self, name: str) -> float | None:
        """Return approximate duration of a track in seconds if known."""
        try:
            from demo.V2.manage.track import TrackBase, TrackV3Timed  # local import to avoid cycles
            obj = TrackBase.read_track(name)
        except Exception:
            return None
        if hasattr(obj, "durations"):
            # TrackV3Timed
            return sum(getattr(obj, "durations", []))
        if getattr(obj, "track_points", None):
            first = obj.track_points[0]
            last = obj.track_points[-1]
            return max(0.0, last.coordinates_timestamp - first.coordinates_timestamp)
        return None

    # --------------------------- Scene commands ---------------------------
    def cmd_scene_add(self, scene_name: str):
        from demo.V2.manage.scene import Scene, SceneElement  # local import
        scene_name = self._canon_name(scene_name)
        if not scene_name.startswith("scene__"):
            logging.error("Scene name must start with 'scene__'")
            return

        logging.info("[SCENE ADD] building LEFT arm timeline – type 'done' to finish")

        def _collect(arm_name: str):
            out: list[SceneElement] = []
            while True:
                line = input(f"{arm_name}> ").strip()
                if line == "done":
                    break
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "track" and len(parts) == 2:
                    out.append(SceneElement(type="track", name=parts[1]))
                elif parts[0] == "pause" and len(parts) == 2:
                    try:
                        dur = float(parts[1])
                        out.append(SceneElement(type="pause", duration=dur))
                    except ValueError:
                        logging.warning("bad duration")
                else:
                    logging.warning("unknown input; use 'track <name>' or 'pause <sec>' or 'done'")
            return out

        left_seq = _collect("LEFT")
        logging.info("[SCENE ADD] building RIGHT arm timeline – type 'done' to finish")
        right_seq = _collect("RIGHT")

        Scene(name=scene_name, left=left_seq, right=right_seq).save()
        logging.info("Scene saved → %s", Path(f"scenes/{scene_name}.json"))

    def cmd_scene_show(self, scene_name: str):
        from demo.V2.manage.scene import Scene
        scene_name = self._canon_name(scene_name)
        try:
            scene = Scene.load(scene_name)
        except Exception as exc:
            logging.error("Failed: %s", exc)
            return

        from typing import Any, cast, Dict, List, Tuple
        tl = cast(Dict[str, List[Tuple[Any, float, float | None]]], scene.timeline_with_times())
        for arm in ("left", "right"):
            logging.info("--- %s ---", arm.upper())
            t_cursor = 0.0
            for item, start, _ in tl[arm]:
                if item.type == "pause":
                    dur = item.duration or 0
                    logging.info("pause %ss  (t=%.2f→%.2f)", dur, start, start + dur)
                    t_cursor += dur
                else:
                    dur = self._track_duration(item.name) or 0
                    logging.info("track %s (%.2fs) (t=%.2f→%.2f)", item.name, dur, start, start + dur)
                    t_cursor += dur

    def _scene_play_once(self, scene_name: str):
        """Play a single scene *scene_name* synchronously.

        Internal helper used by cmd_scene_play to support sequential playback.
        """
        from demo.V2.manage.scene import Scene, SceneElement  # local import to avoid cycles
        scene_name = self._canon_name(scene_name)
        try:
            scene = Scene.load(scene_name)
        except Exception as exc:
            logging.error("Failed to load scene '%s': %s", scene_name, exc)
            return

        stop_flag = threading.Event()

        def _worker(seq: list[SceneElement], proxy: Optional[ArmProxy]):
            if proxy is None or not seq:
                return
            for el in seq:
                if stop_flag.is_set():
                    break
                if el.type == "pause":
                    # Respect external pause.txt (same semantics as in terminal_v2)
                    target_dur = float(el.duration or 0)
                    slept = 0.0
                    chk = 0.2  # poll interval

                    def _external_pause_active() -> bool:
                        from pathlib import Path
                        pf = Path(__file__).parent / "pause.txt"
                        try:
                            val = pf.read_text().strip()
                            logging.debug("[PAUSE_FILE] scene check %s -> %r", pf, val)
                            return val == "1"
                        except Exception:
                            return False

                    while slept < target_dur and not stop_flag.is_set():
                        if _external_pause_active():
                            time.sleep(chk)
                            continue  # do NOT accumulate
                        step = min(chk, target_dur - slept)
                        time.sleep(step)
                        slept += step
                    continue
                track_name = el.name
                if not track_name:
                    continue
                from demo.V2.manage.track import TrackBase, TrackV3Timed
                trk_obj = TrackBase.read_track(track_name)
                try:
                    if isinstance(trk_obj, TrackV3Timed):
                        proxy.cmd_play_v2(track_name)
                    else:
                        proxy.cmd_play(track_name)
                except Exception:
                    logging.exception("scene track play error")

        th_left = threading.Thread(target=_worker, args=(scene.left, self.left), daemon=True)
        th_right = threading.Thread(target=_worker, args=(scene.right, self.right), daemon=True)
        th_left.start()
        th_right.start()
        th_left.join()
        th_right.join()

    def cmd_scene_play(self, *scene_names: str):
        """Play one or several scenes sequentially.

        Usage:
            scene_play <scene1> [scene2 ...]

        Scenes are executed back-to-back without extra delay; the next scene
        starts immediately after the previous one completes.
        """
        if not scene_names:
            logging.info("scene_play: требуется ≥1 имя сцены")
            return

        for idx, sc_name in enumerate(scene_names, 1):
            logging.info("[SCENE PLAY] %d/%d → %s", idx, len(scene_names), sc_name)
            self._scene_play_once(sc_name)

    # ----------------------- generic fallback -----------------------
    def __getattr__(self, item):
        """If method unknown, try to broadcast to both proxies."""
        def _wrapper(*args, **kwargs):
            for proxy in (self.left, self.right):
                if proxy is None:
                    continue
                if hasattr(proxy, item):
                    try:
                        return getattr(proxy, item)(*args, **kwargs)
                    except Exception:
                        logging.debug("proxy %s.%s failed", proxy, item, exc_info=True)
            raise AttributeError(item)
        return _wrapper

    # ----------------------- alias helper -----------------------
    @staticmethod
    def _norm_side(token: str) -> str | None:
        """Map l/r/a aliases to left/right/all."""
        token = token.lower()
        if token in {"left", "l"}:
            return "left"
        if token in {"right", "r"}:
            return "right"
        if token in {"all", "both", "a"}:
            return "all"
        return None

    # ----------------- name canonicalisation -----------------
    @staticmethod
    def _canon_name(name: str) -> str:
        """Convert short prefixes (l_, r_, scene_) to canonical double-underscore form."""
        if name.startswith("l_"):
            return "left__" + name[2:]
        if name.startswith("left_"):
            return "left__" + name[5:]
        if name.startswith("r_"):
            return "right__" + name[2:]
        if name.startswith("right_") and not name.startswith("right__"):
            return "right__" + name[6:]
        if name.startswith("scene_") and not name.startswith("scene__"):
            return "scene__" + name[6:]
        return name

    # ----------------------- new get/set commands -----------------------
    def cmd_get(self, *args):
        """Получить текущие координаты.

        Использование:
            get                         – вывести coords обеих рук
            get <side>                  – вывести coords указанной руки (left/right)
            get <side> <joint_idx>      – coords конкретного сустава
        """
        if not args:
            # both arms full coords
            for label, proxy in (("LEFT", self.left), ("RIGHT", self.right)):
                if proxy is None:
                    continue
                try:
                    coords = proxy.cmd_get()
                    logging.info("%s %s", label, coords)
                except Exception:
                    logging.exception("[GET] proxy error (%s)", label)
            return

        side_norm = self._norm_side(args[0]) if args else None
        if side_norm is None:
            logging.error("[GET] first arg must be l/left or r/right")
            return
        side = side_norm
        proxy = self.left if side == "left" else self.right
        if proxy is None:
            logging.error("[GET] %s arm not initialised", side.upper())
            return
        if len(args) == 1:
            # full coords for side
            try:
                res = proxy.cmd_get()
            except Exception:
                logging.exception("[GET] proxy error")
                return
            # Worker returns dict {"left": .., "right": ..}
            coords = res.get(side) if isinstance(res, dict) else res
            logging.info("%s %s", side.upper(), coords)
            return
        if len(args) == 2:
            joint_idx = args[1]
            try:
                res = proxy.cmd_get(joint_idx)
            except Exception:
                logging.exception("[GET] failed to get joint")
                return
            val = res.get(side) if isinstance(res, dict) else res
            logging.info("%s joint[%s] = %s", side.upper(), joint_idx, val)
            return
        logging.error("[GET] wrong args")

    def cmd_set(self, *args):
        """Установить координату одного сустава.

        Использование: set <side> <joint_idx> <value>
        """
        # Two supported syntaxes:
        #   set <side> <joint_idx> <value>
        #   set <side> [list-of-7-ints]
        if len(args) < 2:
            logging.info("[SET] usage: set <left|right> <joint_idx> <value>   |   set <left|right> [list]")
            return

        side_norm = self._norm_side(args[0]) if args else None
        if side_norm not in {"left", "right"}:
            logging.error("[SET] first arg must be l/left or r/right")
            return
        side = side_norm  # type: ignore[assignment]
        proxy = self.left if side == "left" else self.right
        if proxy is None:
            logging.error("[SET] %s arm not initialised", side.upper())
            return

        # Try to detect multi-coordinate target (7 numbers).
        token_list = args[1:]
        # If first token starts with '[' join rest to parse easier
        combined = " ".join(token_list).strip()
        if combined.startswith("["):
            # probably bracketed list, keep combined string
            list_str = combined
        else:
            list_str = None

        if list_str or len(token_list) >= 7:
            # Attempt to parse coordinates list
            try:
                import json
                coords = json.loads(list_str) if list_str else [int(t.rstrip(',').strip()) for t in token_list]
            except Exception as exc:
                logging.error("[SET] cannot parse coordinates list: %s", exc)
                return
            if not (isinstance(coords, list) and len(coords) == 7):
                logging.error("[SET] list must contain 7 numbers")
                return
            try:
                ok = proxy.cmd_set_all(coords)
                logging.info("[SET] all result: %s", ok)
            except Exception:
                logging.exception("[SET] proxy error (set_all)")
            return

        # Case 2: joint_idx value
        if len(args) != 3:
            logging.info("[SET] usage: set <left|right> <joint_idx> <value>")
            return
        joint_idx, value = args[1], args[2]
        try:
            ok = proxy.cmd_set(side, joint_idx, value)
            logging.info("[SET] result: %s", ok)
        except Exception:
            logging.exception("[SET] proxy error")

    def cmd_incr(self, side: str, *args):
        """Increment joint or gripper on selected arm.

        incr <left|right> [joint_idx] <delta>
        If joint_idx omitted – gripper (6).
        """
        side_n = self._norm_side(side)
        proxy = self.left if side_n == "left" else self.right if side_n == "right" else None
        if proxy is None:
            logging.error("incr: first arg must be left/right and arm must be initialised")
            return
        proxy.cmd_incr(*args)

    def cmd_decr(self, side: str, *args):
        """Decrement joint (negative delta)."""
        side_n = self._norm_side(side)
        proxy = self.left if side_n == "left" else self.right if side_n == "right" else None
        if proxy is None:
            logging.error("decr: first arg must be left/right and arm must be initialised")
            return
        proxy.cmd_decr(*args)

    # -------------- short command aliases (placed after definitions) --------------

    cmd_g = cmd_get   # alias g → get
    # cmd_s already overloaded above
    cmd_i = cmd_incr  # alias i → incr
    cmd_d = cmd_decr  # alias d → decr

    # ----------------------- lifecycle -----------------------
    def shutdown(self):
        for proxy in (self.left, self.right):
            if proxy:
                proxy.shutdown()

    # ----------------------- simple REPL -----------------------
    def repl(self):
        logging.info("Piper terminal v3. Ctrl+D/Ctrl+C – exit.")
        while True:
            try:
                line = input("v3> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            # ---------------- quick history repeat '_' / '__' / ... --------
            stripped = line.strip()
            if stripped and set(stripped) == {'_'}:
                n = len(stripped)
                if 1 <= n <= len(self._cmd_history):
                    line = self._cmd_history[-n]
                    logging.info("↻ %s", line)
                else:
                    logging.warning("No command #%d in history", n)
                    continue  # wait next input

            # ---------------- hybrid-recording special handling ----------------
            if self._handle_hybrid_input(line):
                # line consumed by hybrid handler
                continue

            if not line:
                continue
            tokens = line.split()
            cmd, *args = tokens
            attr = f"cmd_{cmd.replace('-', '_')}"
            try:
                getattr(self, attr)(*args)  # type: ignore[attr-defined]
            except AttributeError:
                logging.warning("Unknown command: %s", cmd)
            except Exception:
                logging.exception("Unhandled error")

            # Save to history (skip repeats consisting of underscores)
            if line and set(line.strip()) != {'_'}:
                self._cmd_history.append(line)
                if len(self._cmd_history) > 10:
                    self._cmd_history.pop(0)
        self.shutdown()

    # ---------------- hybrid (r2) recording helpers -----------------
    def _active_hybrid_proxy(self) -> Optional[ArmProxy]:
        """Return the single proxy that is currently in hybrid recording mode.

        If none or more than one proxies are recording – return None.
        """
        active = [p for p in (self.left, self.right) if p and p.is_hybrid_recording()]
        if len(active) == 1:
            return active[0]
        if len(active) > 1:
            logging.warning("Both arms are recording – specify left/right explicitly.")
        return None

    def _handle_hybrid_input(self, raw: str) -> bool:
        """Intercept user input while r2 recording is active.

        Returns True if *raw* was handled here and should not be processed as a
        regular command.
        """
        proxy = self._active_hybrid_proxy()
        if proxy is None:
            return False  # no active hybrid recording

        stripped = raw.strip()

        # Stop recording
        if stripped.lower() in {"s", "stop"}:
            proxy.stop_hybrid_record()
            return True

        # Change default duration: "default <sec>"
        parts = stripped.split()
        if len(parts) == 2 and parts[0].lower() == "default":
            try:
                self._default_duration = float(parts[1])
                logging.info("[HYB-REC] Новый default duration = %.3fs", self._default_duration)
            except ValueError:
                logging.warning("[HYB-REC] Неверное число")
            return True

        # Empty input => add point with default duration
        if stripped == "":
            proxy.add_hybrid_point(self._default_duration)
            logging.info("[HYB-REC] + Точка (default %.3fs)", self._default_duration)
            return True

        # Single numeric token => duration
        if len(parts) == 1:
            try:
                dur = float(parts[0])
            except ValueError:
                return False  # not handled, fall through
            proxy.add_hybrid_point(dur)
            logging.info("[HYB-REC] + Точка (%.3fs)", dur)
            return True

        # Anything else – not handled here
        return False

    def cmd_list_timed(self):
        """List all TrackV3Timed tracks with point count and effective duration.

        For each v3 timed track found in the tracks directory prints:
            • track name
            • number of control points
            • total duration taking into account ``speed_up`` (as used during
              playback: ``dur * (1 - speed_up)`` for each segment).
        """
        from demo.V2.manage.track import TRACK_DIR, TrackBase, TrackV3Timed  # local import to avoid cycles

        timed_tracks = []  # (name, pts_cnt, duration, speed_up)
        for json_path in TRACK_DIR.glob("*.json"):
            name = json_path.stem
            try:
                trk_obj = TrackBase.read_track(name)
            except Exception:
                # Skip unreadable/invalid tracks silently
                continue
            if isinstance(trk_obj, TrackV3Timed):
                pts_cnt = len(trk_obj.points)
                # First duration value (index 0) corresponds to the first point
                # and is ignored during playback, so mirror that logic here.
                eff_duration = sum(
                    dur * (1 - trk_obj.speed_up) for dur in trk_obj.durations[1:]
                )
                timed_tracks.append((name, pts_cnt, eff_duration, trk_obj.speed_up))

        if not timed_tracks:
            logging.info("[LIST_TIMED] Нет треков v3 (timed).")
            return

        logging.info("[LIST_TIMED] Найдено %d трек(ов) v3:", len(timed_tracks))
        for name, pts_cnt, eff_dur, spdup in sorted(timed_tracks):
            logging.info("%s :: %d pts, duration=%.2fs (speed_up=%.2f)", name, pts_cnt, eff_dur, spdup)

    # alias for convenience
    cmd_lt = cmd_list_timed  # type: ignore[assignment]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    PiperTerminalV3().repl() 