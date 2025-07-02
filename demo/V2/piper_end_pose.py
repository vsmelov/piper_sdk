#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демонстрационный пример нельзя запускать напрямую, необходимо установить SDK через pip
from typing import (
    Optional,
)
import time
from piper_sdk import *

def enable_fun(piper:C_PiperInterface_V2):
    '''
    Включить манипулятор и проверить состояние включения; пытаться в течение 5 с.
    Если превышено время ожидания, программа завершится.
    '''
    enable_flag = False
    # Установить время ожидания (сек)
    timeout = 5
    # Зафиксировать время входа в цикл
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
        # Проверить, превышено ли время ожидания
        if elapsed_time > timeout:
            print("Тайм-аут....")
            elapsed_time_flag = True
            enable_flag = True
            break
        time.sleep(1)
        pass
    if(elapsed_time_flag):
        print("Автоматическое включение превысило время ожидания, выход из программы")
        exit(0)

if __name__ == "__main__":
    from settings import CAN_NAME
    piper = C_PiperInterface_V2(CAN_NAME)
    piper.ConnectPort()
    piper.EnableArm(7)
    enable_fun(piper=piper)
    piper.GripperCtrl(0,1000,0x01, 0)
    factor = 1000
    position = [
                55.0, \
                0.0, \
                206.0, \
                0, \
                85.0, \
                0, \
                0]
    # position = [0.0, \
    #             0.0, \
    #             80.0, \
    #             0, \
    #             203.386, \
    #             0, \
    #             0.8]
    count = 0
    while True:
        # print(piper.GetArmEndPoseMsgs())
        # print(piper.GetArmStatus())
        import time
        count  = count + 1
        # print(count)
        if(count == 0):
            print("1-----------")
            position = [
                55.0, \
                0.0, \
                206.0, \
                0, \
                85.0, \
                0, \
                0]
        elif(count == 200):
            print("2-----------")
            position = [
                55.0, \
                0.0, \
                260.0, \
                0, \
                85.0, \
                0, \
                0]
        elif(count == 400):
            print("3-----------")
            position = [
                55.0, \
                0.0, \
                206.0, \
                0, \
                85.0, \
                0, \
                0]
            count = 0
        
        X = round(position[0]*factor)
        Y = round(position[1]*factor)
        Z = round(position[2]*factor)
        RX = round(position[3]*factor)
        RY = round(position[4]*factor)
        RZ = round(position[5]*factor)
        joint_6 = round(position[6]*factor)
        # print(X,Y,Z,RX,RY,RZ)
        # piper.MotionCtrl_1()
        piper.MotionCtrl_2(
            0x01,
            0x00,
            100,
            0x00,
        )
        piper.EndPoseCtrl(X,Y,Z,RX,RY,RZ)
        piper.GripperCtrl(
            abs(joint_6), 1000, 0x01, 0)
        time.sleep(0.01)
        pass