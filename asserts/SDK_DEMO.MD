# Все демо, связанные с SDK

## Чтение сообщений робота-манипулятора и их вывод

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Считываем и выводим сообщения робота-манипулятора; предварительно необходимо установить piper_sdk
from typing import (
    Optional,
)
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    while True:
        import time
        print(piper.GetArmStatus())
        time.sleep(0.005)
        pass
```

## Включение робота-манипулятора

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Включить робот-манипулятор
from typing import (
    Optional,
)
import time
from piper_sdk import *

def enable_fun(piper:C_PiperInterface, enable:bool):
    '''
    Включить робот-манипулятор и проверить состояние включения; попытка 5 с, если по таймауту не удалось — выйти из программы
    '''
    enable_flag = False
    loop_flag = False
    # Установить тайм-аут (сек)
    timeout = 5
    # Сохраняем время входа в цикл
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
        # Проверяем, не превышено ли время ожидания
        if elapsed_time > timeout:
            print(f"Таймаут....")
            elapsed_time_flag = True
            enable_flag = False
            loop_flag = True
            break
        time.sleep(0.5)
    resp = enable_flag
    print(f"Возвращаем ответ: {resp}")
    return resp

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    import time
    flag = enable_fun(piper=piper, enable=False)
    if(flag == True):
        print("Отключение успешно!!!!")
        exit(0)
    pass
```

## Отключение робота-манипулятора

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Включить робот-манипулятор
from typing import (
    Optional,
)
import time
from piper_sdk import *

def enable_fun(piper:C_PiperInterface, enable:bool):
    '''
    Включить робот-манипулятор и проверить состояние включения; попытка 5 с, если по таймауту не удалось — выйти из программы
    '''
    enable_flag = False
    loop_flag = False
    # Установить тайм-аут (сек)
    timeout = 5
    # Сохраняем время входа в цикл
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
        # Проверяем, не превышено ли время ожидания
        if elapsed_time > timeout:
            print(f"Таймаут....")
            elapsed_time_flag = True
            enable_flag = False
            loop_flag = True
            break
        time.sleep(0.5)
    resp = enable_flag
    print(f"Возвращаем ответ: {resp}")
    return resp

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    import time
    flag = enable_fun(piper=piper, enable=True)
    if(flag == True):
        print("Включение успешно!!!!")
        exit(0)
    pass
```

## Чтение углов суставов робота-манипулятора

Если нет захвата, можно закомментировать часть, связанную с захватом

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Считываем и выводим сообщения робота-манипулятора; предварительно необходимо установить piper_sdk
from typing import (
    Optional,
)
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    while True:
        import time
        print(piper.GetArmJointMsgs())
        print(piper.GetArmGripperMsgs())
        time.sleep(0.005)
        pass
```

## Управление углами суставов робота-манипулятора

Если нет захвата, можно закомментировать часть, связанную с захватом

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Включить робот-манипулятор и проверить состояние включения; попытка 5 с, если по таймауту не удалось — выйти из программы
from typing import (
    Optional,
)
import time
from piper_sdk import *

def enable_fun(piper:C_PiperInterface):
    '''
    Включить робот-манипулятор и проверить состояние включения; попытка 5 с, если по таймауту не удалось — выйти из программы
    '''
    enable_flag = False
    # Установить тайм-аут (сек)
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
        # Проверяем, не превышено ли время ожидания
        if elapsed_time > timeout:
            print("Таймаут....")
            elapsed_time_flag = True
            enable_flag = True
            break
        time.sleep(1)
        pass
    if(elapsed_time_flag):
        print("Программа автоматически завершилась из-за тайм-аута включения")
        exit(0)

if __name__ == "__main__":
    piper = C_PiperInterface("can0")
    piper.ConnectPort()
    piper.EnableArm(7)
    enable_fun(piper=piper)
    # piper.DisableArm(7)
    piper.GripperCtrl(0,1000,0x01, 0)
    factor = 57324.840764 #1000*180/3.14
    position = [0,0,0,0,0,0,0]
    count = 0
    while True:
        print(piper.GetArmStatus())
        import time
        count  = count + 1
        # print(count)
        if(count == 0):
            print("1-----------")
            position = [0,0,0,0,0,0,0]
        elif(count == 500):
            print("2-----------")
            position = [0.2,0.2,-0.2,0.3,-0.2,0.5,0.08]
        elif(count == 1000):
            print("1-----------")
            position = [0,0,0,0,0,0,0]
            count = 0
        
        joint_0 = round(position[0]*factor)
        joint_1 = round(position[1]*factor)
        joint_2 = round(position[2]*factor)
        joint_3 = round(position[3]*factor)
        joint_4 = round(position[4]*factor)
        joint_5 = round(position[5]*factor)
        joint_6 = round(position[6]*1000*1000)
        # piper.MotionCtrl_1()
        piper.MotionCtrl_2(0x01, 0x01, 50, 0x00)
        piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
        piper.GripperCtrl(abs(joint_6), 1000, 0x01, 0)
        piper.MotionCtrl_2(0x01, 0x01, 50, 0x00)
        time.sleep(0.005)
        pass
```

## Настройка робота-манипулятора как ведущего

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Установить робота-манипулятора в режим ведущего, достаточно просто задать параметр
from typing import (
    Optional,
)
from piper_sdk import *
import time

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    piper.MasterSlaveConfig(0xFA, 0, 0, 0)
```

## Настройка робота-манипулятора как ведомого

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Установить робота-манипулятор в режим ведомого
# Обратите внимание: если робот-манипулятор находится в режиме ведущего, после отправки команды настройки потребуется перезагрузка
from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    piper.MasterSlaveConfig(0xFC, 0, 0, 0)
```

## Чтение максимального ограничения ускорения всех моторов манипулятора

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Чтение максимального ограничения ускорения всех моторов манипулятора

from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    while True:
        # piper.SearchAllMotorMaxAccLimit() # Эта функция уже вызывается в ConnectPort, поэтому при каждом запуске программы будет отправляться запрос на чтение
        print(piper.GetAllMotorMaxAccLimit())
        time.sleep(0.01)
```

## Чтение максимальных ограничений угла и скорости всех моторов манипулятора

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Чтение максимальных ограничений угла и скорости всех моторов манипулятора

from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    while True:
        # piper.SearchAllMotorMaxAngleSpd() # Эта функция уже вызывается в ConnectPort, поэтому при каждом запуске программы будет отправляться запрос на чтение
        print(piper.GetAllMotorAngleLimitMaxSpd())
        time.sleep(0.01)
```

## Сброс робота-манипулятора

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Сброс робота-манипулятора: следует выполнить при переключении из режима MIT или обучения в режим позиционно-скоростного управления

from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    piper.MotionCtrl_1(0x02,0,0)# восстановить
    piper.MotionCtrl_2(0, 0, 0, 0x00)# режим позиция-скорость
```

## Переключение робота-манипулятора в режим управления MIT

```python
#!/usr/bin/env python3
# -*-coding:utf8-*-
# Обратите внимание: демо нельзя запустить напрямую, сначала установите sdk через pip
# Переключить робот-манипулятор в режим управления MIT; в этом режиме он реагирует быстрее всего

from typing import (
    Optional,
)
import time
from piper_sdk import *

# Тестовый код
if __name__ == "__main__":
    piper = C_PiperInterface()
    piper.ConnectPort()
    piper.MotionCtrl_2(0, 0, 0, 0xAD)# 0xFC
```
