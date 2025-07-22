#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""go_to_zero.py – перевод манипулятора Piper в «нулевую» заводскую позу.

Скрипт делает следующее:
1. Подключается к указанной CAN-шине (по умолчанию can0).
2. Включает сервоприводы, переключает руку в режим CAN + MOVE J с 10 % скоростью.
3. Отправляет JointCtrl(0,0,0,0,0,0) и обнуляет захват (GripperCtrl).
4. Циклически опрашивает фактические углы суставов до достижения порога точности.
5. По завершении переводит руку в standby, опционально отключает моторы и CAN.

Запускайте несколько раз подряд без перезапуска робота – скрипт повторно
подключится и снова выполнит перемещение.
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import List

from demo.V2.settings import CAN_NAME
from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = CAN_NAME
# Разница, при которой считаем, что целевая позиция достигнута (0.1° в единицах SDK)
THRESHOLD = 50  # 100 * 0.001° = 0.1°
LOG_PERIOD = 0.2  # сек

# Целевая нулевая поза – 6 суставов + захват
ZERO_POSE: List[int] = [0, 0, 0, 0, 0, 0, 0]


def go_to_zero(can_name: str = DEFAULT_CAN, hold: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    logging.info("Connecting to CAN '%s'…", can_name)
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)
    time.sleep(0.5)

    logging.info("Enabling motors…")
    arm.EnableArm(7)
    time.sleep(0.5)

    logging.info("Switching to CAN MOVE J mode with 10 %% speed…")
    arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=10, is_mit_mode=0x00)
    time.sleep(0.5)

    # --- отправляем целевое положение ----------------------------------
    logging.info("Sending ZERO JointCtrl / GripperCtrl …")
    arm.JointCtrl(*ZERO_POSE[:6])
    arm.GripperCtrl(ZERO_POSE[6], 1000, 0x01, 0)

    # --- цикл ожидания --------------------------------------------------
    logging.info("Monitoring convergence … threshold=%d (0.001°)", THRESHOLD)
    try:
        while True:
            js = arm.GetArmJointMsgs().joint_state
            current = [
                js.joint_1,
                js.joint_2,
                js.joint_3,
                js.joint_4,
                js.joint_5,
                js.joint_6,
            ]
            max_diff = max(abs(a - b) for a, b in zip(current, ZERO_POSE[:6]))
            logging.info("current=%s  target=%s  diff_max=%d", current, ZERO_POSE[:6], max_diff)
            if max_diff <= THRESHOLD:
                logging.info("ZERO pose reached (diff %d <= %d)", max_diff, THRESHOLD)
                break
            time.sleep(LOG_PERIOD)
    except KeyboardInterrupt:
        logging.warning("Interrupted by user. Stopping movement …")
    finally:
        if hold:
            logging.info("Holding ZERO pose – motors remain enabled. Press Ctrl+C to release …")
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                logging.info("Release requested – disabling motors …")

        logging.info("Switching to hold-mode and disconnecting …")
        # Держим сервы включёнными (ctrl_mode=0x01, move_mode=0x00)
        try:
            arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x00)
        except Exception:
            logging.debug("ModeCtrl set failed (already disconnected?)", exc_info=True)

        # Не отключаем Enable – иначе рука упадёт.
        arm.DisconnectPort()
        logging.info("Done.")


def main() -> None:
    pa = argparse.ArgumentParser(description="Move Piper arm to factory ZERO pose")
    pa.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    pa.add_argument("--hold", action="store_true", help="Не отключать моторы после достижения позы – удерживать ZERO")
    args = pa.parse_args()

    go_to_zero(args.can, hold=args.hold)


if __name__ == "__main__":
    main() 