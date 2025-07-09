#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: этот пример нельзя запустить напрямую; необходимо установить SDK через pip
# SDK версии V2
# Установка положения: горизонтальная верхняя (по умолчанию)
# Если нужно установить в боковом положении слева/справа
# MotionCtrl_2(0x01,0x01,0,0,0,0x02)
# MotionCtrl_2(0x01,0x01,0,0,0,0x03)

import time
from piper_sdk import *

if __name__ == "__main__":
    piper = C_PiperInterface_V2("can0")
    piper.ConnectPort()
    piper.MotionCtrl_2(0x01,0x01,0,0,0,0x01)  
    