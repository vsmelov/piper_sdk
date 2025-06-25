#!/usr/bin/env python3
# -*-coding:utf8-*-
# ВНИМАНИЕ: демо нельзя запускать напрямую — предварительно установите SDK через «pip install .».
# Скрипт задаёт уровни защиты от столкновений (crash-protection) для манипулятора и выводит текущие значения.

from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый запуск
if __name__ == "__main__":
    piper = C_PiperInterface_V2("can0",False)
    piper.ConnectPort()
    # piper.CrashProtectionConfig(1,1,1,1,1,1)
    piper.CrashProtectionConfig(0,0,0,0,0,0)
    while True:
        piper.ArmParamEnquiryAndConfig(0x02, 0x00, 0x00, 0x00, 0x03)

        print(piper.GetCrashProtectionLevelFeedback())
        time.sleep(0.01)