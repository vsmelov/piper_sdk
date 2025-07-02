#!/bin/bash

# 1. Отключить интерфейс, если он остался висеть:
sudo ip link set can0 down 2>/dev/null

# 2. Настроить интерфейс с нужной скоростью (1 Мбит/с — стандарт для Piper):
sudo ip link set can0 type can bitrate 1000000

# 3. Включить интерфейс:
sudo ip link set can0 up

# 4. Проверка (необязательно, но полезно):
ip link show can0