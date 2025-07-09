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

    logging.info("Enabling motors…")
    arm.EnableArm(7)
    time.sleep(0.5)

    logging.info("Switching to CAN MOVE J mode with 10 %% speed…")
    arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=100, is_mit_mode=0x00)
    time.sleep(0.5)

    # --- отправляем целевое положение ----------------------------------
    logging.info("Sending target JointCtrl / GripperCtrl …")
    arm.JointCtrl(*target[:6])
    if len(target) == 7:
        arm.GripperCtrl(target[6], 1000, 0x01, 0)

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
            max_diff = max(abs(a - b) for a, b in zip(current, target[:6]))
            logging.info("current=%s  target=%s  diff_max=%d", current, target[:6], max_diff)
            if max_diff <= THRESHOLD:
                logging.info("Target reached (diff %d <= %d)", max_diff, THRESHOLD)
                break
            time.sleep(LOG_PERIOD)
    except KeyboardInterrupt:
        logging.warning("Interrupted by user. Stopping movement …")
    finally:
        # Ставим в standby, отключаем CAN
        logging.info("Switching to standby and disconnecting …")
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
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