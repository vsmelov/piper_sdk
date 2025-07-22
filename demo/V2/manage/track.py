from __future__ import annotations

"""Track abstraction layer for PiperTerminal.

Provides:
    - TrackBase: common API.
    - TrackV1  : legacy format (list[list[int]] in JSON + optional *.details.json).
    - TrackV2  : enhanced format with per-point timestamps embedded into the
                 main JSON file and a top-level version tag.

The public API intentionally stays minimal and stable so that other parts of
codebase interact only with TrackBase class methods.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field

# Directory layout is the same as used by terminal_v2.py
BASE_DIR = Path(__file__).parent  # manage/
TRACK_DIR = BASE_DIR / "tracks"
TRACK_DIR.mkdir(exist_ok=True)

# ------------------------------ data structures ------------------------------
@dataclass
class TrackPoint:
    """Rich representation of a single trajectory sample.

    Many fields may be empty depending on recording mode (e.g. legacy v1 tracks
    or SAFE recordings that do not store full telemetry)."""

    coordinates_timestamp: float
    coordinates: List[int]
    details_timestamp: float

    motor_speed_rpm: List[int]
    motor_current_ma: List[int]
    voltage_mv: List[int]
    motor_pos_deg001: List[int]
    motor_effort_mNm: List[int]
    foc_temp_c: List[int]
    motor_temp_c: List[int]
    bus_current_ma: List[int]


class TrackBase:
    """Common interface for trajectory files."""

    version: str = "v1"

    def __init__(self, name: str) -> None:
        self.name = name  # e.g. "left__wave"

    # ------------------------------------------------------------------ paths
    @property
    def path(self) -> Path:
        return TRACK_DIR / f"{self.name}.json"

    @property
    def details_path(self) -> Path:
        return TRACK_DIR / f"{self.name}.details.json"

    # ----------------------------------------------------------------- helpers
    @property
    def points(self) -> List[List[int]]:  # noqa: D401 – property for API parity
        """Return list of 7-length integer lists (deg001 units)."""
        raise NotImplementedError

    @property
    def timestamps(self) -> List[float]:
        """Per-point timestamps (seconds, epoch). May be empty."""
        raise NotImplementedError

    @property
    def details(self) -> List[Dict[str, Any]]:
        """Per-point telemetry details. May be empty list."""
        try:
            if self.details_path.exists():
                return json.loads(self.details_path.read_text())
        except Exception:
            # degraded mode – caller will handle
            pass
        return []

    @property
    def track_points(self) -> List["TrackPoint"]:  # noqa: D401 – property for API
        """Return the trajectory as a list of *TrackPoint* objects."""
        raise NotImplementedError

    # ----------------------------------------------------------------- factories
    @classmethod
    def read_track(cls, name: str) -> "TrackBase":
        """Auto-detect json format and return appropriate Track* instance."""
        path = TRACK_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(path)

        try:
            obj = json.loads(path.read_text())
        except Exception as exc:
            raise ValueError(f"Failed to read track {name}: {exc}") from exc

        # -------------------------------- new v3 detection -----------------------------
        if isinstance(obj, dict) and obj.get("version") == TrackV3Timed.version:
            return TrackV3Timed(name)
        # -------------------------------- existing v2 detection -------------------------
        if isinstance(obj, dict) and obj.get("version") == "v2.0":
            return TrackV2(name)
        # Fallback to legacy v1 format
        return TrackV1(name)

    # ----------------------------------------------------------------- writers
    @classmethod
    def write_from_record(
        cls,
        name: str,
        points_with_ts: List[Tuple[List[int], float]],
        details: List[Dict[str, Any]],
    ) -> None:
        """Persist a newly recorded track using *cls* format.

        Args:
            name: track base filename without extension.
            points_with_ts: list of tuples (pt, ts) where *pt* is 7-length list
                and *ts* is float timestamp.
            details: telemetry list accumulated during recording.
        """
        raise NotImplementedError


class TrackV1(TrackBase):
    """Legacy simple JSON format (list of lists)."""

    version: str = "v1"

    # ----------------------------- cached raw ------------------------
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._data: List[List[int]] = json.loads(self.path.read_text())

    # -------------------------------- API ---------------------------

    @property
    def track_points(self) -> List[TrackPoint]:
        details = self.details
        if len(details) != len(self._data):
            raise ValueError("Details length must match points length for v1 track")

        combined: List[TrackPoint] = []
        for idx, pt in enumerate(self._data):
            if idx >= len(details):
                raise ValueError("Missing details entry for point index {idx}")
            det: Dict[str, Any] = details[idx]
            if "ts" not in det:
                raise ValueError("Missing 'ts' in details for v1 track")
            coords_ts = det["ts"]
            combined.append(
                TrackPoint(
                    coordinates_timestamp=coords_ts,
                    coordinates=pt,
                    details_timestamp=det["ts"],
                    motor_speed_rpm=det["motor_speed_rpm"],
                    motor_current_ma=det["motor_current_ma"],
                    voltage_mv=det["voltage_mv"],
                    motor_pos_deg001=det["motor_pos_deg001"],
                    motor_effort_mNm=det["motor_effort_mNm"],
                    foc_temp_c=det["foc_temp_c"],
                    motor_temp_c=det["motor_temp_c"],
                    bus_current_ma=det["bus_current_ma"],
                )
            )
        return combined

    # ----------------------------- writers --------------------------
    @classmethod
    def write_from_record(
        cls,
        name: str,
        points_with_ts: List[Tuple[List[int], float]],
        details: List[Dict[str, Any]],
    ) -> None:
        pts_only = [pt for pt, _ in points_with_ts]
        path = TRACK_DIR / f"{name}.json"
        path.write_text(json.dumps(pts_only))

        details_path = TRACK_DIR / f"{name}.details.json"
        details_path.write_text(json.dumps(details))


class TrackV2(TrackBase):
    """Enhanced format with embedded timestamps and version tag."""

    version: str = "v2.0"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        obj = json.loads(self.path.read_text())
        if not (isinstance(obj, dict) and obj.get("version") == self.version):
            raise ValueError(f"File {self.path} is not a v2.0 track")
        self._raw: Dict[str, Any] = obj
        self._pts: List[Dict[str, Any]] = obj.get("points", [])

    # -------------------------------- API ---------------------------
    @property
    def points(self) -> List[List[int]]:
        """Raw coordinate list retained for backwards compatibility (internal)."""
        return [item["pt"] for item in self._pts]

    @property
    def timestamps(self) -> List[float]:
        return [item["ts"] for item in self._pts]

    @property
    def details(self) -> List[Dict[str, Any]]:
        # Prefer external details file (contains telemetry). If none exists –
        # generate minimal details with only timestamp field so playback timing works.
        ext_details = super().details
        if ext_details:
            return ext_details
        return [{"ts": ts} for ts in self.timestamps]

    @property
    def track_points(self) -> List[TrackPoint]:
        details = self.details
        combined: List[TrackPoint] = []
        for idx, item in enumerate(self._pts):
            if "pt" not in item or "ts" not in item:
                raise ValueError("Each point entry must contain 'pt' and 'ts' in v2 track")
            pt_coords = item["pt"]
            coords_ts = item["ts"]
            if idx >= len(details):
                raise ValueError("Missing details entry for point index {idx}")
            det: Dict[str, Any] = details[idx]
            if "ts" not in det:
                raise ValueError("Missing 'ts' in details for v2 track")
            combined.append(
                TrackPoint(
                    coordinates_timestamp=coords_ts,
                    coordinates=pt_coords,
                    details_timestamp=det["ts"],
                    motor_speed_rpm=det["motor_speed_rpm"],
                    motor_current_ma=det["motor_current_ma"],
                    voltage_mv=det["voltage_mv"],
                    motor_pos_deg001=det["motor_pos_deg001"],
                    motor_effort_mNm=det["motor_effort_mNm"],
                    foc_temp_c=det["foc_temp_c"],
                    motor_temp_c=det["motor_temp_c"],
                    bus_current_ma=det["bus_current_ma"],
                )
            )
        return combined

    # ----------------------------- writers --------------------------
    @classmethod
    def write_from_record(
        cls,
        name: str,
        points_with_ts: List[Tuple[List[int], float]],
        details: List[Dict[str, Any]],
    ) -> None:
        path = TRACK_DIR / f"{name}.json"
        content = {
            "version": cls.version,
            "points": [
                {"pt": pt, "ts": ts} for pt, ts in points_with_ts
            ],
        }
        path.write_text(json.dumps(content))
        details_path = TRACK_DIR / f"{name}.details.json"
        details_path.write_text(json.dumps(details)) 

# ------------------------------ NEW – Timed control-point track ------------------------------
class TrackV3Timed(TrackBase):
    """Trajectory represented as a sequence of control points with per-segment duration.

    The JSON structure is::
        {
          "version": "v3.0",
          "points": [
            {"pt": [..7 ints..], "duration": 0},           # first point, duration ignored
            {"pt": [..], "duration": 2.5},                 # seconds to move from previous → current
            ...
          ]
        }
    """

    version: str = "v3.0"

    # ----------------------------- cached raw ------------------------
    def __init__(self, name: str) -> None:
        super().__init__(name)
        obj = json.loads(self.path.read_text())
        if not (isinstance(obj, dict) and obj.get("version") == self.version):
            raise ValueError(f"File {self.path} is not a v3.0 timed track")
        self._raw = obj
        self._pts = obj.get("points", [])
        if not isinstance(self._pts, list):
            raise ValueError("'points' must be a list in v3 track")
        # Basic sanity check
        for idx, item in enumerate(self._pts):
            if "pt" not in item or "duration" not in item:
                raise ValueError(f"Each point entry must contain 'pt' and 'duration' (idx={idx})")

    @property
    def speed_up(self):
        if self.name == 'left__open_door':
            return 0
        elif self.name == 'left__lopatka1':
            return 0.15
        elif self.name == 'right__open_door':
            return 0.3
        elif self.name == 'right__meat':
            return 0.2
        elif self.name == 'right__tomat':
            return 0.47
        elif self.name == 'right__salt':
            return 0.2
        elif self.name == 'right__lapsha':
            return 0.3
        elif self.name == 'right__cheese':
            return 0.15
        elif self.name == 'right__close_door':
            return 0.1
        elif self.name == 'left__close_door':
            return 0.25
        elif self.name == 'left__colba1':
            return 0.3
        elif self.name == 'left__lopatka2_open':
            return 0.6
        elif self.name == 'left__lopatka2_mix':
            return 0.6
        elif self.name == 'left__lopatka2_close':
            return 0.6
        elif self.name == 'left__lopatka2_open_faster':
            return 0.6
        elif self.name == 'left__lopatka2_mix_faster':
            return 0.6
        elif self.name == 'left__lopatka2_close_faster':
            return 0.6
        elif self.name == 'left__colba_suhtrav':
            return 0
        elif self.name == 'left__colba_svezhtrav':
            return 0
        else:
            return 0

    # -------------------------------- helpers -----------------------
    @property
    def points(self) -> List[List[int]]:
        return [item["pt"] for item in self._pts]

    @property
    def durations(self) -> List[float]:
        return [float(item["duration"]) for item in self._pts]

    # For compatibility generate cumulative timestamps
    @property
    def timestamps(self) -> List[float]:
        ts: List[float] = []
        acc = 0.0
        for dur in self.durations:
            acc += float(dur)
            ts.append(acc)
        # First timestamp usually equals first duration (could be 0)
        return ts

    @property
    def track_points(self) -> List["TrackPoint"]:
        # Timed tracks do not store telemetry; generate stub TrackPoint objects
        stubs: List[TrackPoint] = []
        for ts_val, pt in zip(self.timestamps, self.points):
            stubs.append(
                TrackPoint(
                    coordinates_timestamp=ts_val,
                    coordinates=pt,
                    details_timestamp=ts_val,
                    motor_speed_rpm=[0]*6,
                    motor_current_ma=[0]*6,
                    voltage_mv=[0]*6,
                    motor_pos_deg001=[0]*6,
                    motor_effort_mNm=[0]*6,
                    foc_temp_c=[0]*6,
                    motor_temp_c=[0]*6,
                    bus_current_ma=[0]*6,
                )
            )
        return stubs

    # ----------------------------- writers --------------------------
    @classmethod
    def write_from_points(
        cls,
        name: str,
        points: List[List[int]],
        durations: List[float],
    ) -> None:
        if len(points) != len(durations):
            raise ValueError("points and durations must be same length")
        path = TRACK_DIR / f"{name}.json"
        payload = {
            "version": cls.version,
            "points": [
                {"pt": pt, "duration": float(dur)} for pt, dur in zip(points, durations)
            ],
        }
        path.write_text(json.dumps(payload, indent=2)) 