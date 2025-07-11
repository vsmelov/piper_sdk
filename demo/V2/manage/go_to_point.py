#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""go_to_point.py – медленный переход манипулятора Piper в сохранённую целевую точку.

Скрипт:
1. Загружает точку из JSON (tracks_db/<имя файла>, формат list[int]).
2. Подключается к роботу, включает моторы, устанавливает режим CAN+MOVE J с 10 % скорости.
3. Отправляет JointCtrl (+ GripperCtrl при наличии) и циклически опрашивает фактическое положение.
4. Подробно пишет логи target_position vs current_position в консоль и в файл .log рядом с JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import List

from demo.V2.settings import CAN_NAME
from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = CAN_NAME
DEFAULT_JSON = Path("point.json")
# Разница, при которой считаем, что целевая позиция достигнута (0.1° в единицах SDK)
THRESHOLD = 50  # 100 * 0.001° = 0.1°
LOG_PERIOD = 0.2  # сек


def _init_logger(log_path: Path) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO,
                        format=fmt,
                        handlers=[
                            logging.FileHandler(log_path, encoding="utf-8"),
                            logging.StreamHandler()
                        ])


def _load_point(json_path: Path) -> List[int]:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not (isinstance(data, list) and len(data) in (6, 7)):
        raise ValueError(f"Ожидался список из 6 или 7 чисел в {json_path}, получено: {data}")
    return data


def go_to_point(json_path: Path, can_name: str = DEFAULT_CAN) -> None:
    # Размещаем файлы в tracks_db
    tracks_db = Path.cwd() / "tracks_db"
    json_path = tracks_db / json_path.name
    log_path = json_path.with_suffix(".log")
    _init_logger(log_path)

    target = _load_point(json_path)
    logging.info("Target point loaded from %s: %s", json_path, target)

    arm = SDK.get_instance(can_name)
    logging.info("Connecting to CAN '%s'…", can_name)
    arm.ConnectPort(can_init=False)
    time.sleep(0.5)

    # Считываем исходную позу ДО включения моторов – будем возвращаться к ней
    js_init = arm.GetArmJointMsgs().joint_state
    gr_init = arm.GetArmGripperMsgs().gripper_state
    start_pose = [
        js_init.joint_1,
        js_init.joint_2,
        js_init.joint_3,
        js_init.joint_4,
        js_init.joint_5,
        js_init.joint_6,
        gr_init.grippers_angle,
    ]
    logging.info("Captured start pose: %s", start_pose)

    logging.info("Enabling motors…")
    arm.EnableArm(7)
    time.sleep(0.5)

    logging.info("Switching to CAN MOVE J mode with 10 %% speed…")
    arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=10, is_mit_mode=0x00)
    time.sleep(0.5)

    # --- helper to send pose and wait until reached --------------------------
    def _send_and_wait(pose: List[int]):
        arm.JointCtrl(*pose[:6])
        if len(pose) == 7:
            arm.GripperCtrl(pose[6], 1000, 0x01, 0)
        while True:
            js_curr = arm.GetArmJointMsgs().joint_state
            curr = [
                js_curr.joint_1,
                js_curr.joint_2,
                js_curr.joint_3,
                js_curr.joint_4,
                js_curr.joint_5,
                js_curr.joint_6,
            ]
            max_diff = max(abs(a - b) for a, b in zip(curr, pose[:6]))
            logging.info("current=%s  target=%s  diff_max=%d", curr, pose[:6], max_diff)
            if max_diff <= THRESHOLD:
                break
            time.sleep(LOG_PERIOD)

    # --- переход к целевой точке -------------------------------------------
    logging.info("Moving to target pose …")
    _send_and_wait(target)
    logging.info("Target reached.")

    # --- возврат к исходной позе -------------------------------------------
    logging.info("Returning to start pose …")
    _send_and_wait(start_pose)
    logging.info("Start pose reached.")

    # --- завершение ---------------------------------------------------------
        logging.info("Switching to standby and disconnecting …")
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
    arm.DisableArm(7)  # отпускание приводов для ручного перетаскивания
        arm.DisconnectPort()
        logging.info("Done.")


def main() -> None:
    pa = argparse.ArgumentParser(description="Move Piper arm to a recorded single pose")
    pa.add_argument("--json", type=Path, default=DEFAULT_JSON, help="JSON-файл с целевой точкой")
    pa.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = pa.parse_args()

    go_to_point(args.json, args.can)


if __name__ == "__main__":
    main() 