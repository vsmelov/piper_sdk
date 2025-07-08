#!/usr/bin/env python3
# -*-coding:utf8-*-
# 注意demo无法直接运行，需要pip安装sdk后才能运行
from typing import (
    Optional,
)
import time
from interface.piper_interface_v2 import *

if __name__ == "__main__":
    piper = C_PiperInterface_V2()
    piper.ConnectPort()
    # (-2.09439, 2.09439)
    # (0.0, 0.07)
    print(piper.GetSDKJointLimitParam('j6'))
    print(piper.GetSDKGripperRangeParam())

    piper.SetSDKGripperRangeParam(0, 0)
    piper.SetSDKJointLimitParam('j6', -2.09439, 2.09439)

    print(piper.GetSDKJointLimitParam('j6'))
    print(piper.GetSDKGripperRangeParam())
