from piper_sdk import *
from demo.V2.settings import CAN_LEFT, CAN_RIGHT


USE_CAN_NAME = CAN_RIGHT

if __name__ == "__main__":
    piper = C_PiperInterface_V2(USE_CAN_NAME)
    piper.ConnectPort()
    piper.DisableArm(7)
    # piper.GripperCtrl(0, 1000, 0x02, 0)
