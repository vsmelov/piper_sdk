from __future__ import annotations

"""Scene composition support.

A *Scene* is a parallel timeline for two arms consisting of Track or Pause elements.
Saved in JSON under manage/scenes/ directory.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Union, Literal, Dict, Any

BASE_DIR = Path(__file__).parent  # manage/
SCENE_DIR = BASE_DIR / "scenes"
SCENE_DIR.mkdir(exist_ok=True)

ElementType = Literal["track", "pause"]

@dataclass
class SceneElement:
    type: ElementType
    # for type == "track"
    name: str | None = None  # track base name without .json
    # for type == "pause"
    duration: float | None = None  # seconds

    def to_json(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "SceneElement":
        t = obj.get("type")
        if t not in ("track", "pause"):
            raise ValueError("Unknown element type")
        return cls(type=t, name=obj.get("name"), duration=obj.get("duration"))

@dataclass
class Scene:
    name: str  # scene__xxx
    left: List[SceneElement]
    right: List[SceneElement]
    version: str = "scene_v1"

    # ---------------- files ----------------
    @property
    def path(self) -> Path:
        return SCENE_DIR / f"{self.name}.json"

    # ---------------- serialization ----------------
    def to_json(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "left": [el.to_json() for el in self.left],
            "right": [el.to_json() for el in self.right],
        }

    def save(self):
        self.path.write_text(json.dumps(self.to_json(), indent=2))

    # ---------------- helpers ----------------
    @classmethod
    def load(cls, name: str) -> "Scene":
        path = SCENE_DIR / f"{name}.json"
        obj = json.loads(path.read_text())
        left = [SceneElement.from_json(e) for e in obj["left"]]
        right = [SceneElement.from_json(e) for e in obj["right"]]
        return cls(name=name, left=left, right=right, version=obj.get("version", "scene_v1"))

    def timeline_with_times(self):
        """Return lists of tuples (element, start, end) per arm."""
        res = {}
        for arm_name, seq in (("left", self.left), ("right", self.right)):
            t = 0.0
            arr = []
            for el in seq:
                if el.type == "pause":
                    start = t
                    end = t + (el.duration or 0)
                    arr.append((el, start, end))
                    t = end
                else:
                    # assume track duration unknown; mark end as None for now
                    arr.append((el, t, None))
            res[arm_name] = arr 