#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_record_track_mit.py – запись траектории Piper в режиме MIT.

Сценарий работы:
1. python demo_record_track_mit.py out.json [--hz 100] [--kp 10] [--kd 0.8] [--can can0]
2. Скрипт переводит контроллер суставов в MIT-режим (MotionCtrl_2, is_mit_mode=0xAD).
3. Каждые 1/Hz секунд:
   • читается текущий угол каждого сустава;
   • сразу же отправляется JointMitCtrl с pos_ref = текущему углу.
     При невысоких Kp/Kd это даёт «мягкую» руку: её легко перемещать рукой,
     а отпустив – она удерживает именно то положение, где её оставили.
4. Для завершения записи нажмите «s» в терминале или Ctrl+C.
5. Скрипт выключит MIT (is_mit_mode=0x00), сохранит собранную траекторию
   (list[list[int, …]] углы в 0.001°) в указанный JSON-файл.

Почему MIT-режим «мягкий»
-------------------------
Контроллер в прошивке реализует PD-закон:
    τ = Kp·(p_ref − p) + Kd·(v_ref − v) + τ_ref
  – p, v  – текущие позиция и скорость;
  – p_ref, v_ref – ссылки, переданные JointMitCtrl;
  – τ_ref – дополнительный момент (здесь 0);
  – Kp, Kd – коэффициенты «жёсткости» и «вязкости».
Если мы каждую итерацию приравниваем p_ref к *текущей* позиции, ошибка (p_ref−p)
≈ 0, а значит τ≈0 ⇒ сустав свободен. Стоит переместить плечо вручную – новое p
сразу станет новым p_ref, и рука «застынет» в этом месте.

Параметры JointMitCtrl
----------------------
    pos_ref – рад, диапазон [−12.5, 12.5]
    vel_ref – рад/с, здесь 0 (стремимся стоять)
    kp       – 5…30  мягко,  >100 жёстко
    kd       – 0.5…2.0 демпфирование
    t_ref    – Н·м, здесь 0 (гравитацию компенсируем руками)

"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import List

from piper_sdk.interface import C_PiperInterface_V2 as SDK

# ---------------------------------------------------------------------------
# Кроссплатформенное чтение одиночного символа без блокировки (копия из оригинала)
# ---------------------------------------------------------------------------
try:
    import msvcrt  # Windows-способ

    def _stop_pressed() -> bool:  # noqa: D401
        """True, если пользователь нажал «s»/«S» без Enter (Windows)."""
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            return ch.lower() == b"s"
        return False
except ImportError:  # POSIX
    import select
    import termios
    import tty

    _orig_attrs = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin)

    def _stop_pressed() -> bool:  # noqa: D401
        """True, если в stdin появился символ «s»/«S» (POSIX)."""
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:
            ch = sys.stdin.read(1)
            return ch.lower() == "s"
        return False

    import atexit

    @atexit.register
    def _restore_tty():
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _orig_attrs)

# ---------------------------------------------------------------------------

DEFAULT_CAN = "can0"
DEFAULT_KP = 10.0
DEFAULT_KD = 0.8


def record(json_path: Path, hz: int, kp: float, kd: float, can_name: str) -> None:
    """Основная процедура записи траектории с MIT-контролем."""
    arm = SDK.get_instance(can_name)
    # Подключаемся (без re-init CAN)
    arm.ConnectPort(can_init=False)

    # Переключаем контроллер в MIT-режим
    arm.MotionCtrl_2(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=0,
                     is_mit_mode=0xAD)

    period = 1.0 / hz
    data: List[List[int]] = []

    print(
        "MIT-режим активирован. Перемещайте руку (она податлива).\n"
        "Нажмите 's' для остановки или Ctrl+C."
    )
    try:
        while True:
            # 1) Читаем текущие суставные углы (0.001°)
            js = arm.GetArmJointMsgs().joint_state
            joints_deg_001 = [
                js.joint_1,
                js.joint_2,
                js.joint_3,
                js.joint_4,
                js.joint_5,
                js.joint_6,
            ]
            # 2) Конвертируем в радианы для MIT-команды
            joints_rad = [x / 1000 * math.pi / 180 for x in joints_deg_001]

            # 3) Отправляем JointMitCtrl для каждого привода
            for i, p in enumerate(joints_rad, start=1):
                arm.JointMitCtrl(
                    motor_num=i,
                    pos_ref=p,
                    vel_ref=0.0,
                    kp=kp,
                    kd=kd,
                    t_ref=0.0,
                )

            # 4) Логируем точку (в градусах*1000 — как в исходном демо)
            data.append(joints_deg_001)

            # 5) Пауза до следующего цикла
            time.sleep(period)

            if _stop_pressed():
                print("Команда остановки получена – завершаю запись…")
                break
    except KeyboardInterrupt:
        print("KeyboardInterrupt – завершаю запись…")
    finally:
        # Выключаем MIT-режим, возвращаемся к обычному pos-spd контролю
        arm.MotionCtrl_2(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=0,
                         is_mit_mode=0x00)
        arm.DisconnectPort()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Сохранено {len(data)} точек в {json_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Record Piper trajectory in MIT mode")
    p.add_argument("json", type=Path, help="Путь, куда сохранить файл траектории")
    p.add_argument("--hz", type=int, default=100, help="Частота цикла, Гц (MIT требует ≥50)")
    p.add_argument("--kp", type=float, default=DEFAULT_KP, help="Коэффициент Kp (жёсткость)")
    p.add_argument("--kd", type=float, default=DEFAULT_KD, help="Коэффициент Kd (демпфирование)")
    p.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = p.parse_args()

    record(args.json, args.hz, args.kp, args.kd, args.can)


if __name__ == "__main__":
    main() 