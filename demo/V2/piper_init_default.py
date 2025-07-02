#!/usr/bin/env python3
# -*-coding:utf8-*-
# 注意demo无法直接运行，需要pip安装sdk后才能运行
# Обратите внимание: демо-скрипт не может запускаться напрямую, необходимо установить SDK через pip
# V2版本sdk
# SDK версии V2
# 机械臂 设置全部关节限位、关节最大速度、关节加速度为默认值： 0x02
# Робот-манипулятор: установить все предельные углы суставов, максимальную скорость суставов и ускорение суставов по умолчанию: 0x02

from typing import (
    Optional,
)
import time
from piper_sdk import *

def enable_fun(piper:C_PiperInterface_V2, enable:bool):
    '''
    Включить манипулятор и проверять состояние включения в течение 5 с; если время ожидания превышено, программа завершится
    '''
    enable_flag = False
    loop_flag = False
    # 设置超时时间（秒）
    # Установить тайм-аут (сек)
    timeout = 5
    # 记录进入循环前的时间
    # Зафиксировать время входа в цикл
    start_time = time.time()
    elapsed_time_flag = False
    while not (loop_flag):
        elapsed_time = time.time() - start_time
        print(f"--------------------")
        enable_list = []
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_1.foc_status.driver_enable_status)
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_2.foc_status.driver_enable_status)
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_3.foc_status.driver_enable_status)
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_4.foc_status.driver_enable_status)
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_5.foc_status.driver_enable_status)
        enable_list.append(piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status)
        if(enable):
            enable_flag = all(enable_list)
            piper.EnableArm(7)
            piper.GripperCtrl(0,1000,0x01, 0)
        else:
            enable_flag = any(enable_list)
            piper.DisableArm(7)
            piper.GripperCtrl(0,1000,0x02, 0)
        print(f"Состояние включения: {enable_flag}")
        print(f"--------------------")
        if(enable_flag == enable):
            loop_flag = True
            enable_flag = True
        else: 
            loop_flag = False
            enable_flag = False
        # 检查是否超过超时时间
        # Проверить, не превышен ли тайм-аут
        if elapsed_time > timeout:
            print(f"Вышло время....")
            elapsed_time_flag = True
            enable_flag = False
            loop_flag = True
            break
        time.sleep(0.5)
    resp = enable_flag
    print(f"Returning response: {resp}")
    return resp

if __name__ == "__main__":
    piper = C_PiperInterface_V2("can0")
    piper.ConnectPort()
    piper.EnableArm(7)
    # enable_fun(piper=piper, enable=True)
    piper.ArmParamEnquiryAndConfig(0x01,0x02,0,0,0x02)
    while True:
        piper.SearchAllMotorMaxAngleSpd()
        print(piper.GetAllMotorAngleLimitMaxSpd())
        time.sleep(0.01)