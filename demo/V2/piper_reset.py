#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демонстрационный пример нельзя запустить напрямую, необходимо установить SDK через pip.
# Сброс манипулятора; необходимо выполнить при переключении из режима MIT или обучения в режим позиционно-скоростного управления.

from typing import (
    Optional,
)
import time
from interface.piper_interface_v2 import *
from demo.V2.settings import CAN_NAME

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface_V2(can_name=CAN_NAME)
    piper.ConnectPort()
    piper.MotionCtrl_1(0x01,0,0)  # восстановление
    # piper.MotionCtrl_1(0x00,0,0x01)  # восстановление
    import time
    time.sleep(4)
    piper.MotionCtrl_1(0x02,0,0)  # восстановление
    piper.MotionCtrl_2(0, 0, 0, 0x00)  # позиционно-скоростной режим
