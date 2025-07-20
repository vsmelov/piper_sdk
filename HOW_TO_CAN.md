#!/bin/bash

sudo ethtool -i can0 | grep bus

bash can_activate.sh can0 1000000 "3-3.2:1.0"
bash can_activate.sh can1 1000000 "3-3.3:1.0"
