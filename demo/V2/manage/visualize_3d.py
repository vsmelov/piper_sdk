import math
import time
import logging
from threading import Thread

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 – needed for 3-D

from interface.piper_interface_v2 import C_PiperInterface_V2 as SDK
from kinematics.piper_fk import C_PiperForwardKinematics
from demo.V2.settings import CAN_NAME

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s")


class LiveArmVisualizer:
    """Very small 3-D real-time visualizer for the 7-DOF Piper arm.

    It connects to the arm, continuously fetches joint angles, computes forward
    kinematics and draws a stick model in a matplotlib 3-D plot.
    """

    POLL_HZ = 20  # telemetry polling frequency

    def __init__(self):
        self.arm = SDK.get_instance(CAN_NAME)
        try:
            self.arm.ConnectPort()
            LOG.info("CAN port connected for visualizer.")
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to open CAN – running in demo mode with random pose: %s", exc)
            self.arm = None

        self.fk = C_PiperForwardKinematics()

        # Matplotlib 3-D figure
        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.line, = self.ax.plot([], [], [], "-o", lw=2)

        # A simple cubic workspace box ~1×1×1 m
        lim = 600  # mm
        self.ax.set_xlim(-lim, lim)
        self.ax.set_ylim(-lim, lim)
        self.ax.set_zlim(0, lim * 2 / 1.5)  # type: ignore[attr-defined]
        self.ax.set_xlabel("X (mm)")
        self.ax.set_ylabel("Y (mm)")
        self.ax.set_zlabel("Z (mm)")  # type: ignore[attr-defined]
        self.ax.set_title("Piper arm – live view")

    # ---------------------------- data retrieval ----------------------------
    def _read_joints_deg001(self):
        """Return current 6 joint angles in SDK units (0.001°)."""
        if self.arm is None:
            # Demo pose: slow circular motion
            t = time.time()
            return [int(1000 * 30 * math.sin(t + i)) for i in range(6)]
        js = self.arm.GetArmJointMsgs().joint_state
        return [js.joint_1, js.joint_2, js.joint_3, js.joint_4, js.joint_5, js.joint_6]

    # ---------------------------- matplotlib anim --------------------------
    def _update(self, frame):  # noqa: D401 – matplotlib API
        joints_deg001 = self._read_joints_deg001()
        joints_rad = [math.radians(d / 1000) for d in joints_deg001]
        positions = self.fk.CalFK(joints_rad)  # 6×[x,y,z,…]

        xs, ys, zs = [0], [0], [0]  # base at origin
        for pos in positions:
            xs.append(pos[0])
            ys.append(pos[1])
            zs.append(pos[2])

        self.line.set_data(xs, ys)
        self.line.set_3d_properties(zs)  # type: ignore[attr-defined]
        return self.line,

    def run(self):
        _ = FuncAnimation(self.fig, self._update, interval=1000 / self.POLL_HZ, blit=False)
        plt.show()
        # On close – disconnect
        if self.arm:
            try:
                self.arm.DisconnectPort()
            except Exception:
                pass


if __name__ == "__main__":
    LiveArmVisualizer().run() 