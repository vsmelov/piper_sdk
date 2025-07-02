#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK
from demo.V2.settings import CAN_NAME

DEFAULT_CAN = CAN_NAME


def show(can_name: str) -> None:
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    while True:
        # --- получаем актуальные сообщения от SDK -------------------
        hs = arm.GetArmHighSpdInfoMsgs()
        ls = arm.GetArmLowSpdInfoMsgs()

        motor_effort_mNm = [
            hs.motor_1.effort,
            hs.motor_2.effort,
            hs.motor_3.effort,
            hs.motor_4.effort,
            hs.motor_5.effort,
            hs.motor_6.effort,
        ]
        print(f'{motor_effort_mNm=}')
        foc_temp_c = [
            ls.motor_1.foc_temp,
            ls.motor_2.foc_temp,
            ls.motor_3.foc_temp,
            ls.motor_4.foc_temp,
            ls.motor_5.foc_temp,
            ls.motor_6.foc_temp,
        ]
        print(f'{foc_temp_c=}')
        motor_temp_c = [
            ls.motor_1.motor_temp,
            ls.motor_2.motor_temp,
            ls.motor_3.motor_temp,
            ls.motor_4.motor_temp,
            ls.motor_5.motor_temp,
            ls.motor_6.motor_temp,
        ]
        print(f'{motor_temp_c=}')
        time.sleep(1)

def main() -> None:
    show(CAN_NAME)


if __name__ == "__main__":
    main() 