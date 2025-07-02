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
from demo.V2.settings import CAN_NAME
from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = CAN_NAME

# --- ПАРАМЕТРЫ ПО УМОЛЧАНИЮ ---
JSON_PATH = Path("tracks_db/out.json")  # файл с траекторией в tracks_db подпапке
HZ = 50
CAN = DEFAULT_CAN


def play(json_path: Path = JSON_PATH, hz: int = HZ, can_name: str = CAN) -> None:
    # Look for file in tracks_db directory if not absolute path
    if not json_path.is_absolute():
        tracks_db_dir = Path.cwd() / "tracks_db"
        json_path = tracks_db_dir / json_path.name

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"В файле {json_path} нет данных для воспроизведения")

    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)


    # arm.MotionCtrl_1(0x02,0,0)  # 2 восстановление
    # arm.MotionCtrl_2(0, 0, 0, 0x00)  # позиционно-скоростной режим

    # arm.MotionCtrl_1(0x02,0,0)  # 2 восстановление
    # time.sleep(0.5)
    #
    # exit()
    # arm.MotionCtrl_2(0, 0, 0, 0x00)  # 3 озиционно-скоростной режим

    # Переключаем в режим CAN + Joint (MOVE J)
    time.sleep(0.5)  # дать драйверам включиться

    # piper.GripperCtrl(0, 1000, 0x01, 0)
    arm.EnableArm(7)  # включаем все двигатели
    # arm.GripperCtrl(0, 1000, 0x01, 0)
    arm.ModeCtrl(0x01, 0x01, 50, 0x00) # 1

    time.sleep(0.5)  # дать контроллеру переключиться

    period = 1.0 / hz
    print(f"Воспроизведение {len(data)} точек с частотой {hz} Гц…  Ctrl+C для прерывания.")
    try:
        for pt in data:
            if len(pt) == 6:
                arm.JointCtrl(*pt)
            elif len(pt) == 7:
                arm.JointCtrl(*pt[:6])
                arm.GripperCtrl(pt[6], 1000, 0x01, 0)
            else:
                print("⚠️  пропуск некорректной точки", pt)
                continue
            time.sleep(period)
    except KeyboardInterrupt:
        print("Остановлено пользователем.")
    finally:
        # Переводим в standby и отключаем моторы, если явно попросили
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)
        # От CAN можно отключиться в любом случае – моторы уже получили последнее задание
        arm.DisconnectPort()
    print("Готово.")


def main() -> None:
    play()


if __name__ == "__main__":
    main() 