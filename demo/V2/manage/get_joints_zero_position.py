#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""get_joints_zero_position.py — вывести текущие углы суставов (ожидаемые нули).

Используется для проверки после выполнения set_joints_zero_position.py.
"""
from __future__ import annotations

import argparse
import logging
import time

from demo.V2.settings import CAN_NAME, CAN_RIGHT, CAN_LEFT
from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = CAN_RIGHT


def _init_logger():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    _init_logger()
    pa = argparse.ArgumentParser(description="Показать текущие углы Piper (0.001°)")
    pa.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = pa.parse_args()

    arm = SDK.get_instance(args.can)
    logging.info("Connecting to %s", args.can)
    arm.ConnectPort(can_init=False)
    time.sleep(0.5)

    try:
        while True:

            js = arm.GetArmJointMsgs().joint_state
            angles = [js.joint_1, js.joint_2, js.joint_3, js.joint_4, js.joint_5, js.joint_6]
            logging.info("Current joint angles (0.001°): %s", angles)
            deg = [v / 1000.0 for v in angles]
            logging.info("Current joint angles (deg): %s", deg)
            logging.info('='*40)
            time.sleep(1)
    except KeyboardInterrupt:
        arm.DisconnectPort()


if __name__ == "__main__":
    main() 