#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_record_track.py – запись траектории движения робота Piper в JSON.

Сценарий:
1. Запустите скрипт:  python demo_record_track.py  out.json  [--hz 50] [--can can0]
2. Рука автоматически переводится в режим drag-teach записи (MotionCtrl_1, grag_teach_ctrl=0x01).
3. Физически перемещайте манипулятор по нужной траектории (включая открытие-закрытие схвата).
4. Для завершения записи нажмите клавишу пробел (space) в терминале (без Enter) либо Ctrl+C.
5. Скрипт сохранит коллектированный массив суставных углов + гриппер в указанном JSON-файле.

Файл формируется как list[list[int, …]] где каждая точка – семь целых значений:
    6 углов суставов и угол гриппера (всё в 0.001° / 0.001 мм для гриппера).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK
from demo.V2.settings import CAN_NAME

# --- helpers -----------------------------------------------------------
# Неблокирующее чтение клавиатуры; завершаем запись при нажатии пробела.
import select
import termios
import tty


start_at = time.time()

def _stop_pressed() -> bool:  # noqa: D401 – одностр.
    """Вернёт True, если пользователь нажал пробел (space) без клавиши Enter."""

    if time.time() - start_at > 20:
        return True

    # Если скрипт запущен не из интерактивного терминала (например, IDE/cron),
    # stdin не является TTY – тогда просто игнорируем остановку по пробелу.
    if not sys.stdin.isatty():
        return False

    fd = sys.stdin.fileno()
    # Сохраняем текущие настройки терминала, переходим в cbreak-режим,
    # читаем символ (если он есть) и восстанавливаем настройки.
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:  # есть ввод от пользователя
            ch = sys.stdin.read(1)
            if ch == " ":
                return True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return False

DEFAULT_CAN = CAN_NAME


def record(json_path: Path, hz: int, can_name: str) -> None:
    arm = SDK.get_instance(can_name)
    arm.ConnectPort(can_init=False)

    # Переводим в режим drag-teach записи
    # arm.MotionCtrl_1(emergency_stop=0x00, track_ctrl=0x00, grag_teach_ctrl=0x01)

    period = 1.0 / hz
    data: List[List[int]] = []            # краткий трек (только углы + схват)
    details: List[dict] = []              # расширенный лог со всеми телеметрическими данными

    print(
        "Запись траектории начата. Перемещайте руку. "
        "Нажмите пробел для остановки или Ctrl+C."
    )
    try:
        while True:
            # --- получаем актуальные сообщения от SDK -------------------
            js = arm.GetArmJointMsgs().joint_state
            gr = arm.GetArmGripperMsgs().gripper_state
            hs = arm.GetArmHighSpdInfoMsgs()
            ls = arm.GetArmLowSpdInfoMsgs()

            # -- краткая запись (только суставы + схват) ------------------
            p = [
                js.joint_1,
                js.joint_2,
                js.joint_3,
                js.joint_4,
                js.joint_5,
                js.joint_6,
                gr.grippers_angle,
            ]
            data.append(p)
            print(p)

            # -- расширённая запись --------------------------------------
            sample = {
                "ts": time.time(),
                "joints_deg001": [
                    js.joint_1,
                    js.joint_2,
                    js.joint_3,
                    js.joint_4,
                    js.joint_5,
                    js.joint_6,
                ],
                "gripper_deg001": gr.grippers_angle,
                # High-speed feedback (каждый элемент – int из SDK)
                "motor_speed_rpm": [
                    hs.motor_1.motor_speed,
                    hs.motor_2.motor_speed,
                    hs.motor_3.motor_speed,
                    hs.motor_4.motor_speed,
                    hs.motor_5.motor_speed,
                    hs.motor_6.motor_speed,
                ],
                "motor_current_ma": [
                    hs.motor_1.current,
                    hs.motor_2.current,
                    hs.motor_3.current,
                    hs.motor_4.current,
                    hs.motor_5.current,
                    hs.motor_6.current,
                ],
                "motor_pos_deg001": [
                    hs.motor_1.pos,
                    hs.motor_2.pos,
                    hs.motor_3.pos,
                    hs.motor_4.pos,
                    hs.motor_5.pos,
                    hs.motor_6.pos,
                ],
                "motor_effort_mNm": [
                    hs.motor_1.effort,
                    hs.motor_2.effort,
                    hs.motor_3.effort,
                    hs.motor_4.effort,
                    hs.motor_5.effort,
                    hs.motor_6.effort,
                ],
                # Low-speed feedback
                "voltage_mv": [
                    ls.motor_1.vol,
                    ls.motor_2.vol,
                    ls.motor_3.vol,
                    ls.motor_4.vol,
                    ls.motor_5.vol,
                    ls.motor_6.vol,
                ],
                "foc_temp_c": [
                    ls.motor_1.foc_temp,
                    ls.motor_2.foc_temp,
                    ls.motor_3.foc_temp,
                    ls.motor_4.foc_temp,
                    ls.motor_5.foc_temp,
                    ls.motor_6.foc_temp,
                ],
                "motor_temp_c": [
                    ls.motor_1.motor_temp,
                    ls.motor_2.motor_temp,
                    ls.motor_3.motor_temp,
                    ls.motor_4.motor_temp,
                    ls.motor_5.motor_temp,
                    ls.motor_6.motor_temp,
                ],
                "bus_current_ma": [
                    ls.motor_1.bus_current,
                    ls.motor_2.bus_current,
                    ls.motor_3.bus_current,
                    ls.motor_4.bus_current,
                    ls.motor_5.bus_current,
                    ls.motor_6.bus_current,
                ],
            }
            details.append(sample)
            time.sleep(period)
            if _stop_pressed():
                print("Команда остановки получена – завершаю запись…")
                break
    except KeyboardInterrupt:
        print("KeyboardInterrupt – завершаю запись…")
    finally:
        # Завершаем режим записи траектории
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00, move_spd_rate_ctrl=0)
        arm.DisconnectPort()

    # Create tracks_db directory in current folder
    tracks_db_dir = Path.cwd() / "tracks_db"
    tracks_db_dir.mkdir(parents=True, exist_ok=True)
    
    # Update json_path to be in tracks_db directory
    json_path = tracks_db_dir / json_path.name

    # -- сохраняем краткий трек ------------------------------------------
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)

    # -- сохраняем расширённый лог ---------------------------------------
    details_path = json_path.with_suffix('.details.json')
    with details_path.open("w", encoding="utf-8") as f:
        json.dump(details, f)

    print(
        f"Сохранено {len(data)} точек в {json_path}\n"
        f"Сохранён детальный лог ({len(details)} точек) в {details_path}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Record Piper trajectory to JSON")
    p.add_argument("--json", type=Path, default='out.json', help="Путь, куда сохранить файл траектории")
    p.add_argument("--hz", type=int, default=50, help="Частота сэмплирования, Гц")
    p.add_argument("--can", type=str, default=DEFAULT_CAN, help="CAN-интерфейс (socketcan)")
    args = p.parse_args()

    record(args.json, args.hz, args.can)


if __name__ == "__main__":
    main() 