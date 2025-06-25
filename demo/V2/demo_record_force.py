#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_record_force.py – демонстрация силовой податливости (admittance control).

Цель
-----
Рука удерживает текущее положение (MIT-контроль). Если на сустав
прикладывается внешняя сила/момент, контроллер «уступает»: опорный угол
постепенно смещается, позволяя звену плавно перемещаться.

Базовая идея
------------
1. Онлайн считываем крутящий момент каждого двигателя через сообщение
   High-Speed Feedback (`ArmHighSpdFeedback.effort`, 0.001 N·m).
2. Для каждого сустава держим *опорный* угол `ref_rad` (рад).
3. Если |τ| > τ_thr (порог), увеличиваем `ref_rad` на Δp, пропорциональный
   моменту:  Δp = gain * (τ − sgn(τ)*τ_thr) * dt.
   Таким образом «мягкость» регулируется параметром *gain* – чем он больше,
   тем легче рука поддаётся.
4. Пакет `JointMitCtrl` отправляется каждую итерацию с текущими `ref_rad` и
   умеренными Kp/Kd → сохраняется удержание без дрейфа.

Запуск:
    python demo_record_force.py  out.json  [--hz 100] [--kp 40] [--kd 1.0] \
                                 [--tau-thr 0.3] [--gain 0.3] [--can can0]

Файл JSON формируется так же, как в других демо – список точек
(шесть углов в 0.001°) для возможного последующего анализа.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import List, Tuple

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

# ---------------------------------------------------------------------------
# Неблокирующее нажатие «s» для остановки (повторяет код из других демо)
# ---------------------------------------------------------------------------
import time
start=time.time()

def _stop_pressed() -> bool:  # noqa: D401
    return time.time() - start > 10

# ---------------------------------------------------------------------------

DEFAULT_CAN = "can0"
DEFAULT_HZ = 100
DEFAULT_KP = 40.0  # чуть жестче, чтобы держать
DEFAULT_KD = 1.0
DEFAULT_TAU_THR = 0.3  # Н·м
DEFAULT_GAIN = 0.3     # рад/(Н·м·c)
DEFAULT_DURATION = 20.0  # секунд записи


# --- Вспомогательные преобразования ----------------------------------------

def deg001_list(js) -> List[int]:
    """Возвращает список углов (0.001°) из ArmJointFeedBack объекта."""
    return [
        js.joint_1,
        js.joint_2,
        js.joint_3,
        js.joint_4,
        js.joint_5,
        js.joint_6,
    ]


def rad_list_from_deg001(lst: List[int]) -> List[float]:
    return [x / 1000 * math.pi / 180 for x in lst]


def torque_list(hs) -> List[float]:
    """Считывает крутящий момент (Н·m) из HighSpdFeedback."""
    return [
        hs.motor_1.effort / 1000,
        hs.motor_2.effort / 1000,
        hs.motor_3.effort / 1000,
        hs.motor_4.effort / 1000,
        hs.motor_5.effort / 1000,
        hs.motor_6.effort / 1000,
    ]


# --- Основной цикл ---------------------------------------------------------

def record_force(
    json_path: Path,
    hz: int,
    kp: float,
    kd: float,
    tau_thr: float,
    gain: float,
    can_name: str,
) -> None:
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Включаем все двигатели и ждём, чтобы драйверы перешли в ON
    arm.EnableArm(7)
    time.sleep(0.5)

    # MIT-режим (`move_mode=0x04` – MOVE M, но SDK и с 0x01/J тоже работает)
    arm.MotionCtrl_2(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=0, is_mit_mode=0xAD)

    period = 1.0 / hz
    first = True
    ref_rad: List[float] = [0.0] * 6
    data: List[List[int]] = []

    print(
        f"Запись в режиме силовой податливости: {DEFAULT_DURATION} с…\n"
        "Прилагайте усилие к звеньям."
    )
    start_time = time.time()
    try:
        while time.time() - start_time < DEFAULT_DURATION:
            js = arm.GetArmJointMsgs().joint_state
            hs = arm.GetArmHighSpdInfoMsgs()

            cur_deg001 = deg001_list(js)
            cur_rad = rad_list_from_deg001(cur_deg001)
            tau_nm = torque_list(hs)

            if first:
                ref_rad = cur_rad.copy()
                first = False

            # --- admittance -------------------------------------------------
            for i in range(6):
                tau = tau_nm[i]
                if abs(tau) > tau_thr:
                    # дельта позиции ~ (τ-τ_thr) * gain * dt
                    delta = (tau - math.copysign(tau_thr, tau)) * gain * period
                    ref_rad[i] += delta

            # --- отправляем команды ----------------------------------------
            for idx, p in enumerate(ref_rad, start=1):
                arm.JointMitCtrl(idx, p, 0.0, kp, kd, 0.0)

            data.append(cur_deg001)
            time.sleep(period)
    except KeyboardInterrupt:
        print("KeyboardInterrupt – завершаю…")
    finally:
        arm.MotionCtrl_2(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=0, is_mit_mode=0x00)
        arm.DisconnectPort()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Лог траектории ({len(data)} точек) сохранён в {json_path}")


# --- CLI -------------------------------------------------------------------

def main() -> None:
    global DEFAULT_DURATION

    p = argparse.ArgumentParser(description="Force-compliant MIT demo (admittance)")
    p.add_argument("json", type=Path, nargs="?", default=Path("out.json"), help="Путь к JSON (default: out.json)")
    p.add_argument("--hz", type=int, default=DEFAULT_HZ, help="Частота цикла, Гц")
    p.add_argument("--kp", type=float, default=DEFAULT_KP, help="Kp (жёсткость удержания)")
    p.add_argument("--kd", type=float, default=DEFAULT_KD, help="Kd (демпфирование)")
    p.add_argument("--tau-thr", type=float, default=DEFAULT_TAU_THR, help="Порог момента, Н·м")
    p.add_argument("--gain", type=float, default=DEFAULT_GAIN, help="Admittance gain, рад/(Н·м·c)")
    p.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс")
    p.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Время записи, сек")
    args = p.parse_args()

    # передаём длительность через глобальную константу для простоты
    DEFAULT_DURATION = args.duration
    record_force(args.json, args.hz, args.kp, args.kd, args.tau_thr, args.gain, args.can)


if __name__ == "__main__":
    main() 