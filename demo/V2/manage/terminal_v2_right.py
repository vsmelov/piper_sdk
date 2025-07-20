from demo.V2.manage.terminal_v2 import PiperTerminal
from demo.V2.settings import CAN_RIGHT


class PiperTerminalRight(PiperTerminal):
    """Specialised PiperTerminal that operates the RIGHT arm only."""

    def __init__(self):
        # Disable left arm completely by passing None
        super().__init__(left_can=None, right_can=CAN_RIGHT)


if __name__ == "__main__":
    PiperTerminalRight().repl() 