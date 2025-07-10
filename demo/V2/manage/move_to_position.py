#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_to_position.py – перемещение робота Piper к записанной позиции.

Сценарий:
1. Запустите скрипт: python move_to_position.
2. Введите название позиции в терминале
3. Скрипт плавно переместит робота к записанной позиции
4. После достижения позиции робот переходит в режим ожидания

Файл позиции должен содержать 7 целых значений:
    6 углов суставов и угол гриппера (всё в 0.001° / 0.001 мм для гриппера).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK

DEFAULT_CAN = "can_piper"
DEFAULT_SPEED = 30  # Speed percentage (0-100)
DEFAULT_HZ = 50     # Control frequency


def load_position(position_name: str) -> List[int]:
    """Загружает позицию из JSON файла."""
    
    # Create safe filename
    safe_name = "".join(c for c in position_name if c.isalnum() or c in "_-").strip()
    if not safe_name:
        raise ValueError("Название позиции должно содержать буквы или цифры.")
    
    # Look for file in tracks_db directory
    tracks_db_dir = Path.cwd() / "tracks_db"
    file_path = tracks_db_dir / f"position__{safe_name}.json"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Позиция '{position_name}' не найдена в {file_path}")
    
    with file_path.open("r", encoding="utf-8") as f:
        position_data = json.load(f)
    
    if not isinstance(position_data, list) or len(position_data) != 7:
        raise ValueError(f"Неверный формат данных в файле {file_path}")
    
    return position_data


def get_current_position(arm) -> List[int]:
    """Получает текущую позицию робота."""
    js = arm.GetArmJointMsgs().joint_state
    gr = arm.GetArmGripperMsgs().gripper_state
    
    return [
        js.joint_1,
        js.joint_2,
        js.joint_3,
        js.joint_4,
        js.joint_5,
        js.joint_6,
        gr.grippers_angle,
    ]


def move_to_position(position_name: str, can_name: str = DEFAULT_CAN, 
                   speed: int = DEFAULT_SPEED, hz: int = DEFAULT_HZ) -> None:
    """Плавно перемещает робота к записанной позиции."""
    
    try:
        # Load target position
        target_position = load_position(position_name)
        print(f"✓ Загружена позиция '{position_name}'")
        print(f"  Целевые суставы (0.001°): {target_position[:6]}")
        print(f"  Целевой гриппер (0.001°): {target_position[6]}")
        
        # Connect to robot
        arm = SDK.get_instance(can_name)
        arm.ConnectPort(can_init=False)
        
        print(f"Подключение к роботу через {can_name}...")
        time.sleep(1.0)
        
        # Enable motors and set control mode
        arm.EnableArm(7)  # Enable all motors
        time.sleep(0.5)   # Wait for drivers to activate
        
        arm.ModeCtrl(ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=speed, is_mit_mode=0x00)
        time.sleep(0.5)   # Wait for controller to switch modes
        
        # Get current position
        current_position = get_current_position(arm)
        print(f"  Текущие суставы (0.001°): {current_position[:6]}")
        print(f"  Текущий гриппер (0.001°): {current_position[6]}")
        
        # Calculate movement duration based on maximum joint difference
        max_diff = max(abs(t - c) for t, c in zip(target_position[:6], current_position[:6]))
        movement_time = max(2.0, max_diff / 1000.0 * 2.0)  # At least 2 seconds, scale with distance
        
        print(f"Перемещение к позиции '{position_name}'...")
        print(f"Время перемещения: ~{movement_time:.1f} секунд")
        
        # Smooth movement using interpolation
        period = 1.0 / hz
        total_steps = int(movement_time * hz)
        
        for step in range(total_steps + 1):
            # Calculate interpolation factor (0.0 to 1.0)
            t = step / total_steps
            # Use smooth step function (ease-in-out)
            t = t * t * (3.0 - 2.0 * t)
            
            # Interpolate between current and target positions
            interpolated_position = []
            for i in range(7):
                current_val = current_position[i]
                target_val = target_position[i]
                interpolated_val = int(current_val + t * (target_val - current_val))
                interpolated_position.append(interpolated_val)
            
            # Send joint commands
            arm.JointCtrl(*interpolated_position[:6])
            arm.GripperCtrl(interpolated_position[6], 1000, 0x01, 0)
            
            # Progress indicator
            if step % (total_steps // 10) == 0 or step == total_steps:
                progress = (step / total_steps) * 100
                print(f"  Прогресс: {progress:.0f}%")
            
            time.sleep(period)
        
        print("✓ Перемещение завершено!")
        
        # Verify final position
        final_position = get_current_position(arm)
        print(f"  Финальные суставы (0.001°): {final_position[:6]}")
        print(f"  Финальный гриппер (0.001°): {final_position[6]}")
        
        # Keep motors enabled but return to standby mode
        arm.ModeCtrl(ctrl_mode=0x00, move_mode=0x00, move_spd_rate_ctrl=0)
        print("Робот переведен в режим ожидания (моторы включены)")
        
    except FileNotFoundError as e:
        print(f"Ошибка: {e}")
    except ValueError as e:
        print(f"Ошибка: {e}")
    except Exception as e:
        print(f"Ошибка при перемещении: {e}")
    finally:
        try:
            arm.DisconnectPort()
        except:
            pass


def list_positions() -> None:
    """Показывает список доступных позиций."""
    tracks_db_dir = Path.cwd() / "tracks_db"
    
    if not tracks_db_dir.exists():
        print("Папка tracks_db не найдена. Сначала запишите несколько позиций.")
        return
    
    position_files = list(tracks_db_dir.glob("position__*.json"))
    
    if not position_files:
        print("Записанные позиции не найдены.")
        return
    
    print("Доступные позиции:")
    for file_path in sorted(position_files):
        position_name = file_path.stem.replace("position__", "")
        print(f"  - {position_name}")


def main() -> None:
    print("=== Перемещение к позиции робота Piper ===")
    print("Введите название позиции для перемещения.")
    print("Команды: 'list' - показать позиции, 'exit' - выход\n")
    
    try:
        command = input("Позиция (или команда): ").strip()

        if not command:
            print(f'error - not command')
        elif command.lower() == 'exit':
            return
        elif command.lower() == 'list':
            list_positions()
            print()
        else:
            move_to_position(command)
            print()  # Empty line for readability
                
    except KeyboardInterrupt:
        print("\nЗавершение работы.")


if __name__ == "__main__":
    main() 