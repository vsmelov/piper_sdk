#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_record_track.py – запись траектории движения робота Piper в JSON.

Сценарий:
1. Запустите скрипт:  python demo_record_track.py  out.json  [--hz 50] [--can can0]
2. Рука автоматически переводится в режим drag-teach записи (MotionCtrl_1, grag_teach_ctrl=0x01).
3. Физически перемещайте манипулятор по нужной траектории.
4. Для завершения записи нажмите клавишу «s» в терминале (без Enter) либо Ctrl+C.
5. Скрипт сохранит коллектированный массив суставных углов в указанном JSON-файле.

Файл формируется как list[list[int, …]] где каждая точка – шесть целых значений
(углы суставов в 0.001°).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

from piper_sdk.interface import C_PiperInterface_V2 as SDK

# ---------------------------------------------------------------------------
# Вспомогательные утилиты работы с клавиатурой (кросс-платформенно)
# ---------------------------------------------------------------------------
try:
    # Windows – используем msvcrt, не требует сторонних зависимостей.
    import msvcrt  # type: ignore

    def _stop_pressed() -> bool:  # noqa: D401 – одностр.
        """True если пользователь нажал «s»/«S» без необходимости нажимать Enter."""
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            return ch.lower() == b"s"
        return False
except ImportError:  # POSIX
    import select
    import termios
    import tty

    _orig_attrs = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin)  # немедленное чтение символа

    def _stop_pressed() -> bool:  # noqa: D401
        """True если в stdin появился символ «s»/«S» (работает в POSIX)."""
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:
            ch = sys.stdin.read(1)
            return ch.lower() == "s"
        return False

    import atexit

    @atexit.register
    def _restore_tty():
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _orig_attrs)

# ---------------------------------------------------------------------------

DEFAULT_CAN = "can0"


def record(json_path: Path, hz: int, can_name: str) -> None:
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Переводим в режим drag-teach записи
    arm.MotionCtrl_1(emergency_stop=0x00, track_ctrl=0x00, grag_teach_ctrl=0x01)

    period = 1.0 / hz
    data: List[List[int]] = []

    print(
        "Запись траектории начата. Перемещайте руку. "
        "Нажмите клавишу 's' для остановки или Ctrl+C."
    )
    try:
        while True:
            js = arm.GetArmJointMsgs().joint_state
            data.append([
                js.joint_1,
                js.joint_2,
                js.joint_3,
                js.joint_4,
                js.joint_5,
                js.joint_6,
            ])
            time.sleep(period)
            if _stop_pressed():
                print("Команда остановки получена – завершаю запись…")
                break
    except KeyboardInterrupt:
        print("KeyboardInterrupt – завершаю запись…")
    finally:
        # Завершаем режим записи траектории
        arm.MotionCtrl_1(0x00, 0x00, 0x02)
        arm.DisconnectPort()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Сохранено {len(data)} точек в {json_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Record Piper trajectory to JSON")
    p.add_argument("json", type=Path, help="Путь, куда сохранить файл траектории")
    p.add_argument("--hz", type=int, default=50, help="Частота сэмплирования, Гц")
    p.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = p.parse_args()

    record(args.json, args.hz, args.can)


if __name__ == "__main__":
    main() 