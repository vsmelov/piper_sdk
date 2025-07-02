#!/usr/bin/env python3
# -*-coding:utf8-*-
# ВНИМАНИЕ: демо нельзя запускать напрямую — предварительно установите SDK через «pip install .».
# Скрипт выполняет быструю остановку манипулятора; используйте его при переходе
# из MIT-режима или режима "teach" обратно к позиционно-скоростному управлению.
# После выполнения команды требуется выполнить Reset и дважды заново включить моторы.

from typing import (
    Optional,
)
import time
from interface.piper_interface_v2 import *

# 测试代码
if __name__ == "__main__":
    piper = C_PiperInterface_V2()
    piper.ConnectPort()
    piper.MotionCtrl_1(0x01,0,0)
