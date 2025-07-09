#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_point.py – сохранение единственной точки положения манипулятора Piper.

Скрипт:
1. Подключается к CAN-шине (по умолчанию can0).
2. Считывает текущие суставные углы + положение схвата.
3. Сохраняет точку в JSON-файл (tracks_db/<имя файла>). Формат – list[int, …] длиной 7:
   [j1, j2, j3, j4, j5, j6, gripper]. Все значения в единицах SDK – 0.001° / 0.001 мм.
4. Логи пишутся как в консоль, так и в файл .log рядом с JSON.
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

def _init_logger(log_path: Path) -> None:
    """Настройка логгера: вывод и в файл, и в терминал."""
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=logging.INFO,
                        format=fmt,
                        handlers=[
                            logging.FileHandler(log_path, encoding="utf-8"),
                            logging.StreamHandler()
                        ])


def record_point(json_path: Path, can_name: str = DEFAULT_CAN, settle_sec: float = 0.5) -> None:
    """Сохраняет одну точку."""
    # Располагаем файл в подпапке tracks_db
    tracks_db = Path.cwd() / "tracks_db"
    tracks_db.mkdir(parents=True, exist_ok=True)
    json_path = tracks_db / json_path.name
    _init_logger(json_path.with_suffix(".log"))

    logging.info("Connecting to CAN '%s'…", can_name)
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Даём времени драйверам/шине стабилизироваться
    logging.info("Waiting %.2f s to stabilise SDK feedback…", settle_sec)
    time.sleep(settle_sec)

    # Читаем актуальные данные
    js = arm.GetArmJointMsgs().joint_state
    gr = arm.GetArmGripperMsgs().gripper_state
    point: List[int] = [
        js.joint_1,
        js.joint_2,
        js.joint_3,
        js.joint_4,
        js.joint_5,
        js.joint_6,
        gr.grippers_angle,
    ]

    logging.info("Recorded point: %s", point)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(point, f)
    logging.info("Saved point to %s", json_path)

    arm.DisconnectPort()
    logging.info("Disconnect complete – done.")


def main() -> None:
    pa = argparse.ArgumentParser(description="Record single Piper pose to JSON")
    pa.add_argument("--json", type=Path, default=DEFAULT_JSON,
                    help="Имя JSON-файла для сохранения (по умолчанию point.json)")
    pa.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = pa.parse_args()

    record_point(args.json, args.can)


if __name__ == "__main__":
    main() 