#!/usr/bin/env python3
# -*-coding:utf8-*-
# ВНИМАНИЕ: демо нельзя запустить напрямую — перед этим установите SDK через «pip install .».
# Переводит манипулятор в MIT-режим, в котором отклик двигателя на команды максимальный.

from typing import (
    Optional,
)
import time
from piper_sdk import *

# 测试代码
if __name__ == "__main__":
    piper = C_PiperInterface_V2()
    piper.ConnectPort()
    while True:
        piper.MotionCtrl_2(1, 1, 0, 0xAD)# 0xFC
        time.sleep(1)
