from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
import math
from dataclasses import dataclass

# История ввода (POSIX)
try:
    import readline  # noqa: F401 – side-effect import
except ImportError:
    pass
else:
    # Файл истории команд (persist между сессиями)
    _HIST_PATH = Path.home() / ".piper_terminal_history"
    try:
        readline.read_history_file(_HIST_PATH)
    except FileNotFoundError:
        pass

    import atexit

    def _save_history():
        try:
            readline.write_history_file(_HIST_PATH)
        except Exception:
            pass

    atexit.register(_save_history)

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK
from demo.V2.settings import CAN_NAME
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
)

TRACK_DIR = Path("tracks")
TRACK_DIR.mkdir(exist_ok=True)

SAFE_DIR = TRACK_DIR / "_safe"
SAFE_DIR.mkdir(exist_ok=True)

ZERO_POS_PATH = SAFE_DIR / "zero_position.json"
# The gripper torque, in 0.001 N/m. Range 0-5000 (corresponds 0-5 N/m)
GRIPPER_EFFORT = 4000

# DANGEROUS constant: how much the gripper will additionally squeeze during playback.
# Value is a fraction; resulting gripper angle is reduced by this coefficient (tightening).
GRIPPER_TIGHT_COEFFICEINT = 0.02  # ⚠️ changing this may break grasp reliability

# ---------- Настройки ----------
DELAY_BETWEEN_TRACKS = 3  # секунд паузы между треками

# Значение суставов SDK измеряются в «0.001 °» (тысячных долей градуса).
# Поэтому 1 ° = 1000 единиц SDK.
# Будем считать «близко», если ошибка ≤ 3 °.
TOLERANCE_ANGLE_DEG = 3
# преобразуем в единицы SDK (int, чтобы не плодить float-ы)
TOLERANCE_ANGLE_UNITS = TOLERANCE_ANGLE_DEG * 1000  # 3000 units = 3°

# Сколько конечных суставов игнорировать при проверках (wrist roll, gripper и т.п.)
IGNORED_JOINTS = [
    3, 5, 6
]

# ------------------------------------------------- helpers -------------------------------------------------

def _track_path(full_name: str) -> Path:
    """Путь к основному .json трека."""
    return TRACK_DIR / f"{full_name}.json"


def _details_path(full_name: str) -> Path:
    return TRACK_DIR / f"{full_name}.details.json"


def _zero_track_path(name: str) -> Path:
    """Файл безопасного (zero) трека внутри SAFE_DIR."""
    return SAFE_DIR / f"zero_track__{name}.json"


def _zero_track_details_path(name: str) -> Path:
    return SAFE_DIR / f"zero_track__{name}.details.json"


def _list_zero_tracks() -> List[Path]:
    """Возвращает только основные файлы треков (без *.details.json)."""
    return sorted(
        p for p in SAFE_DIR.glob("zero_track__*.json") if not p.name.endswith(".details.json")
    )


@dataclass
class PiperResponse:
    ok: bool
    error: Optional[str] = None
    note: Optional[str] = None


class PiperTerminal:
    """REPL для управления одной (левой) роборукой.

    Команды:
        record <name>               – запись обычного трека
        r <name>                    – то же, что record (alias)
        s                           – остановить запись
        play  <t1> [t2 ...]         – воспроизведение треков
        p  <t1> [t2 ...]            – то же, что play (alias)
        r-0-pos                     – записать Zero-позицию
        r-0-track [name]            – записать безопасный Zero-трек
        check-0-pos                 – максимальная дельта от Zero-позиции
        check-0-track               – минимальная дельта до Zero-треков
        get_track_range <name>      – min/max значений суставов по всему треку
    """

    def __init__(self) -> None:
        # Инициализируем только левую руку (can0). Правая (can1) временно не используется.
        self.left_arm = SDK.get_instance(CAN_NAME)
        self.right_arm = None  # заглушка
        try:
            self.left_arm.ConnectPort()
            logging.info("CAN0 port connected.")
        except Exception as e:  # noqa: BLE001
            logging.info(f"[WARN] Не удалось открыть CAN0: {e}")
        # Запись
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_stop = threading.Event()

    def __dangerous_reset(self, arm):
        # это код полное говно, но работает
        # надо разобраться что тут реально нужно а что нет (либо забить хуй)
        # 1) Сбрасываем все возможные внутренние статусы после drag-teach
        logging.info("MotionCtrl_1: grag_teach_ctrl=0x02")
        arm.MotionCtrl_1(grag_teach_ctrl=0x02)  # гарант. выход из teach
        logging.info("MotionCtrl_1: track_ctrl=0x03")
        arm.MotionCtrl_1(track_ctrl=0x03)  # очистить текущую траекторию
        logging.info("MotionCtrl_1: emergency_stop=0x02")
        arm.MotionCtrl_1(emergency_stop=0x02)  # снять e-stop если висел

        arm.DisconnectPort()

        time.sleep(1)  # даем piper перезагрузится, если ждать меньше будет рука-импотент

        arm = SDK.get_instance(CAN_NAME)  # важно пересоздать руку (я хз почему)
        arm.ConnectPort(can_init=True)  # этот аргумент важен


        logging.info("DisableArm: id_mask=7")
        for i in range(10):  # быдлохак
            arm.DisableArm(7)
            arm.GripperCtrl(0, 1000, 0x02, 0)  # Disable and clear error
            time.sleep(0.01)
        logging.info("disabled probably")


        # это отвратительная копипаста из примера demo.V2
        def enable_fun(piper):
            start = time.time()
            while True and time.time() - start < 5:
                enable_list = []
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_1.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_2.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_3.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_4.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_5.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status)
                enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status)
                # enable_list.append()
                gripper_status = piper.GetArmGripperMsgs().gripper_state.status_code
                gripper_foc_status = str(piper.GetArmGripperMsgs().gripper_state.foc_status)
                enable_flag = all(enable_list)
                piper.EnableArm(7)
                logging.info(f'enabling gripper, current status: {gripper_status}, {gripper_foc_status}')
                # piper.GripperCtrl(0, 1000, 0x01, 0)
                piper.GripperCtrl(50_000, 1000, 0x01, 0)
                if enable_flag:
                    break
                time.sleep(0.1)

        # 2) Включаем сервоприводы и переходим в режим воспроизведения
        # logging.info("EnableArm: id_mask=7")
        # for i in range(10):  # быдлохак
        #     arm.EnableArm(7)
        #     time.sleep(0.01)
        enable_fun(arm)

        # 3) CAN-контроль, MOVE J, MIT-off
        logging.info(
            "MotionCtrl_2: ctrl_mode=0x01, move_mode=0x01, "
            "move_spd_rate_ctrl=50, is_mit_mode=0x00"
        )
        arm.MotionCtrl_2(
            ctrl_mode=0x01,
            move_mode=0x01,
            move_spd_rate_ctrl=50,
            is_mit_mode=0x00,
        )
        arm.GripperCtrl(50_000, 1000, 0x01, 0)
        arm.ModeCtrl(0x01, 0x01, 50, 0x00)  # включаем контроль руки
        time.sleep(1)  # wait

        # arm.SetSDKJointLimitParam('j6', -2.09439 - 0.1, 2.09439 + 0.1)  # отключаем крайние лимиты

    # --------------------------------- util helpers ----------------------------------------------------
    def _confirm_overwrite(self, path: Path) -> bool:
        """Спрашивает у пользователя подтверждение на перезапись файла."""
        try:
            ans = input(f"Файл {path.name} уже существует. Перезаписать? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            logging.info("Отмена.")
            return False
        return ans == "y"

    # --------------------------------- motion helpers ---------------------------------------------------
    def _move_smooth(self, arm, target_pt, steps: int = 100, hz: int = 50) -> PiperResponse:
        """Плавно ведёт руку к target_pt за ~steps/hz секунд."""
        curr = self._current_point(arm)
        diffs = [(t - c) / steps for c, t in zip(curr, target_pt)]
        period = 1.0 / hz

        logging.info(f'[SEND] sending points started')
        for i in range(steps):
            pt = [int(c + d * i) for c, d in zip(curr, diffs)]
            self._send_point(arm, pt)
            time.sleep(period)  # todo: too aggressive
        logging.info(f'[SEND] sending points finished')

        if not self._is_close_strict(self._current_point(arm), target_pt):
            return PiperResponse(
                ok=False,
                error='not close to target_pt',
            )

        return PiperResponse(
            ok=True,
        )

    # --------------------------------- Zero safety helpers ---------------------------------------------
    def _maybe_reset_from_safe_pose_and_move_to_0(self, arm) -> PiperResponse:
        """Если текущая поза достаточно близка к любому Zero-треку – выполняем безопасный reset.

        Алгоритм:
            1. Проверяем близость к точкам всех Zero-треков.
            2. Если попали, плавно переводим в Zero-позицию.
        """
        z_tracks = _list_zero_tracks()
        if not z_tracks:
            return PiperResponse(
                ok=False,
                error='no 0 tracks'
            )

        curr = self._current_point(arm)
        found = False
        for p in z_tracks:
            if found:
                break
            try:
                data = json.loads(p.read_text())
            except Exception as exc:
                logging.exception(f'fail: {exc}')
                continue
            # Проверяем не каждую точку, чтобы не тратить время
            for pt in data:
                if self._is_close_ignored(curr, pt):
                    logging.info(f"[SAFE] Находимся в безопасном треке ({p.name}).")
                    found = True
                    break

        if not found:
            logging.error("[UNSAFE] далеко от safe-track")
            return PiperResponse(
                ok=False,
                error='far from 0 tracks'
            )

        logging.info("[SAFE] близко к safe-track, СБРОС")
        self.__dangerous_reset(arm)
        self.__dangerous_reset(arm)
        # эту штуку важно вызвать два раза иначе рука не напряжется (мне пока лень разбираться почему)

        logging.info("[SAFE] едем в 0-pos")
        zero_pos = json.loads(ZERO_POS_PATH.read_text())
        self._move_smooth(arm, zero_pos)
        if not self.cmd_check_0_pos():
            logging.error(f'[ERROR] мы не приехали в 0 pos')
            return PiperResponse(
                ok=False,
                error='not in 0 pos'
            )
        else:
            logging.info("[SAFE] приехали в 0-pos")
            return PiperResponse(
                ok=True,
            )

    # --------------------------------- safety helpers ------------------------------------------------
    def _is_near_zero_track(self, arm) -> bool:
        """Проверяет, близка ли текущая поза к любой точке Zero-треков (с учётом tol)."""
        for p in _list_zero_tracks():
            try:
                data = json.loads(p.read_text())
            except Exception as exc:
                logging.exception(f'error: {exc}')
                continue
            for pt in data:  # проверяем все точки, чтобы не пропустить ближайшую
                if self._is_close_ignored(self._current_point(arm), pt):
                    return True
        return False

    def _safe_move_smooth(self, arm, target_pt) -> bool:
        """Безопасный вариант _move_smooth. Выполняется только если рука уже находится
        рядом с одной из безопасных поз (Zero-track). Возвращает True если движение
        начато, False если отказано (небезопасно).
        """
        if not self._is_near_zero_track(arm):
            logging.error("[SAFE-MOVE] Current pose is not near any Zero-track. Aborting move.")
            return False
        self._move_smooth(arm, target_pt)
        return True

    # --------------------------------- math helpers ---------------------------------------------------
    @staticmethod
    def _considered_diffs(pt_a: List[int], pt_b: List[int]) -> List[int]:
        """Разницы суставов, исключая IGNORED_JOINTS."""
        return [abs(a - b) for idx, (a, b) in enumerate(zip(pt_a, pt_b)) if idx not in IGNORED_JOINTS]

    @staticmethod
    def _max_delta_and_joint_strict(pt_a: List[int], pt_b: List[int]):
        """Возвращает (max_delta, worst_joint_index) учитывая ВСЕ суставы."""
        diffs = [abs(a - b) for a, b in zip(pt_a, pt_b)]
        max_delta = max(diffs)
        worst_joint = diffs.index(max_delta)
        return max_delta, worst_joint

    @staticmethod
    def _max_delta_and_joint_ignored(pt_a: List[int], pt_b: List[int]):
        """Возвращает (max_delta, worst_joint_index) игнорируя IGNORED_JOINTS."""
        diffs = [abs(a - b) for a, b in zip(pt_a, pt_b)]
        max_delta = -1
        worst_joint = None
        for idx, d in enumerate(diffs):
            if idx in IGNORED_JOINTS:
                continue
            if d > max_delta:
                max_delta = d
                worst_joint = idx
        return max_delta, worst_joint if worst_joint is not None else -1

    # --------------------------------- diagnostic commands -------------------------------------------
    def cmd_check_0_pos(self) -> bool:
        """Проверяет отклонение от сохранённой Zero-позиции."""
        if not ZERO_POS_PATH.exists():
            logging.info("[CHECK-0-POS] Zero-позиция не сохранена.")
            return False
        target = json.loads(ZERO_POS_PATH.read_text())
        curr = self._current_point(self.left_arm)
        max_delta, worst_joint = self._max_delta_and_joint_ignored(curr, target)
        status = "SUCCESS" if max_delta <= TOLERANCE_ANGLE_UNITS else "FAIL"
        diff_units = abs(TOLERANCE_ANGLE_UNITS - max_delta)
        diff_deg = diff_units / 1000
        logging.info(
            f"[CHECK-0-POS] Δmax = {max_delta} units (~{max_delta/1000:.3f}°) – {status} | "
            f"tolerance {TOLERANCE_ANGLE_UNITS} units (~{TOLERANCE_ANGLE_UNITS/1000:.1f}°), "
            f"{('margin','exceeded')[status=='FAIL']} by {diff_units} units (~{diff_deg:.3f}°) | worst joint #{worst_joint}"
        )
        return max_delta <= TOLERANCE_ANGLE_UNITS

    def cmd_check_0_track(self):
        """Минимальная ошибка по всем Zero-трекам относительно текущей позы."""
        tracks = _list_zero_tracks()
        if not tracks:
            logging.info("[CHECK-0-TRACK] Нет ни одного Zero-трека.")
            return
        curr = self._current_point(self.left_arm)
        best = math.inf
        best_worst_joint = None
        best_pt: Optional[List[int]] = None
        for p in tracks:
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            for pt in data:
                numeric_pt = [int(x) for x in pt]
                max_d, worst_joint_candidate = self._max_delta_and_joint_ignored(curr, numeric_pt)
                if max_d < best:
                    best = max_d
                    best_worst_joint = worst_joint_candidate
                    best_pt = numeric_pt
                    if best == 0:
                        break
            if best == 0:
                break

        if best is math.inf:
            logging.info("[CHECK-0-TRACK] Не удалось прочитать треки.")
        else:
            status = "SUCCESS" if best <= TOLERANCE_ANGLE_UNITS else "FAIL"
            diff_units = abs(TOLERANCE_ANGLE_UNITS - best)
            diff_deg = diff_units / 1000
            logging.info(
                f"[CHECK-0-TRACK] Δmin = {best} units (~{best/1000:.3f}°) – {status} | "
                f"tolerance {TOLERANCE_ANGLE_UNITS} units (~{TOLERANCE_ANGLE_UNITS/1000:.1f}°), "
                f"{('margin','exceeded')[status=='FAIL']} by {diff_units} units (~{diff_deg:.3f}°) | "
                f"worst joint #{best_worst_joint} | best point {best_pt}"
            )

    def cmd_get_track_range(self, track: str):
        """Показывает диапазоны (min/max) углов для каждого сустава по треку.

        usage: get_track_range <track_name>
        """
        if not track:
            logging.info("get_track_range: требуется имя трека")
            return
        try:
            data = self._load(track)
        except Exception as exc:
            logging.error(f"[ERROR] {exc}")
            return

        # Инициализируем списки длиной 7 (6 суставов + захват)
        mins = [math.inf] * 7
        maxs = [-math.inf] * 7
        for pt in data:
            for i, val in enumerate(pt):
                mins[i] = min(mins[i], val)
                maxs[i] = max(maxs[i], val)

        joint_names = ["j1", "j2", "j3", "j4", "j5", "j6", "gripper"]
        for i, name in enumerate(joint_names):
            logging.info(f"{name}: min={mins[i]}, max={maxs[i]}")

    # --------------------------------- record / stop ----------------------------------------------------
    def cmd_record(self, *args: str):
        if self._rec_thread and self._rec_thread.is_alive():
            logging.info("Запись уже идёт – остановите 's'.")
            return
        if len(args) == 1:
            full_name = args[0]
        elif len(args) == 2:
            parent, child = args
            if "__" in child:
                logging.info("В child_name запрещено '__'.")
                return
            full_name = f"{parent}__{child}"
        else:
            logging.info("record: требуется 1 или 2 аргумента.")
            return
        track_file = _track_path(full_name)
        if track_file.exists():
            if not self._confirm_overwrite(track_file):
                return
        arm = self._arm_from_name(full_name)
        logging.info(f"[REC] {full_name} – перемещайте руку, 's' для стоп.")
        self._rec_stop.clear()
        self._rec_thread = threading.Thread(
            target=self._rec_worker, args=(arm, full_name), daemon=True
        )
        self._rec_thread.start()

    def cmd_r_0_pos(self):
        """Сохранить текущую позу как Zero-позицию."""
        pos = self._current_point(self.left_arm)
        ZERO_POS_PATH.write_text(json.dumps(pos))
        logging.info(f"[ZERO-POS] Сохранено -> {ZERO_POS_PATH}\n           Точка: {pos}")

    def cmd_r_0_track(self, *args: str):
        """Запись безопасного Zero-трека.

        usage: r-0-track [name]
        Если name не указан – берётся метка времени.
        """
        if self._rec_thread and self._rec_thread.is_alive():
            logging.info("Запись уже идёт – остановите 's'.")
            return
        if args and len(args) > 1:
            logging.info("r-0-track: требуется максимум 1 аргумент.")
            return
        name = args[0] if args else time.strftime("%Y%m%d_%H%M%S")
        if "__" in name or "/" in name:
            logging.info("Имя не должно содержать '__' или '/'.")
            return
        json_path = _zero_track_path(name)
        if json_path.exists():
            if not self._confirm_overwrite(json_path):
                return
        arm = self.left_arm
        logging.info(f"[REC-SAFE] {json_path.name} – перемещайте руку, 's' для стоп.")
        self._rec_stop.clear()
        self._rec_thread = threading.Thread(
            target=self._rec_worker_safe, args=(arm, name), daemon=True
        )
        self._rec_thread.start()

    def cmd_s(self):
        if not (self._rec_thread and self._rec_thread.is_alive()):
            logging.info("Ничего не записывается.")
            return
        self._rec_stop.set()
        self._rec_thread.join()
        logging.info("✓ Запись остановлена.")

    # --------------------------------- workers ----------------------------------------------------------
    def _rec_worker(self, arm, full_name: str, hz: int = 50):
        """Работник записи обычного трека."""
        period = 1.0 / hz
        logging.info("MotionCtrl_1: grag_teach_ctrl=0x01   (start recording)")
        arm.MotionCtrl_1(grag_teach_ctrl=0x01)
        data: List[List[int]] = []
        details: List[dict] = []
        zero_start: Optional[float] = None
        zero_warned = False
        try:
            while not self._rec_stop.is_set():
                js = arm.GetArmJointMsgs().joint_state
                gr = arm.GetArmGripperMsgs().gripper_state
                curr_point = [
                    js.joint_1,
                    js.joint_2,
                    js.joint_3,
                    js.joint_4,
                    js.joint_5,
                    js.joint_6,
                    gr.grippers_angle,
                ]

                if all(v == 0 for v in curr_point):
                    if zero_start is None:
                        zero_start = time.time()
                    elif time.time() - zero_start > 0.1 and not zero_warned:
                        logging.error("[REC] Получаем нулевые данные >0.1s – проверьте соединение.")
                        zero_warned = True
                    time.sleep(period)
                    continue
                else:
                    zero_start = None
                    zero_warned = False

                data.append(curr_point)
                hs = arm.GetArmHighSpdInfoMsgs()
                ls = arm.GetArmLowSpdInfoMsgs()
                details.append(
                    {
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
                    }
                )
                time.sleep(period)
        finally:
            self._finalize_record(arm)
            _track_path(full_name).write_text(json.dumps(data))
            _details_path(full_name).write_text(json.dumps(details))
            logging.info(
                f"[REC] Сохранено {len(data)} точек -> {_track_path(full_name)}."
            )

    def _rec_worker_safe(self, arm, safe_name: str, hz: int = 50):
        """Работник записи безопасного Zero-трека."""
        period = 1.0 / hz
        logging.info("MotionCtrl_1: grag_teach_ctrl=0x01   (start recording SAFE)")
        arm.MotionCtrl_1(grag_teach_ctrl=0x01)
        data: List[List[int]] = []
        details: List[dict] = []
        zero_start: Optional[float] = None
        zero_warned = False
        try:
            while not self._rec_stop.is_set():
                js = arm.GetArmJointMsgs().joint_state
                gr = arm.GetArmGripperMsgs().gripper_state
                curr_point = [
                    js.joint_1,
                    js.joint_2,
                    js.joint_3,
                    js.joint_4,
                    js.joint_5,
                    js.joint_6,
                    gr.grippers_angle,
                ]

                if all(v == 0 for v in curr_point):
                    if zero_start is None:
                        zero_start = time.time()
                    elif time.time() - zero_start > 0.1 and not zero_warned:
                        logging.error("[REC-SAFE] Получаем нулевые данные >0.1s – проверьте соединение.")
                        zero_warned = True
                    time.sleep(period)
                    continue
                else:
                    zero_start = None
                    zero_warned = False

                data.append(curr_point)
                details.append({"ts": time.time()})
                time.sleep(period)
        finally:
            self._finalize_record(arm)
            json_path = _zero_track_path(safe_name)
            json_path.write_text(json.dumps(data))
            _zero_track_details_path(safe_name).write_text(json.dumps(details))
            logging.info(
                f"[REC-SAFE] Сохранено {len(data)} точек -> {json_path}."
            )

    def _finalize_record(self, arm):
        """Общий хвост после любой записи."""
        logging.info("MotionCtrl_1: grag_teach_ctrl=0x02   (stop recording)")
        arm.MotionCtrl_1(grag_teach_ctrl=0x02)  # завершить режим записи
        logging.info("EnableArm: id_mask=7")
        arm.EnableArm(7)
        logging.info("ModeCtrl: ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50")
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50)

    # --------------------------------- play -------------------------------------------------------------
    def cmd_play(self, *tracks: str):
        if not tracks:
            logging.info("play: требуется >=1 трек")
            return
        # for prev, curr in zip(tracks, tracks[1:]):
        #     if not curr.startswith(prev + "__"):
        #         logging.info(f"Ошибка порядка: '{curr}' не является потомком '{prev}'.")
        #         return

        # Проверка безопасности перед reset-ом
        arm0 = self._arm_from_name(tracks[0])
        result = self._maybe_reset_from_safe_pose_and_move_to_0(arm0)
        if not result.ok:
            logging.error(f'bad status: {result}')
            return

        # Теперь проверка стартовой позиции трека
        first_track_start = self._load(tracks[0])[0]
        if not self._is_close_ignored(self._current_point(arm0), first_track_start):
            logging.info("[INFO] Перемещаю робота в начало трека…")
            if not self._safe_move_smooth(arm0, first_track_start):
                logging.error("[PLAY] Движение к стартовой точке отменено из соображений безопасности.")
                return
            time.sleep(0.2)

        for i, full_name in enumerate(tracks):
            data = self._load(full_name)
            details = self._load_details(full_name)
            arm = self._arm_from_name(full_name)
            logging.info(f"[PLAY] {full_name} ({len(data)} pts)…")
            self._run_track(arm, data, details)
            if i < len(tracks) - 1:
                logging.info(f"…пауза {DELAY_BETWEEN_TRACKS} c…")
                time.sleep(DELAY_BETWEEN_TRACKS)
        logging.info("✓ Воспроизведение завершено.")

    # --------------------------------- low-level helpers -----------------------------------------------
    def _arm_from_name(self, full_name: str):
        if full_name.startswith("left__"):
            return self.left_arm
        if full_name.startswith("right__"):
            raise ValueError("Правая рука (can1) недоступна")
        raise ValueError("Имя должно начинаться с left__")

    def _send_point(self, arm, pt):
        arm.JointCtrl(*pt[:6])
        # Apply tightening if configured (>0)
        grip_val = pt[6]
        if GRIPPER_TIGHT_COEFFICEINT > 0:
            grip_val = int(grip_val * (1 - GRIPPER_TIGHT_COEFFICEINT))
        arm.GripperCtrl(grip_val, GRIPPER_EFFORT, 0x01, 0)

    def _prepare_track_play(self, arm):
        """Один раз перед отправкой траектории настраиваем режим."""
        arm.EnableArm(7)
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=50)
        time.sleep(0.02)

    def _run_track(self, arm, data: List[List[int]], details: Optional[List[dict]] = None, hz: int = 50):
        """Play the given trajectory.

        If timestamps are provided in *details*, the playback speed will match the
        original recording. Otherwise falls back to a fixed *hz* rate.
        """
        if details is None:
            details = []
        use_timestamps = bool(details)
        if use_timestamps and len(details) != len(data):
            logging.warning("[PLAY] details length mismatch – falling back to fixed hz mode")
            use_timestamps = False

        period = 1.0 / hz
        logging.info("ModeCtrl: ctrl_mode=0x01, move_mode=0x01   (start track)")
        self._prepare_track_play(arm)
        total_pts = len(data)
        last_pct = -10
        step_log = max(1, total_pts // 100)
        # Мы больше не пропускаем точки, чтобы обеспечить корректный тайминг
        started_at: float = time.time() if use_timestamps else 0.0
        first_ts: float = details[0]['ts'] if use_timestamps else 0.0

        for idx, pt in enumerate(data):
            if use_timestamps:
                target_offset = details[idx]['ts'] - first_ts
                run_time = time.time() - started_at
                delay = max(0.0, target_offset - run_time)
                if delay > 0:
                    time.sleep(delay)
                self._send_point(arm, pt)
            else:
                self._send_point(arm, pt)
                time.sleep(period)

            # выводим погрешность между целевой точкой и фактической позой
            if idx % step_log == 0:  # примерно 1% шаг
                feedback = self._current_point(arm)
                delta = [abs(a - b) for a, b in zip(feedback, pt)]
                logging.info(f"[DELTA] {delta}")

            pct = int((idx + 1) * 100 / total_pts)
            if pct // 10 > last_pct // 10:
                last_pct = pct
                logging.info(f"[PLAY] progress {pct}% ({idx+1}/{total_pts})")

        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
        logging.info("ModeCtrl: ctrl_mode=0x00, move_mode=0x00   (end track)")

    # --------------------------------- geometry helpers ------------------------------------------------
    def _current_point(self, arm):
        js = arm.GetArmJointMsgs().joint_state
        gr = arm.GetArmGripperMsgs().gripper_state
        return [
            js.joint_1,
            js.joint_2,
            js.joint_3,
            js.joint_4,
            js.joint_5,
            js.joint_6,
            gr.grippers_angle,
        ]

    @staticmethod
    def _is_close_strict(pt_a, pt_b, tol=TOLERANCE_ANGLE_UNITS):
        """Сравнение без исключений суставов (строгий режим)."""
        return all(abs(a - b) <= tol for a, b in zip(pt_a, pt_b))

    @staticmethod
    def _is_close_ignored(pt_a, pt_b, tol=TOLERANCE_ANGLE_UNITS):
        """Сравнение с игнорированием IGNORED_JOINTS."""
        return PiperTerminal._max_delta_and_joint_ignored(pt_a, pt_b)[0] <= tol

    @staticmethod
    def _load(full_name: str) -> List[List[int]]:
        path = _track_path(full_name)
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text())

    @staticmethod
    def _load_details(full_name: str) -> List[dict]:
        """Load per-point metadata (including timestamps) for a track.

        Returns an empty list if the *.details.json file is missing.
        """
        try:
            path = _details_path(full_name)
            if not path.exists():
                return []
            return json.loads(path.read_text())
        except Exception:
            # Any problem reading – degrade gracefully to empty list
            logging.exception(f"[WARN] Failed to load details for {full_name}")
            return []

    # --------------------------------- цикл ввода ------------------------------------------------------
    def repl(self):
        logging.info(
            "Piper terminal v2. help – список команд. Ctrl+D/Ctrl+C – выход."
        )
        # Показываем справку сразу, чтобы пользователь видел доступные команды
        logging.info(self.__doc__)
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                logging.info("\nВыход.")
                break
            if not line:
                continue
            tokens = line.split()
            cmd, *args = tokens
            attr = f"cmd_{cmd.replace('-', '_')}"  # поддержка дефисов
            try:
                getattr(self, attr)(*args)  # type: ignore[attr-defined]
            except AttributeError:
                if cmd == "help":
                    logging.info(self.__doc__)
                else:
                    logging.info("Неизвестная команда.")
            except TypeError as e:
                logging.info(f"[ARGS] {e}")
            except Exception:  # noqa: BLE001
                logging.exception("[EXCEPTION] Unhandled error")
        # корректно закрываем (только CAN0)
        self.left_arm.DisconnectPort()

    # Алиасы коротких команд --------------------------------------------------
    def cmd_r(self, *args: str):
        """Alias for record."""
        self.cmd_record(*args)

    def cmd_p(self, *args: str):
        """Alias for play."""
        self.cmd_play(*args)


# -------------------------------------------------------------------- MAIN
if __name__ == "__main__":
    terminal = PiperTerminal()
    terminal.repl()
