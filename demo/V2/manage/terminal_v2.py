from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
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
from demo.V2.settings import CAN_LEFT, CAN_RIGHT
import logging
from demo.V2.manage.track import TrackBase, TrackV2, TrackPoint


# ------------------------------------------------------------------------------------
# Если одна из рук недоступна – будем хранить в атрибуте *None* (без лишних классов).
# ------------------------------------------------------------------------------------


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

# Заводская нулевая поза (6 суставов + захват) в единицах SDK (0.001° / 0.001 мм)
ZERO_POSE: List[int] = [0, 0, 0, 0, 0, 0, 0]

# ---------- Настройки ----------
DELAY_BETWEEN_TRACKS = 3  # секунд паузы между треками

# Значение суставов SDK измеряются в «0.001 °» (тысячных долей градуса).
# Поэтому 1 ° = 1000 единиц SDK.
# Будем считать «близко», если ошибка ≤ 3 °.
TOLERANCE_ANGLE_DEG = 5
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
    """
    Файл безопасного (zero) трека внутри SAFE_DIR.
    """
    return SAFE_DIR / f"zero_track_{name}.json"


def _zero_track_details_path(name: str) -> Path:
    """
    Файл деталей безопасного (zero) трека внутри SAFE_DIR.
    """
    return SAFE_DIR / f"zero_track_{name}.details.json"


def _list_zero_tracks() -> List[Path]:
    """
    Возвращает только основные файлы треков (без *.details.json).
    """
    return sorted(
        p for p in SAFE_DIR.glob("zero_track_*.json") if not p.name.endswith(".details.json")
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
        pp <left> <right>           – параллельное воспроизведение для двух рук
        check-0-pos                 – максимальная дельта от Zero-позиции
        check-0-track               – минимальная дельта до Zero-треков
        get_track_range <name>      – min/max значений суставов по треку

    При запуске доступные руки автоматически переходят в ZERO_POSE и удерживаются.
    Далее можно записывать/проигрывать треки.
    """

    # Track implementation to use by default (can be overridden in subclasses)
    track_cls = TrackV2

    def __init__(self) -> None:
        # Инициализируем каждую руку отдельно и не падаем, если одна из них недоступна.

        # Левая рука ------------------------------------------------------------------
        try:
            _left_candidate = SDK.get_instance(CAN_LEFT)
            try:
                _left_candidate.ConnectPort()
                self.left_arm = _left_candidate
                logging.info(f"LEFT ({CAN_LEFT}) port connected.")
                self._goto_zero(self.left_arm, "LEFT")
            except Exception as exc:
                logging.warning(f"LEFT ({CAN_LEFT}) connection failed: {exc}")
                self.left_arm = None
        except Exception as exc:
            logging.warning(f"LEFT ({CAN_LEFT}) initialisation failed: {exc}")
            self.left_arm = None

        # Правая рука (может быть временно выключена через settings) -----------------
        self.right_arm = None
        if CAN_RIGHT:
            try:
                _right_candidate = SDK.get_instance(CAN_RIGHT)
                try:
                    _right_candidate.ConnectPort()
                    self.right_arm = _right_candidate
                    logging.info(f"RIGHT ({CAN_RIGHT}) port connected.")
                    self._goto_zero(self.right_arm, "RIGHT")
                except Exception as exc:
                    logging.warning(f"RIGHT ({CAN_RIGHT}) connection failed: {exc}")
                    self.right_arm = None
            except Exception as exc:
                logging.warning(f"RIGHT ({CAN_RIGHT}) initialisation failed: {exc}")
                self.right_arm = None

        # Запись
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_stop = threading.Event()
        # Воспроизведение
        self._play_thread: Optional[threading.Thread] = None
        self._play_stop = threading.Event()
        self._play_stop.set()  # not playing initially

        # Optional callback invoked for each point sent during playback.
        # Signature: hook(pt: List[int]) where pt is 7-length list (deg001 units)
        self._point_hook = None  # type: Optional[Callable[[List[int]], None]]

    def __dangerous_reset(self, arm, can_name):
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

        time.sleep(1)  # даём контроллеру перезапуститься

        arm = SDK.get_instance(can_name)  # важно пересоздать руку (я хз почему)
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
    def _maybe_reset_from_safe_pose_and_move_to_0(self, arm, can_name) -> PiperResponse:
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
        best_delta = math.inf
        best_track_path: Optional[Path] = None
        best_pt: Optional[List[int]] = None
        best_worst_joint: Optional[int] = None

        for p in z_tracks:
            try:
                data = json.loads(p.read_text())
            except Exception as exc:
                logging.exception(f'fail: {exc}')
                continue
            for pt in data:
                delta, worst_joint = self._max_delta_and_joint_ignored(curr, pt)
                if delta < best_delta:
                    best_delta = delta
                    best_track_path = p
                    best_pt = pt
                    best_worst_joint = worst_joint

        if best_delta > TOLERANCE_ANGLE_UNITS:
            logging.error(
                "[UNSAFE] далеко от safe-track | "
                f"closest Δ={best_delta} units (~{best_delta/1000:.3f}°), "
                f"track={best_track_path.name if best_track_path else 'n/a'}, "
                f"worst joint #{best_worst_joint}"
            )
            return PiperResponse(ok=False, error='far from 0 tracks')

        # Found safe proximity
        logging.info(
            f"[SAFE] Ближайший safe-track: {best_track_path.name if best_track_path else 'n/a'} | "
            f"Δ={best_delta} units (~{best_delta/1000:.3f}°) | worst joint #{best_worst_joint} | point {best_pt}"
        )

        logging.info("[SAFE] близко к safe-track, СБРОС")
        self.__dangerous_reset(arm, can_name)
        self.__dangerous_reset(arm, can_name)
        # эту штуку важно вызвать два раза иначе рука не напряжется (мне пока лень разбираться почему)

        # todo это не надо!
        # logging.info("[SAFE] едем в 0-pos")
        # zero_pos = json.loads(ZERO_POS_PATH.read_text())
        # self._move_smooth(arm, zero_pos)

        # if not self.cmd_check_0_pos():
        #     logging.error(f'[ERROR] мы не приехали в 0 pos')
        #     return PiperResponse(
        #         ok=False,
        #         error='not in 0 pos'
        #     )
        # else:
        #     logging.info("[SAFE] приехали в 0-pos")
        #     return PiperResponse(
        #         ok=True,
        #     )

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
        for tp in data:
            for i, val in enumerate(tp.coordinates):
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

    # Удалённые команды r-0-pos / r-0-track больше не доступны.

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
        data: List[List[int]] = []  # points only
        details: List[dict] = []    # telemetry with ts (first field is ts)
        _acq_times: List[float] = []  # seconds
        zero_start: Optional[float] = None
        zero_warned_at = time.time()
        try:
            while not self._rec_stop.is_set():
                _acq_start = time.perf_counter()
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
                    elif time.time() - zero_start > 1:
                        if time.time() - zero_warned_at > 1:
                            logging.error("[REC] Получаем нулевые данные >1s – проверьте соединение.")
                            zero_warned_at = time.time()
                    time.sleep(period)
                    continue
                else:
                    zero_start = None
                    zero_warned_at = time.time()

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
                _acq_end = time.perf_counter()
                _acq_times.append(_acq_end - _acq_start)
                time.sleep(period)
        finally:
            self._finalize_record(arm)
            # Transform to (pt, ts) tuples expected by write_from_record
            points_ts = [
                (pt, d["ts"]) for pt, d in zip(data, details)
            ]
            # Report acquisition timing statistics
            if _acq_times:
                times_ms = [t * 1000 for t in _acq_times]
                times_sorted = sorted(times_ms)
                n = len(times_sorted)
                p10 = times_sorted[int(n * 0.1)]
                p90 = times_sorted[int(n * 0.9)-1]
                logging.info(
                    f"[REC-TIMING] samples={n}  min={min(times_ms):.2f} ms  p10={p10:.2f} ms  avg={sum(times_ms)/n:.2f} ms  p90={p90:.2f} ms  max={max(times_ms):.2f} ms"
                )

            # Persist using the configured track_cls
            self.track_cls.write_from_record(full_name, points_ts, details)
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
        # Переключаемся в MOVE J для перемещения
        logging.info("ModeCtrl: ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=20")
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=20)

        # --- Возвращаем руку в ZERO_POSE -----------------------------------
        try:
            logging.info("[REC] Moving arm to ZERO_POSE after recording …")
            self._move_smooth(arm, ZERO_POSE, steps=120, hz=60)
        except Exception as exc:
            logging.warning(f"[REC] Failed to move to ZERO_POSE: {exc}")

        # Снова удерживаем
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00, move_spd_rate_ctrl=50)

    # --------------------------------- play -------------------------------------------------------------
    def cmd_play(self, *tracks: str):
        # --- Setup stop flags & thread info ---
        if not tracks:
            logging.info("play: требуется >=1 трек")
            return
        self._play_stop.clear()
        # Remember the thread that executes playback so we can join later
        self._play_thread = threading.current_thread()

        # for prev, curr in zip(tracks, tracks[1:]):
        #     if not curr.startswith(prev + "__"):
        #         logging.info(f"Ошибка порядка: '{curr}' не является потомком '{prev}'.")
        #         return

        # Проверка безопасности перед reset-ом
        arm0 = self._arm_from_name(tracks[0])
        arm0_can_name = self._arm_can_from_name(tracks[0])
        result = self._maybe_reset_from_safe_pose_and_move_to_0(arm0, arm0_can_name)
        if not result.ok:
            logging.error(f'bad status: {result}')
            return

        # --- Переход в ZERO_POSE перед началом воспроизведения -------------
        if not self._is_close_ignored(self._current_point(arm0), ZERO_POSE):
            logging.info("[PLAY] Перемещаю робот в ZERO позу перед воспроизведением…")
            self._move_smooth(arm0, ZERO_POSE)

        # Теперь проверка стартовой позиции трека
        first_track_start = self._load(tracks[0])[0].coordinates
        if not self._is_close_ignored(self._current_point(arm0), first_track_start):
            logging.info("[INFO] Перемещаю робота в начало трека…")
            if not self._safe_move_smooth(arm0, first_track_start):
                logging.error("[PLAY] Движение к стартовой точке отменено из соображений безопасности.")
                return
            time.sleep(0.2)

        for i, full_name in enumerate(tracks):
            if self._play_stop.is_set():
                logging.info("[PLAY] Стоп запрошен – прерываем воспроизведение после трека.")
                break

            data = self._load(full_name)
            arm = self._arm_from_name(full_name)
            logging.info(f"[PLAY] {full_name} ({len(data)} pts)…")
            self._run_track(arm, data)

            if self._play_stop.is_set():
                logging.info("[PLAY] Стоп запрошен – останавливаем дальнейшие треки.")
                break

            if i < len(tracks) - 1:
                logging.info(f"…пауза {DELAY_BETWEEN_TRACKS} c…")
                # Если во время паузы поступил запрос на остановку – уходим сразу
                for _ in range(DELAY_BETWEEN_TRACKS * 10):
                    if self._play_stop.is_set():
                        break
                    time.sleep(0.1)
                if self._play_stop.is_set():
                    logging.info("[PLAY] Стоп запрошен во время паузы – прерываем.")
                    break

        logging.info("✓ Воспроизведение завершено.")
        self._play_thread = None
        self._play_stop.set()

    # --------------------------------- play_parallel ----------------------------------------------------
    def cmd_play_parallel(self, left_track: str = "", right_track: str = ""):
        """Воспроизвести два трека параллельно – один для левой, другой для правой руки.

        usage: pp <left_track> <right_track>
        """
        if not left_track or not right_track:
            logging.info("pp: требуется 2 трека – левый и правый")
            return

        tracks = [left_track, right_track]

        # Базовая валидация имён треков
        for t in tracks:
            if not (t.startswith("left__") or t.startswith("right__")):
                logging.error(f"[PP] Неверное имя трека '{t}'. Должно начинаться с 'left__' или 'right__'.")
                return

        # Проверяем, что передан ровно один трек для каждой руки
        if (left_track.startswith("left__") and right_track.startswith("left__")) or (
            left_track.startswith("right__") and right_track.startswith("right__")
        ):
            logging.error("[PP] Нужен один трек для левой и один для правой руки – проверьте порядок аргументов.")
            return

        # Предполетные проверки: сбросы и движение в 0 позу для каждой руки (по очереди)
        for full_name in tracks:
            arm = self._arm_from_name(full_name)
            can_name = self._arm_can_from_name(full_name)
            result = self._maybe_reset_from_safe_pose_and_move_to_0(arm, can_name)
            if not result.ok:
                logging.error(f"[PP] Предусловия безопасности не выполнены для {full_name}: {result.error}")
                return

        # --- Переход в ZERO_POSE перед параллельным воспроизведением -------
        for full_name in tracks:
            arm = self._arm_from_name(full_name)
            if not self._is_close_ignored(self._current_point(arm), ZERO_POSE):
                logging.info(f"[PP] Перемещаю {'левую' if arm is self.left_arm else 'правую'} руку в ZERO позу…")
                self._move_smooth(arm, ZERO_POSE)

        # При необходимости доводим каждую руку до стартовой точки
        for full_name in tracks:
            arm = self._arm_from_name(full_name)
            first_pt = self._load(full_name)[0]
            if not self._is_close_ignored(self._current_point(arm), first_pt):
                logging.info(
                    f"[PP] Перемещаю {'левую' if arm is self.left_arm else 'правую'} руку в начало трека…"
                )
                if not self._safe_move_smooth(arm, first_pt):
                    logging.error("[PP] Движение к стартовой точке отменено (небезопасно).")
                    return
                time.sleep(0.2)

        # Внутренний воркер для исполнения одного трека
        def _play_worker(full_name: str):
            data = self._load(full_name)
            details = self._load_details(full_name)
            arm = self._arm_from_name(full_name)
            logging.info(f"[PLAY→] {full_name} ({len(data)} pts)…")
            self._run_track(arm, data, details)

        # Запускаем оба воспроизведения параллельно
        t_left = threading.Thread(target=_play_worker, args=(left_track,), daemon=True)
        t_right = threading.Thread(target=_play_worker, args=(right_track,), daemon=True)
        t_left.start()
        t_right.start()
        t_left.join()
        t_right.join()

        logging.info("✓ Параллельное воспроизведение завершено.")

    # --------------------------------- low-level helpers -----------------------------------------------
    def _arm_can_from_name(self, full_name: str):
        if full_name.startswith("left__"):
            return CAN_LEFT
        if full_name.startswith("right__"):
            return CAN_RIGHT
        raise ValueError("Имя должно начинаться с left__ или right__")

    def _arm_from_name(self, full_name: str):
        if full_name.startswith("left__"):
            if self.left_arm is None:
                raise RuntimeError("Left arm is not initialised/connected.")
            return self.left_arm
        if full_name.startswith("right__"):
            if self.right_arm is None:
                raise RuntimeError("Right arm is not initialised/connected.")
            return self.right_arm
        raise ValueError("Имя должно начинаться с left__ или right__")

    def _send_point(self, arm, pt):
        eff_pt = self._effective_target(pt)
        arm.JointCtrl(*eff_pt[:6])
        arm.GripperCtrl(eff_pt[6], GRIPPER_EFFORT, 0x01, 0)

        # Notify visualizer if hook set
        if self._point_hook is not None:
            try:
                self._point_hook(pt)
            except Exception:
                # Do not let GUI errors break control loop
                logging.debug("point_hook raised", exc_info=True)

    def _prepare_track_play(self, arm):
        """Один раз перед отправкой траектории настраиваем режим."""
        arm.EnableArm(7)
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=50)
        time.sleep(0.02)

    def _run_track(self, arm, data: List[TrackPoint], details=None, hz: int = 50):
        """Play the given trajectory with accuracy gating.

        The next point will not be issued until the arm is within 0.2° (≈200 units)
        of the previous one. A command is resent every 20 ms until that happens.
        If 60 ms pass without success, a warning is emitted on every subsequent
        resend.
        """
        if details is None:
            details = []
        use_timestamps = True  # always rely on coordinates_timestamp

        logging.info("ModeCtrl: ctrl_mode=0x01, move_mode=0x01   (start track)")
        self._prepare_track_play(arm)
        total_pts = len(data)
        last_pct = -10

        started_at = time.time() if use_timestamps else None
        first_ts: float = data[0].coordinates_timestamp if use_timestamps else 0.0

        for idx, tp in enumerate(data):
            if self._play_stop.is_set():
                logging.info("[PLAY] Стоп запрошен – прерываем трек.")
                break

            # Synchronize with original timing (best-effort) before gating
            if use_timestamps:
                target_offset = tp.coordinates_timestamp - first_ts
                while True:
                    run_time = time.time() - (started_at or 0.0)
                    if run_time >= target_offset or self._play_stop.is_set():
                        break
                    time.sleep(0.001)

            self._send_point(arm, tp.coordinates)

            # # -------------------- accuracy gating --------------------
            # first_send_ts = time.time()
            # warned = False
            # last_warn_ts = first_send_ts
            #
            # warning_after = 0.06
            # while True:
            #     now = time.time()
            #
            #     # Check convergence
            #     target_pos = self._effective_target(tp.coordinates)
            #     if self._is_close_strict(
            #             self._current_point(arm),
            #             target_pos,
            #             tol=100,
            #             gripper_tol=1000,  # very stupid
            #     ):
            #         break
            #
            #     # Issue warnings
            #     if now - first_send_ts >= warning_after:
            #         if (not warned) or (now - last_warn_ts >= 1.0):
            #             curr_pos = self._current_point(arm)
            #             target_pos = self._effective_target(tp.coordinates)
            #             deltas = [abs(a - b) for a, b in zip(curr_pos, target_pos)]
            #             max_delta = max(deltas)
            #             worst_joint = deltas.index(max_delta)
            #
            #             logging.warning(
            #                 f"[PLAY] Point {idx}: arm not in position Δmax={max_delta} units (~{max_delta/1000:.3f}°) worst joint #{worst_joint}"
            #             )
            #             logging.warning(f"  current={curr_pos}")
            #             logging.warning(f"  target={target_pos}")
            #             logging.warning(f"  deltas={deltas}")
            #             warned = True
            #             last_warn_ts = now
            #
            #     if self._play_stop.is_set():
            #         break
            #     time.sleep(0.002)  # small sleep to avoid busy-loop

            # # выводим погрешность между целевой точкой и фактической позой
            # if idx % step_log == 0:  # примерно 1% шаг
            #     feedback = self._current_point(arm)
            #     delta = [abs(a - b) for a, b in zip(feedback, pt)]
            #     logging.info(f"[DELTA] {delta}")

            pct = int((idx + 1) * 100 / total_pts)
            if pct // 10 > last_pct // 10:
                last_pct = pct
                logging.info(f"[PLAY] progress {pct}% ({idx+1}/{total_pts})")

        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
        if self._play_stop.is_set():
            logging.info("[PLAY] Трек остановлен досрочно.")
        logging.info("ModeCtrl: ctrl_mode=0x00, move_mode=0x00   (end track)")

    # --------------------------------- geometry helpers ------------------------------------------------
    def _current_point(self, arm):
        """Return current joint/gripper angles.

        Sometimes immediately after reconnect the device can report all-zero
        values for a short period. We poll for up to 100 ms waiting for any
        non-zero reading. If the timeout is reached – a warning is emitted and
        the last (still zero) reading is returned so that callers can decide
        what to do next.
        """
        deadline = time.perf_counter() + 0.1  # 100 ms
        warned_at = time.time()
        while True:
            js = arm.GetArmJointMsgs().joint_state
            gr = arm.GetArmGripperMsgs().gripper_state
            pt = [
                js.joint_1,
                js.joint_2,
                js.joint_3,
                js.joint_4,
                js.joint_5,
                js.joint_6,
                gr.grippers_angle,
            ]

            if any(v != 0 for v in pt):
                return pt

            if time.perf_counter() >= deadline:
                if time.time() - warned_at > 0.1:
                    logging.warning("[DATA] No valid joint data for >100 ms (all zeros)")
                    warned_at = time.time()

            time.sleep(0.005)  # small back-off to avoid busy-loop

    @staticmethod
    def _is_close_strict(
            pt_a,
            pt_b,
            tol=TOLERANCE_ANGLE_UNITS,
            gripper_tol=None
    ):
        """Сравнение без исключений суставов (строгий режим)."""
        motors_a = pt_a[:-1]
        gripper_a = pt_a[-1]
        motors_b = pt_b[:-1]
        gripper_b = pt_b[-1]
        motors_flag = all(abs(a - b) <= tol for a, b in zip(motors_a, motors_b))
        if gripper_tol is None:
            gripper_tol = tol
        gripper_flag = abs(gripper_a - gripper_b) <= gripper_tol
        return motors_flag and gripper_flag

    @staticmethod
    def _is_close_ignored(pt_a, pt_b, tol=TOLERANCE_ANGLE_UNITS):
        """Сравнение с игнорированием IGNORED_JOINTS."""
        return PiperTerminal._max_delta_and_joint_ignored(pt_a, pt_b)[0] <= tol

    @staticmethod
    def _load(full_name: str) -> List[TrackPoint]:
        """Load trajectory as list of TrackPoint objects."""
        return TrackBase.read_track(full_name).track_points

    # --- New helper: load *.details.json for a track (may be absent) --------------
    @staticmethod
    def _load_details(full_name: str):
        """Return associated *.details.json contents or empty list if missing."""
        path = _details_path(full_name)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception as exc:  # noqa: BLE001
                logging.warning(f"Failed to load details for '{full_name}': {exc}")
        return []

    # ---------------------------- Public API (GUI helpers) ----------------------------
    def list_tracks(self) -> List[str]:
        """Return a sorted list of available track names (without extension)."""
        return sorted(
            p.stem for p in TRACK_DIR.glob("*.json") if not p.name.endswith(".details.json")
        )

    def start_record(self, full_name: str):
        """Begin recording a new track with *full_name* (e.g. 'left__my_move')."""
        self.cmd_record(full_name)

    def stop_record(self):
        """Stop the current recording session (if any)."""
        self.cmd_s()

    def play_tracks(self, *tracks: str):
        """Play one or more tracks sequentially (blocking call).

        Stores the playing thread reference so that `stop_play()` can join it from outside.
        """
        try:
            self.cmd_play(*tracks)
        finally:
            # Ensure flags reset even on exception
            self._play_thread = None
            self._play_stop.set()

    # -------------------------------- status helpers ---------------------------------
    def is_recording(self) -> bool:
        """Return True if a recording thread is currently active."""
        return self._rec_thread is not None and self._rec_thread.is_alive()

    def is_playing(self) -> bool:
        """Return True if a playing thread is currently active."""
        return self._play_thread is not None and self._play_thread.is_alive()

    def stop_play(self):
        """Stop the current playing session (if any)."""
        self._play_stop.set()
        # Join from a different thread only
        if self._play_thread and self._play_thread is not threading.current_thread():
            self._play_thread.join()
        self._play_thread = None
        logging.info("✓ Воспроизведение остановлено.")

    # -------------------------------- cleanup ----------------------------------------
    def shutdown(self):
        """Cleanup resources (disconnect CAN) – call when GUI exits."""
        for arm in (self.left_arm, self.right_arm):
            if arm is None:
                continue
            try:
                arm.DisconnectPort()
            except Exception:
                pass

    # -------------------------------- REPL loop -------------------------------------
    def repl(self):
        logging.info(
            "Piper terminal v2. help – список команд. Ctrl+D/Ctrl+C – выход."
        )
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
            attr = f"cmd_{cmd.replace('-', '_')}"
            try:
                getattr(self, attr)(*args)  # type: ignore[attr-defined]
            except AttributeError:
                if cmd == "help":
                    logging.info(self.__doc__)
                else:
                    logging.warning(f"Неизвестная команда: {cmd}")
            except Exception:
                logging.exception("[EXCEPTION] Unhandled error")
        # disconnect
        self.shutdown()

    # -------------------------------- aliases ---------------------------------------
    def cmd_r(self, *args: str):
        """Alias for record."""
        self.cmd_record(*args)

    def cmd_p(self, *args: str):
        """Alias for play."""
        self.cmd_play(*args)

    def cmd_pp(self, *args: str):
        """Alias for play_parallel."""
        self.cmd_play_parallel(*args)

    # ----------------------- hook / utility helpers ---------------------------------
    def set_point_hook(self, func):
        """Register a callback called on every _send_point during playback."""
        self._point_hook = func

    @staticmethod
    def _effective_target(pt: List[int]) -> List[int]:
        """Return a copy of pt with tightening applied to gripper (index 6)."""
        eff = list(pt)
        if GRIPPER_TIGHT_COEFFICEINT > 0:
            eff[6] = int(eff[6] * (1 - GRIPPER_TIGHT_COEFFICEINT))
        return eff

    # ------------------------ startup zero helper -----------------------------------
    def _goto_zero(self, arm, label: str = "ARM") -> None:
        """Enable *arm* and move it to ZERO_POSE, then switch to hold-mode."""
        try:
            arm.EnableArm(7)
            time.sleep(0.5)
            arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=10, is_mit_mode=0x00)
            time.sleep(0.5)
            arm.JointCtrl(*ZERO_POSE[:6])
            arm.GripperCtrl(ZERO_POSE[6], 1000, 0x01, 0)
            while True:
                js = arm.GetArmJointMsgs().joint_state
                curr = [js.joint_1, js.joint_2, js.joint_3, js.joint_4, js.joint_5, js.joint_6]
                if max(abs(a - b) for a, b in zip(curr, ZERO_POSE[:6])) <= 50:
                    break
                time.sleep(0.1)
            arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00)
            logging.info(f"[INIT] {label} moved to ZERO pose and holding.")
        except Exception as exc:
            logging.warning(f"[INIT] Failed to move {label} to ZERO pose: {exc}")


# -------------------------------------------------------------------- MAIN
if __name__ == "__main__":
    terminal = PiperTerminal()
    terminal.repl()