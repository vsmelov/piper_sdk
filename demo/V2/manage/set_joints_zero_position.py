#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_joints_zero_position.py — установить текущие углы суставов как «нуль».

Алгоритм:
1. Подключаемся к роботу по CAN (по умолчанию can0).
2. Включаем все моторы и ждём стабилизации телеметрии.
3. Логируем текущие углы.y
4. Отправляем JointConfig с `joint_num = 7`y и `set_zero = 0xAE` — задаёт положение всех суставов как 0.
5. Повторно запрашиваем углы, выводим в лог до/после.
6. Переходим в standby и отключаемся.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

from demo.V2.settings import CAN_NAME, CAN_RIGHT, CAN_LEFT
from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = CAN_RIGHT
LOG_NAME = "set_zero.log"
THRESH = 200  # 0.2° допуск
WAIT_DISABLE_TIMEOUT = 5.0  # сек


def _init_logger() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    logging.basicConfig(level=logging.INFO,
                        format=fmt,
                        handlers=[
                            logging.FileHandler(LOG_NAME, encoding="utf-8"),
                            logging.StreamHandler()
                        ])


def _get_current_angles(arm: SDK):
    js = arm.GetArmJointMsgs().joint_state
    return [js.joint_1, js.joint_2, js.joint_3, js.joint_4, js.joint_5, js.joint_6]


def _get_enable_flags(arm: SDK) -> List[int]:
    ls = arm.GetArmLowSpdInfoMsgs()
    return [
        ls.motor_1.foc_status.driver_enable_status,
        ls.motor_2.foc_status.driver_enable_status,
        ls.motor_3.foc_status.driver_enable_status,
        ls.motor_4.foc_status.driver_enable_status,
        ls.motor_5.foc_status.driver_enable_status,
        ls.motor_6.foc_status.driver_enable_status,
    ]


def set_zero(can_name: str = DEFAULT_CAN):
    _init_logger()
    logging.info("Connecting to CAN '%s'…", can_name)
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Включаем моторы
    # arm.EnableArm(7)


    before = _get_current_angles(arm)
    logging.info("Current joint angles (0.001°): %s", before)

    # Проверяем питание драйверов
    enables_before = _get_enable_flags(arm)
    logging.info("Driver enable flags: %s (1 = enabled)", enables_before)

    # --- WARNING & USER CONFIRMATION ----------------------------------
    warning = (
        "\n\n⚠️⚠️⚠️  ВНИМАНИЕ!  ⚠️⚠️⚠️\n"
        "Позиция суставов будет записана как НУЛЕВАЯ.\n"
        "ПЕРЕД выполнением плавно переведите все суставы в требуемое нулевое положение.\n"
        "СЕЙЧАС МОТОРЫ БУДУТ ОТКЛЮЧЕНЫ, И РУКА МОЖЕТ СВОБОДНО ОПУСТИТЬСЯ!\n"
        "Убедитесь, что ничто не мешает безопасному опусканию.\n"
        "Чтобы продолжить, введите 'y' и нажмите Enter. Любой другой ввод отменит операцию.\n"
    )
    print(warning)
    resp = input("Продолжить? [y/N]: ").strip().lower()
    if resp != "y":
        logging.info("Отменено пользователем. Выходим без изменений.")
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
        arm.DisconnectPort()
        return

    # --- Отключаем драйверы и ждём фактического disable ----------------
    logging.info("Disabling all motors …")
    arm.DisableArm(7)

    t0 = time.time()
    while True:
        if all(flag == 0 for flag in _get_enable_flags(arm)):
            break
        if time.time() - t0 > WAIT_DISABLE_TIMEOUT:
            logging.warning("Some drivers are still enabled after %.1f s — продолжаю, но результат может быть неверным.", WAIT_DISABLE_TIMEOUT)
            break
        time.sleep(0.1)

    # --- Выбор режима ---------------------------------------------------
    mode = input("Установить ноль для (a) всех суставов или (s) последовательно? (индексы 0-5) [a/s]: ").strip().lower()

    def _set_joint(j:int):
        logging.info("Set zero (index %d)", j-1)
        arm.JointConfig(joint_num=j, set_zero=0xAE)  # type: ignore[arg-type]
        time.sleep(0.1)

    if mode == "a":
        # --- Все суставы сразу -----------------------------------------
        for joint in range(1, 7):
            _set_joint(joint)
        logging.info("Zero-set command sent to all joints.")
    elif mode == 's':
        # --- Режим по одному суставу -----------------------------------
        while True:
            inp = input("Введите индекс сустава 0-5 (или 'q' для выхода): ").strip().lower()
            if inp in ("q", "quit", "exit"):
                break
            if not inp.isdigit() or not (0 <= int(inp) <= 5):
                print("Неверный ввод. Введите 0-5 или 'q'.")
                continue
            _set_joint(int(inp) + 1)  # JointConfig использует диапазон 1-6
        logging.info("Завершён поочерёдный режим установки нулей.")
    else:
        raise ValueError('wrong')

    # ждём применения
    time.sleep(1.5)

    after = _get_current_angles(arm)
    logging.info("Joint angles after zero-set (0.001°): %s", after)
    logging.info("After in degrees: %s", [v/1000 for v in after])

    max_dev = max(abs(v) for v in after)
    if max_dev <= THRESH:
        logging.info("Zero-set SUCCESS, max deviation %d ≤ %d", max_dev, THRESH)
    else:
        logging.warning("Zero-set MAY HAVE FAILED, max deviation %d > %d", max_dev, THRESH)

    enables_after = _get_enable_flags(arm)
    logging.info("Driver enable flags after: %s", enables_after)

    # Переключаемся в standby и отключаемся
    # arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
    arm.DisconnectPort()
    logging.info("Done.")


def main() -> None:
    pa = argparse.ArgumentParser(description="Установить текущую позу Piper как нулевую")
    pa.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = pa.parse_args()

    set_zero(args.can)


if __name__ == "__main__":
    main() 