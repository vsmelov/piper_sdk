from __future__ import annotations

"""IPC helpers for running each robot arm in its own process.

Usage example:

    from demo.V2.manage.arm_ipc import ArmProxy
    from demo.V2.settings import CAN_LEFT, CAN_RIGHT

    left = ArmProxy(CAN_LEFT)
    right = ArmProxy(CAN_RIGHT)

    # Play tracks on each arm in parallel processes
    left.cmd_play("left__wave")
    right.cmd_play("right__wave")

    left.shutdown()
    right.shutdown()

The proxy forwards *any* attribute access (method call) to the background
`ArmWorkerProcess`. Therefore you can call the same public API methods that
`PiperTerminal` exposes (`cmd_play`, `cmd_record`, `play_tracks`, ...).
"""

import logging
import traceback
from multiprocessing import Process, Pipe
from multiprocessing.connection import Connection
from typing import Any, Dict


class _ArmWorkerProcess(Process):
    """Background process hosting a *single-arm* PiperTerminal.

    It listens on a *Connection* for JSON-serialisable command dictionaries and
    executes them sequentially. Designed to be started only via *ArmProxy*.
    """

    def __init__(self, can_name: str, conn: Connection):
        super().__init__(daemon=True)
        self._can_name = can_name
        self._conn = conn

    # ---------------------------------------------------------------------
    # Process entry-point
    # ---------------------------------------------------------------------
    def run(self):  # noqa: D401 – imperative mood
        # Minimal logging config inside the child so that prints are visible.
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(processName)s:%(lineno)d - %(message)s",
        )

        try:
            # Import locally to keep fork-safety (SDK may init on import).
            from demo.V2.manage.terminal_v2 import PiperTerminal

            term = PiperTerminal(left_can=self._can_name, right_can=None)
            logging.info("Arm worker started – CAN=%s", self._can_name)
        except Exception as exc:  # noqa: BLE001 – inside child
            logging.exception("FAILED to initialise PiperTerminal: %s", exc)
            # We stay alive to send back error explanations, but many commands
            # will obviously fail.
            term = None  # type: ignore[assignment]

        while True:
            try:
                msg: Dict[str, Any] = self._conn.recv()
            except EOFError:
                break  # parent side closed

            # ------------------------------------------------------------
            cmd_type = msg.get("cmd")
            if cmd_type == "shutdown":
                if term:
                    try:
                        term.shutdown()
                    except Exception:
                        logging.exception("shutdown error")
                break

            if cmd_type == "call":
                method_name: str = msg.get("method")  # type: ignore[arg-type]
                args = msg.get("args", [])
                kwargs = msg.get("kwargs", {})
                call_id = msg.get("id")

                if term is None:
                    self._conn.send({"ok": False, "error": "terminal init failed", "id": call_id})
                    continue

                try:
                    result = getattr(term, method_name)(*args, **kwargs)
                    self._conn.send({"ok": True, "result": result, "id": call_id})
                except Exception as exc:  # noqa: BLE001
                    tb = traceback.format_exc()
                    logging.error("Exception in worker method %s: %s", method_name, exc)
                    self._conn.send({"ok": False, "error": repr(exc), "trace": tb, "id": call_id})
            else:
                logging.warning("Unknown message: %s", msg)

        self._conn.close()
        logging.info("Arm worker stopped – CAN=%s", self._can_name)


class ArmProxy:
    """Client-side proxy that talks to an *ArmWorkerProcess* via Pipe.

    It behaves *похожим* образом на `PiperTerminal`: любые вызовы метода,
    отсутствующего в самом `ArmProxy`, автоматически маршаллируются в процесс
   -воркер и выполняются там.
    """

    def __init__(self, can_name: str):
        parent, child = Pipe()
        self._conn = parent
        # Pyright may complain about generic variance; safe to ignore.
        self._proc = _ArmWorkerProcess(can_name, child)  # type: ignore[arg-type]
        self._proc.start()
        self._req_id = 0  # simple incremental correlation id

    # ------------------------- low-level helpers -------------------------
    def _send_call(self, method: str, *args, **kwargs):
        self._req_id += 1
        curr_id = self._req_id
        self._conn.send({
            "cmd": "call",
            "method": method,
            "args": args,
            "kwargs": kwargs,
            "id": curr_id,
        })
        resp = self._conn.recv()
        if resp.get("id") != curr_id:
            raise RuntimeError("out-of-order IPC reply")
        if resp.get("ok"):
            return resp.get("result")
        raise RuntimeError(f"Worker error: {resp.get('error')}\n{resp.get('trace', '')}")

    # ------------------------- public helpers ---------------------------
    def shutdown(self):
        """Gracefully terminate the worker process."""
        if not self._proc.is_alive():  # already dead
            return
        try:
            self._conn.send({"cmd": "shutdown"})
        except (BrokenPipeError, EOFError):
            pass
        self._conn.close()
        self._proc.join(timeout=3)

    # ------------------ dynamic dispatch magic --------------------------
    def __getattr__(self, item: str):  # noqa: D401 – it's fine
        """Return a callable forwarding the method *item* to the worker."""
        return lambda *args, **kwargs: self._send_call(item, *args, **kwargs)

    # Ensure we clean up the worker if ArmProxy GC-ed
    def __del__(self):
        try:
            self.shutdown()
        except Exception:  # noqa: BLE001
            pass 