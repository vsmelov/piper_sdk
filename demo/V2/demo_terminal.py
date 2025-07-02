#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_terminal.py – интерактивный терминал управления двумя роборуками Piper.

Список команд (введите «help»):

help                                   – вывод справки
status  {arm}                          – печатает статус руки(-рук)
enable  {arm}                          – включает серво-приводы
disable {arm}                          – отключает серво-приводы

Работа с траекториями (файлы лежат в каталоге «tracks»):
list  {arm}                            – плоский список имён
tree  {arm}                            – вывод в виде дерева

record {full_name}                    \
record {parent_fullname} {child}       – запись новой траектории (drag-teach)
 s                                      – остановить текущую запись

to_start {full_name}                   – переместить в начало трека
to_end   {full_name}                   – переместить в конец трека

play  {track1} {track2} …              – воспроизведение последовательности
viz   {track}                          – 3-D визуализация траектории

{arm}: l / r / b  (left – can0, right – can1, both)

Полное имя трека:  left__open_door__take_box (для правой — right__…)
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

# История ввода (POSIX)
try:
    import readline  # noqa: F401 – side-effect import
except ImportError:
    pass

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

TRACK_DIR = Path("tracks")
TRACK_DIR.mkdir(exist_ok=True)

# ---------- Настройки ----------
DELAY_BETWEEN_TRACKS = 3           # секунд паузы между треками

# Значение суставов SDK измеряются в «0.001 °» (тысячных долях градуса).
# Поэтому 1 ° = 1000 единиц SDK.
# Будем считать «близко», если ошибка ≤ 3 °.
TOLERANCE_ANGLE_DEG = 3
# преобразуем в единицы SDK (int, чтобы не плодить float-ы)
TOLERANCE_ANGLE_UNITS = TOLERANCE_ANGLE_DEG * 1000  # 3000 units = 3°


def _track_path(full_name: str) -> Path:
    """Путь к основному .json трека."""
    return TRACK_DIR / f"{full_name}.json"


def _details_path(full_name: str) -> Path:
    return TRACK_DIR / f"{full_name}.details.json"


class PiperTerminal:
    """REPL для управления двумя роборуками."""

    def __init__(self) -> None:
        # Инициализируем только левую руку (can0). Правая (can1) временно не используется.
        self.left_arm = SDK.get_instance("can0")
        self.right_arm = None  # заглушка
        try:
            self.left_arm.ConnectPort()
        except Exception as e:  # noqa: BLE001
            print("[WARN] Не удалось открыть CAN0:", e)
        # Запись
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_stop = threading.Event()

    # --------------------- базовые CAN-команды
    def cmd_status(self, arm_code: str):
        for arm in self._select(arm_code):
            st = arm.GetArmStatus().arm_status
            name = "LEFT" if arm is self.left_arm else "RIGHT"
            print(f"[{name}] mode={st.ctrl_mode} status={st.arm_status} err={st.err_code}")

    def cmd_enable(self, arm_code: str):
        for arm in self._select(arm_code):
            arm.MotionCtrl_1(emergency_stop=0x02)  # снять стоп
            arm.EnableArm(7)
            time.sleep(0.2)
            arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50)
        print("✓ EnableArm выполнен.")

    def cmd_disable(self, arm_code: str):
        for arm in self._select(arm_code):
            arm.DisableArm(7)
            arm.MotionCtrl_1(emergency_stop=0x01)  # быстрый стоп
            arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00, move_spd_rate_ctrl=0)
        print("✓ DisableArm выполнен.")

    # --------------------- list / tree
    def cmd_list(self, arm_code: str):
        for name in sorted(self._all_tracks()):
            if arm_code != "b":
                need = "left" if arm_code == "l" else "right"
                if not name.startswith(need):
                    continue
            print(name)

    def cmd_tree(self, arm_code: str):
        root: Dict[str, Dict] = {}

        def insert(node: Dict, parts: List[str]):
            if not parts:
                return
            head, *tail = parts
            node.setdefault(head, {})
            insert(node[head], tail)

        for name in self._all_tracks():
            if arm_code != "b":
                need = "left" if arm_code == "l" else "right"
                if not name.startswith(need):
                    continue
            insert(root, name.split("__"))

        def walk(node: Dict, indent: int = 0):
            for k in sorted(node):
                print("    " * indent + k)
                walk(node[k], indent + 1)

        walk(root)

    # --------------------- to_start / to_end
    def cmd_to_start(self, full_name: str):
        data = self._load(full_name)
        arm = self._arm_from_name(full_name)
        self._move_smooth(arm, data[0])
        print("✓ to_start выполнено.")

    def cmd_to_end(self, full_name: str):
        data = self._load(full_name)
        arm = self._arm_from_name(full_name)
        self._move_smooth(arm, data[-1])
        print("✓ to_end выполнено.")

    def _move_smooth(self, arm, target_pt, steps: int = 100, hz: int = 50):
        """Плавно ведёт руку к target_pt за ~steps/hz секунд."""
        curr = self._current_point(arm)
        diffs = [ (t - c) / steps for c, t in zip(curr, target_pt) ]

        period = 1.0 / hz
        # 1) Сбрасываем все возможные внутренние статусы после drag-teach
        arm.MotionCtrl_1(grag_teach_ctrl=0x02)   # гарант. выход из teach
        arm.MotionCtrl_1(track_ctrl=0x03)        # очистить текущую траекторию
        arm.MotionCtrl_1(emergency_stop=0x02)    # снять e-stop если висел

        # 2) Включаем сервоприводы и переходим в режим воспроизведения
        arm.EnableArm(7)
        time.sleep(0.3)  # даём драйверам подняться

        # 3) CAN-контроль, MOVE J, MIT-off
        arm.MotionCtrl_2(ctrl_mode=0x01, move_mode=0x01,
                          move_spd_rate_ctrl=50, is_mit_mode=0x00)
        time.sleep(0.1)

        for i in range(1, steps + 1):
            pt = [ int(c + d * i) for c, d in zip(curr, diffs) ]
            arm.JointCtrl(*pt[:6])
            arm.GripperCtrl(pt[6])
            time.sleep(period)
        # hold
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50)

    # --------------------- record / stop
    def cmd_record(self, *args: str):
        if self._rec_thread and self._rec_thread.is_alive():
            print("Запись уже идёт – остановите 's'.")
            return
        if len(args) == 1:
            full_name = args[0]
        elif len(args) == 2:
            parent, child = args
            if "__" in child:
                print("В child_name запрещено '__'.")
                return
            full_name = f"{parent}__{child}"
        else:
            print("record: требуется 1 или 2 аргумента.")
            return
        if _track_path(full_name).exists():
            print("Файл уже существует – выберите другое имя.")
            return
        arm = self._arm_from_name(full_name)
        print(f"[REC] {full_name} – перемещайте руку, 's' для стоп.")
        self._rec_stop.clear()
        self._rec_thread = threading.Thread(
            target=self._rec_worker, args=(arm, full_name), daemon=True
        )
        self._rec_thread.start()

    def cmd_s(self):
        if not (self._rec_thread and self._rec_thread.is_alive()):
            print("Ничего не записывается.")
            return
        self._rec_stop.set()
        self._rec_thread.join()
        print("✓ Запись остановлена.")

    def _rec_worker(self, arm, full_name: str, hz: int = 50):
        period = 1.0 / hz
        arm.MotionCtrl_1(grag_teach_ctrl=0x01)
        data: List[List[int]] = []
        details: List[dict] = []
        try:
            while not self._rec_stop.is_set():
                js = arm.GetArmJointMsgs().joint_state
                gr = arm.GetArmGripperMsgs().gripper_state
                hs = arm.GetArmHighSpdInfoMsgs()
                ls = arm.GetArmLowSpdInfoMsgs()
                data.append([js.joint_1, js.joint_2, js.joint_3, js.joint_4,
                             js.joint_5, js.joint_6, gr.grippers_angle])
                details.append({
                    "ts": time.time(),
                    "joints_deg001": [
                        js.joint_1,
                        js.joint_2,
                        js.joint_3,
                        js.joint_4,
                        js.joint_5,
                        js.joint_6,
                    ],
                    "gripper_deg001": gr.grippers_angle,
                    # High-speed feedback
                    "motor_speed_rpm": [
                        hs.motor_1.motor_speed,
                        hs.motor_2.motor_speed,
                        hs.motor_3.motor_speed,
                        hs.motor_4.motor_speed,
                        hs.motor_5.motor_speed,
                        hs.motor_6.motor_speed,
                    ],
                    "motor_current_ma": [
                        hs.motor_1.current,
                        hs.motor_2.current,
                        hs.motor_3.current,
                        hs.motor_4.current,
                        hs.motor_5.current,
                        hs.motor_6.current,
                    ],
                    "motor_pos_deg001": [
                        hs.motor_1.pos,
                        hs.motor_2.pos,
                        hs.motor_3.pos,
                        hs.motor_4.pos,
                        hs.motor_5.pos,
                        hs.motor_6.pos,
                    ],
                    "motor_effort_mNm": [
                        hs.motor_1.effort,
                        hs.motor_2.effort,
                        hs.motor_3.effort,
                        hs.motor_4.effort,
                        hs.motor_5.effort,
                        hs.motor_6.effort,
                    ],
                    # Low-speed feedback
                    "voltage_mv": [
                        ls.motor_1.vol,
                        ls.motor_2.vol,
                        ls.motor_3.vol,
                        ls.motor_4.vol,
                        ls.motor_5.vol,
                        ls.motor_6.vol,
                    ],
                    "foc_temp_c": [
                        ls.motor_1.foc_temp,
                        ls.motor_2.foc_temp,
                        ls.motor_3.foc_temp,
                        ls.motor_4.foc_temp,
                        ls.motor_5.foc_temp,
                        ls.motor_6.foc_temp,
                    ],
                    "motor_temp_c": [
                        ls.motor_1.motor_temp,
                        ls.motor_2.motor_temp,
                        ls.motor_3.motor_temp,
                        ls.motor_4.motor_temp,
                        ls.motor_5.motor_temp,
                        ls.motor_6.motor_temp,
                    ],
                    "bus_current_ma": [
                        ls.motor_1.bus_current,
                        ls.motor_2.bus_current,
                        ls.motor_3.bus_current,
                        ls.motor_4.bus_current,
                        ls.motor_5.bus_current,
                        ls.motor_6.bus_current,
                    ],
                })
                time.sleep(period)
        finally:
            # Выходим из режима drag-teach и удерживаем позицию
            arm.MotionCtrl_1(grag_teach_ctrl=0x02)  # завершить режим записи
            arm.EnableArm(7)
            arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50)
            _track_path(full_name).write_text(json.dumps(data))
            _details_path(full_name).write_text(json.dumps(details))
            print(f"[REC] Сохранено {len(data)} точек -> {_track_path(full_name)}.")

    # --------------------- play
    def cmd_play(self, *tracks: str):
        if not tracks:
            print("play: требуется >=1 трек")
            return
        for prev, curr in zip(tracks, tracks[1:]):
            if not curr.startswith(prev + "__"):
                print(f"Ошибка порядка: '{curr}' не является потомком '{prev}'.")
                return
        # Проверка стартовой позиции
        first_track_start = self._load(tracks[0])[0]
        arm0 = self._arm_from_name(tracks[0])
        if not self._is_close(self._current_point(arm0), first_track_start):
            print("[INFO] Перемещаю робота в начало трека…")
            self._move_smooth(arm0, first_track_start)
            time.sleep(0.2)

        for i, full_name in enumerate(tracks):
            data = self._load(full_name)
            arm = self._arm_from_name(full_name)
            print(f"[PLAY] {full_name} ({len(data)} pts)…")
            self._run_track(arm, data)
            if i < len(tracks) - 1:
                print(f"…пауза {DELAY_BETWEEN_TRACKS} c…")
                time.sleep(DELAY_BETWEEN_TRACKS)
        print("✓ Воспроизведение завершено.")

    # --------------------- viz
    def cmd_viz(self, track: str):
        try:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 side-effect
        except ImportError:
            print("Требуется 'matplotlib'. pip install matplotlib")
            return
        data = self._load(track)
        arm = self._arm_from_name(track)
        coords = []
        for pt in data:
            arm.JointCtrl(*pt[:6])  # записываем в контрол значения, потом читаем FK
            fk = arm.GetFK("control")
            x, y, z = fk[-1][:3]
            coords.append((x, y, z))
        xs, ys, zs = zip(*coords)
        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")
        ax.plot(xs, ys, zs)
        ax.set_xlabel("X, mm")
        ax.set_ylabel("Y, mm")
        ax.set_zlabel("Z, mm")
        plt.show()

    # --------------------- внутренние утилиты
    def _all_tracks(self):
        for p in TRACK_DIR.glob("*.json"):
            if p.name.endswith(".details.json"):
                continue
            yield p.stem

    def _select(self, code: str):
        code = code.lower()
        if code == "l":
            return (self.left_arm,)
        if code in {"r", "b"}:
            raise ValueError("Правая рука (can1) недоступна")
        raise ValueError("{arm} должен быть 'l'")

    def _arm_from_name(self, full_name: str):
        if full_name.startswith("left__"):
            return self.left_arm
        if full_name.startswith("right__"):
            raise ValueError("Правая рука (can1) недоступна")
        raise ValueError("Имя должно начинаться с left__")

    def _send_point(self, arm, pt):
        # гарантируем, что контроллер готов принять точку
        arm.EnableArm(7)
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=50)
        time.sleep(0.05)
        arm.JointCtrl(*pt[:6])
        arm.GripperCtrl(pt[6])

    def _run_track(self, arm, data: List[List[int]], hz: int = 50):
        period = 1.0 / hz
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01)
        step = max(1, len(data)//1000)
        for idx, pt in enumerate(data):
            if idx % step != 0 and idx != len(data)-1:
                continue
            self._send_point(arm, pt)
            time.sleep(period)
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)

    # --------------------- geometry helpers
    def _current_point(self, arm):
        js = arm.GetArmJointMsgs().joint_state
        gr = arm.GetArmGripperMsgs().gripper_state
        return [js.joint_1, js.joint_2, js.joint_3, js.joint_4, js.joint_5, js.joint_6, gr.grippers_angle]

    @staticmethod
    def _is_close(pt_a, pt_b, tol=TOLERANCE_ANGLE_UNITS):
        """Сравнивает две точки (7-элементные списки) с заданным допуском."""
        return all(abs(a - b) <= tol for a, b in zip(pt_a, pt_b))

    @staticmethod
    def _load(full_name: str) -> List[List[int]]:
        path = _track_path(full_name)
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text())

    # --------------------- exit helpers
    def cmd_exit(self):
        sys.exit(0)

    def cmd_quit(self):
        sys.exit(0)

    # --------------------- цикл ввода
    def repl(self):
        print("Piper dual-arm terminal. help – список команд. Ctrl+D/Ctrl+C – выход.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nВыход.")
                break
            if not line:
                continue
            tokens = line.split()
            cmd, *args = tokens
            try:
                getattr(self, f"cmd_{cmd}")(*args)  # type: ignore[attr-defined]
            except AttributeError:
                if cmd == "help":
                    print(__doc__)
                else:
                    print("Неизвестная команда.")
            except TypeError as e:
                print("[ARGS]", e)
            except Exception as e:  # noqa: BLE001
                print("[ERROR]", e)
        # корректно закрываем (только CAN0)
        self.left_arm.DisconnectPort()

    # --------------------- play_reverse
    def cmd_play_reverse(self, *tracks: str):
        if len(tracks) != 2:
            print("play_reverse: требуется ровно 2 трека (parent child)")
            return
        track1, track2 = tracks
        if not track2.startswith(track1 + "__"):
            print(f"'{track2}' не является потомком '{track1}'.")
            return

        # Проверяем текущую позицию – должна быть близка к КОНЦУ track2
        arm = self._arm_from_name(track2)
        current = self._current_point(arm)
        end_pt = self._load(track2)[-1]
        if not self._is_close(current, end_pt):
            print("[INFO] Рука в конце трека – автоматически перемещаю в начало…")
            self._move_smooth(arm, end_pt)
            return

        seq = [track2, track1]
        for i, full_name in enumerate(seq):
            data = self._load(full_name)[::-1]  # проигрываем в обратном порядке
            arm = self._arm_from_name(full_name)
            print(f"[REV] {full_name} (rev, {len(data)} pts)…")
            self._run_track(arm, data)
            if i < len(seq) - 1:
                print(f"…пауза {DELAY_BETWEEN_TRACKS} c…")
                time.sleep(DELAY_BETWEEN_TRACKS)
        print("✓ Reverse-воспроизведение завершено.")


# -------------------------------------------------------------------- MAIN
if __name__ == "__main__":
    terminal = PiperTerminal()
    terminal.repl() 