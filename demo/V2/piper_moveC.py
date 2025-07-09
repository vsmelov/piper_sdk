#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание, этот пример невозможно запустить напрямую; сначала установите SDK через pip
# Демо дугового режима роботизированной руки Piper
# Убедитесь, что в рабочем пространстве робота нет препятствий

from typing import (
    Optional,
)
import time
from interface.piper_interface_v2 import *

def enable_fun(piper:C_PiperInterface_V2):
    '''
    Включить роботизированную руку и проверить статус включения, попытка 5 с; если время ожидания превышено, программа завершится
    '''
    enable_flag = False
    # Установка тайм-аута (сек)
    timeout = 5
    # Сохраняем время входа в цикл
    start_time = time.time()
    elapsed_time_flag = False
    while not (enable_flag):
        elapsed_time = time.time() - start_time
        print("--------------------")
        enable_flag = piper.GetArmLowSpdInfoMsgs().motor_1.foc_status.driver_enable_status and \
            piper.GetArmLowSpdInfoMsgs().motor_2.foc_status.driver_enable_status and \
            piper.GetArmLowSpdInfoMsgs().motor_3.foc_status.driver_enable_status and \
            piper.GetArmLowSpdInfoMsgs().motor_4.foc_status.driver_enable_status and \
            piper.GetArmLowSpdInfoMsgs().motor_5.foc_status.driver_enable_status and \
            piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status
        print("Состояние включения:",enable_flag)
        piper.EnableArm(7)
        piper.GripperCtrl(0,1000,0x01, 0)
        print("--------------------")
        # Проверяем, превышено ли время ожидания
        if elapsed_time > timeout:
            print("Превышено время ожидания...")
            elapsed_time_flag = True
            enable_flag = True
            break
        time.sleep(1)
        pass
    if(elapsed_time_flag):
        print("Автоматическое включение превысило время ожидания, программа завершается")
        exit(0)

if __name__ == "__main__":
    piper = C_PiperInterface_V2()
    piper.ConnectPort()
    piper.EnableArm(7)
    enable_fun(piper=piper)
    # piper.DisableArm(7)
    piper.GripperCtrl(0,1000,0x01, 0)
    # X:135.481
    piper.EndPoseCtrl(135481,9349,161129,178756,6035,-178440)
    piper.MoveCAxisUpdateCtrl(0x01)
    time.sleep(0.001)
    piper.EndPoseCtrl(222158,128758,142126,175152,-1259,-157235)
    piper.MoveCAxisUpdateCtrl(0x02)
    time.sleep(0.001)
    piper.EndPoseCtrl(359079,3221,153470,179038,1105,179035)
    piper.MoveCAxisUpdateCtrl(0x03)
    time.sleep(0.001)
    piper.MotionCtrl_2(0x01, 0x03, 30, 0x00)
    pass