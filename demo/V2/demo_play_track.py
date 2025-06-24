#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_play_track.py – воспроизведение ранее записанной траектории с помощью Piper SDK.

Использование:
    python demo_play_track.py path.json [--hz 50] [--can can0]

Скрипт:
1. Загружает список точек из JSON (см. demo_record_track.py).
2. Переключает манипулятор в режим управления по суставам (ModeCtrl: ctrl_mode=0x01, move_mode=0x01).
3. Последовательно отправляет JointCtrl для каждой точки с указанной частотой.
4. По завершении возвращается в standby и отключает CAN.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from piper_sdk.interface import C_PiperInterface_V2 as SDK

DEFAULT_CAN = "can0"


def play(json_path: Path, hz: int, can_name: str) -> None:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"В файле {json_path} нет данных для воспроизведения")

    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Переводим в режим CAN + Joint (MOVE J)
    arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=50, is_mit_mode=0x00)
    time.sleep(0.5)  # дать контроллеру переключиться

    period = 1.0 / hz
    print(f"Воспроизведение {len(data)} точек с частотой {hz} Гц…  Ctrl+C для прерывания.")
    try:
        for pt in data:
            if len(pt) != 6:
                print("⚠️  пропуск некорректной точки", pt)
                continue
            arm.JointCtrl(*pt)
            time.sleep(period)
    except KeyboardInterrupt:
        print("Остановлено пользователем.")
    finally:
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00)  # Standby
        arm.DisconnectPort()
    print("Готово.")


def main() -> None:
    p = argparse.ArgumentParser(description="Play Piper JSON trajectory")
    p.add_argument("json", type=Path, help="Файл с траекторией, записанной demo_record_track.py")
    p.add_argument("--hz", type=int, default=50, help="Частота отправки точек, Гц")
    p.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс")
    args = p.parse_args()

    play(args.json, args.hz, args.can)


if __name__ == "__main__":
    main() 