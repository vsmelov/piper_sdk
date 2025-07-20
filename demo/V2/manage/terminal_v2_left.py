from demo.V2.manage.terminal_v2 import PiperTerminal
from demo.V2.settings import CAN_LEFT


class PiperTerminalLeft(PiperTerminal):
    """Specialised PiperTerminal that works with the LEFT arm only.

    All right-arm initialisation is disabled so that the instance touches only
    the CAN bus assigned to the left robot arm. Intended to be launched in a
    dedicated OS process to avoid GIL contention between two arms.
    """

    def __init__(self):
        # Disable right arm completely by passing None
        super().__init__(left_can=CAN_LEFT, right_can=None)


if __name__ == "__main__":
    PiperTerminalLeft().repl() 