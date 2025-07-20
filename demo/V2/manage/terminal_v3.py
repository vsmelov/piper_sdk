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
        if CAN_LEFT is not None:
            self.left = ArmProxy(CAN_LEFT, side="left")
            logging.info("Left arm proxy ready (%s)", CAN_LEFT)
        if CAN_RIGHT is not None:
            self.right = ArmProxy(CAN_RIGHT, side="right")
            logging.info("Right arm proxy ready (%s)", CAN_RIGHT)

    # --------------------- util helpers ---------------------
    def _proxy_for_track(self, name: str) -> ArmProxy:
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
        proxy = self._proxy_for_track(args[0] if len(args) == 1 else args[0])
        proxy.cmd_record(*args)

    # alias
    cmd_r = cmd_record  # type: ignore[assignment]

    def cmd_record_v2(self, *args):
        if not args:
            logging.info("record_v2: требуется имя трека")
            return
        proxy = self._proxy_for_track(args[0] if len(args) == 1 else args[0])
        proxy.cmd_record_v2(*args)

    # alias
    cmd_r2 = cmd_record_v2  # type: ignore[assignment]

    def cmd_s(self):
        """stop recording"""
        self._call_both("cmd_s")

    # ----------------------- play -----------------------
    def cmd_play(self, *tracks: str):
        if not tracks:
            logging.info("play: требуется >=1 трек")
            return
        # Группируем треки по рукам
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
        th = []
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
        """Reset arms.

        Usage:
            reset all   – обе руки
            reset left  – только левая
            reset right – только правая
        По умолчанию сбрасываются обе руки.
        """
        target = target.lower() if isinstance(target, str) else "all"
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

    def cmd_scene_play(self, scene_name: str):
        from demo.V2.manage.scene import Scene, SceneElement
        try:
            scene = Scene.load(scene_name)
        except Exception as exc:
            logging.error("Failed to load scene: %s", exc)
            return

        stop_flag = threading.Event()

        def _worker(seq: list[SceneElement], proxy: Optional[ArmProxy]):
            if proxy is None or not seq:
                return
            for el in seq:
                if stop_flag.is_set():
                    break
                if el.type == "pause":
                    time.sleep(el.duration or 0)
                    continue
                track_name = el.name
                if not track_name:
                    continue
                # Determine play method based on track type
                from demo.V2.manage.track import TrackBase, TrackV3Timed  # local import
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
        self.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    PiperTerminalV3().repl() 