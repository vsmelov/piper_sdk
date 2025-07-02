#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_position.py – запись текущей позиции робота Piper в JSON.

Сценарий:
1. Запустите скрипт: python record_position.py
2. Введите название позиции в терминале и нажмите Enter
3. Нажмите Enter еще раз для подтверждения и записи текущей позиции
4. Скрипт сохранит текущие углы суставов + гриппер в файл position__{name}.json

Файл формируется как list[int, …] где 7 целых значений:
    6 углов суставов и угол гриппера (всё в 0.001° / 0.001 мм для гриппера).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = "can_piper"


def record_position(arm, position_name: str) -> None:
    """Записывает текущую позицию робота в JSON файл."""
    
    # Validate position name
    if not position_name.strip():
        print("Ошибка: название позиции не может быть пустым.")
        return
    
    # Remove any invalid characters for filename
    safe_name = "".join(c for c in position_name if c.isalnum() or c in "_-").strip()
    if not safe_name:
        print("Ошибка: название позиции должно содержать буквы или цифры.")
        return
    
    # Предполагаем, что подключение уже установлено в main()
    
    try:
        # Get current joint positions
        js = arm.GetArmJointMsgs().joint_state
        gr = arm.GetArmGripperMsgs().gripper_state
        
        # Create position data (6 joints + gripper)
        position_data = [
            js.joint_1,
            js.joint_2,
            js.joint_3,
            js.joint_4,
            js.joint_5,
            js.joint_6,
            gr.grippers_angle,
        ]
        
        # Create tracks_db directory
        tracks_db_dir = Path.cwd() / "tracks_db"
        tracks_db_dir.mkdir(parents=True, exist_ok=True)
        
        # Save position to file
        filename = f"position__{safe_name}.json"
        file_path = tracks_db_dir / filename
        
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(position_data, f)
        
        print(f"✓ Позиция '{position_name}' сохранена в {file_path}")
        print(f"  Суставы (0.001°): {position_data[:6]}")
        print(f"  Гриппер (0.001°): {position_data[6]}")
        
    except Exception as e:
        print(f"Ошибка при записи позиции: {e}")


def main() -> None:
    print("=== Запись позиции робота Piper ===")
    print("Введите название позиции, затем нажмите Enter еще раз для записи.")
    print("Для выхода нажмите Ctrl+C\n")
    
    try:
        arm = SDK.get_instance(DEFAULT_CAN)
        arm.ConnectPort(can_init=False)
        print(f"Подключено к роботу через {DEFAULT_CAN}. Можно записывать позиции.")

        # Step 1: Get position name
        position_name = input("Название позиции: ").strip()
        if not position_name:
            print("Пожалуйста, введите название позиции.\n")
            continue

        # Step 2: Confirm and record
        print(f"Готово записать позицию '{position_name}'. Нажмите Enter для подтверждения...")
        confirm = input().strip()

        # Record the position (regardless of what was entered for confirmation)
        record_position(arm, position_name)
        print()  # Empty line for readability
                
    except KeyboardInterrupt:
        print("\nЗавершение работы пользователем.")
    finally:
        try:
            arm.DisconnectPort()
        except Exception:
            pass


if __name__ == "__main__":
    main() 