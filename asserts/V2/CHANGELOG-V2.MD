# ChangeLog-V2 (русский перевод)

> V1 и V2 здесь относятся к релизной ветке **0.1.x** и не связаны с веткой **0.0.x**.
> Основное отличие **V2** от **V1** — новый протокол. Код 0.1.x значительно отличается от 0.0.x.

Ниже перечислены изменения/дополнения, появившиеся в V2 по сравнению с V1.

---

## 1 Совместимость прошивки

Поддерживается новая прошивка (версии **V1.5-2** и новее); при этом сохранена обратная совместимость с предыдущими версиями.

### 1.1 Кадр 0x2A1 — Arm Status Feedback

* В Byte 2 («mode feedback») добавлено значение **0x04 `MOVE M`** — используется как feedback для **MIT-режима**.

### 1.2 Кадр 0x151 — Mode Control

* В Byte 1 (`MOVE mode`) добавлена команда **0x04 `MOVE M`** — включает MIT-режим.
* Добавлен **Byte 5** «Installation position»:
  * 0x00 — недействительно  
  * 0x01 — горизонтальная установка (upright)  
  * 0x02 — боковая установка слева  
  * 0x03 — боковая установка справа  
  (установка с кабелями, направленными назад)

### 1.3 Новые команды MIT-контроля (0x15A – 0x15F)

| Byte | Содержимое | Примечание |
|------|-----------|-----------|
| 0 | `Pos_ref` [bit15‒8] | uint8 |
| 1 | `Pos_ref` [bit7‒0] | uint8 |
| 2 | `Vel_ref` [bit11‒4] | uint8 |
| 3 | `Vel_ref` [bit3‒0] + `Kp` [bit11‒8] | uint8 |
| 4 | `Kp` [bit7‒0] (рек. 10) | uint8 |
| 5 | `Kd` [bit11‒4] (рек. 0.8) | uint8 |
| 6 | `Kd` [bit3‒0] + `T_ref` [bit7‒4] | uint8 |
| 7 | `T_ref` [bit3‒0] + CRC [bit3‒0] | uint8 |

### 1.4 Кадр 0x474 — Motor Angle Limit / Max Speed Set

Добавлено использование «невалидного» значения **0x7FFF**.

| Byte | Описание | Ед. | Комментарий |
|------|---------|-----|-------------|
| 0 | № привода (1-6) | uint8 |
| 1-2 | Max Angle Limit H/L | 0.1° | 0x7FFF = не менять |
| 3-4 | Min Angle Limit H/L | 0.1° | 0x7FFF = не менять |
| 5-6 | Max Joint Speed H/L | 0.001 rad/s | 0x7FFF = не менять |
| 7 | резерв | — | |

### 1.5 Кадр 0x475 — Joint Config

Также добавлены специальные значения **0xAE** / **0x7FFF**.

| Byte | Описание |
|------|----------|
| 0 | № привода (1-7; 7 = все) |
| 1 | «Set current pos as zero» — 0xAE |
| 2 | «Acc param valid» — 0xAE |
| 3-4 | Max Joint Acc H/L, 0.001 rad/s² (0x7FFF = не менять) |
| 5 | «Clear joint error» |
| 6-7 | резерв |

### 1.6 Кадр 0x477 — Arm Param Enquiry & Config

Новое значение **`param_enquiry = 0x04`** — запрос параметров **Gripper / Teaching Pendant**.

* Byte 0 — `param_enquiry`  
  0x01 — End V/Acc; 0x02 — Collision Protection; 0x03 — Trajectory Index; **0x04 — Gripper/Pendant Param**
* Byte 1 — `param_setting`  (0x01 — сброс End V/Acc; 0x02 — восстановить лимиты/скорости/ускорения по умолчанию)
* Byte 2 — настройки feedback 0x48X (0x00/0x01/0x02)
* Byte 3 — «End-load param effective» (0xAE)
* Byte 4 — `set_end_load` (0x00 — no-load; 0x01 — half-load; 0x02 — full-load)

### 1.7 Кадр 0x479 — End Vel/Acc Param Set

Во все поля допускается «невалидное» значение **0x7FFF**.

### 1.8 Новый кадр 0x47D — Gripper / Teaching Pendant Param Config

* Byte 0 — коэффициент хода Teaching Pendant, 100–200 % (по умолчанию 100 %).  
  Применяется только к master-руке в режиме master-slave и масштабирует движение для slave-руки.
* Byte 1 — предел хода Gripper/Pendant (мм): 0 — недейств. / 70 — маленький гр. / 100 — большой гр.
* Byte 2-7 — резерв

### 1.9 Новый кадр 0x47E — Gripper / Teaching Pendant Param Feedback

Возвращает фактические значения параметров из 0x47D.

---

## 2 Интерфейс SDK

Класс **`C_PiperInterface`** (V1) сохранён. Добавлен самостоятельный класс **`C_PiperInterface_V2`**. Несмотря на дублирование, это обеспечивает полную независимость версий.

Дополнительные методы V2:

| Метод | Тип | Описание | Вызов | Параметры | Возврат |
|-------|-----|----------|-------|-----------|---------|
| `GetGripperTeachingPendantParamFeedback` | Getter | Получить кадр 0x47E (коэфф. хода + предел хода) | `obj.GetGripperTeachingPendantParamFeedback()` | — | `self.__feedback_gripper_teaching_pendant_param` |
| `MotorMaxSpdSet` | Ctrl | Установить максимальную скорость мотора | внешний | `motor_num`, `max_joint_spd` | — |
| `__JointMitCtrl` | Ctrl (внутр.) | MIT-команда 0x15A-0x15F | внутр. | см. сигнатуру | — |
| `JointMitCtrl` | Ctrl | Публичная обёртка к MIT-командам | внешний | `motor_num`, `pos_ref`, `vel_ref`, `kp`, `kd`, `t_ref` | — |
| `GripperTeachingPendantParamConfig` | Ctrl | Отправка кадра 0x47D | внешний | `teaching_range_per`, `max_range_config` | — |
