#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_play_track.py – воспроизведение ранее записанной траектории с Piper SDK.

Скрипт:
1. Загружает список точек из JSON (см. demo_record_track.py).
2. Переводит манипулятор в режим управления по суставам (ModeCtrl: ctrl_mode=0x01, move_mode=0x01).
3. Последовательно отправляет JointCtrl (+ при наличии GripperCtrl) для каждой точки.
4. По завершении возвращается в standby (моторы остаются под питанием) и отключает CAN.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK
from demo.V2.settings import CAN_NAME


def play(can_name: str = CAN_NAME) -> None:
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)
    arm.ModeCtrl(0x01, 0x01, 50, 0x00)


def main() -> None:
    play()


if __name__ == "__main__":
    main()