"""Curriculum loading and activity helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass(slots=True)
class CurriculumItem:
    track: str
    item_id: str
    min_age: int
    max_age: int
    target: str
    patterns: Sequence[str]

    def for_prompt(self, age_band: str) -> str:
        """Return a pattern trimmed for the age band."""

        import random

        pattern = random.choice(list(self.patterns))
        max_tokens = 8 if max_age_from_band(age_band) <= 6 else 12
        tokens = pattern.split()
        if len(tokens) <= max_tokens:
            return pattern
        return " ".join(tokens[:max_tokens])


def parse_age_range(text: str) -> tuple[int, int]:
    lo, hi = text.split("-")
    return int(lo), int(hi)


def min_age_from_band(band: str) -> int:
    return parse_age_range(band)[0]


def max_age_from_band(band: str) -> int:
    return parse_age_range(band)[1]


class Curriculum:
    """Static curriculum container."""

    def __init__(self, items: Iterable[CurriculumItem]):
        self._items: List[CurriculumItem] = list(items)

    @classmethod
    def from_json(cls, path: Path) -> "Curriculum":
        data = json.loads(path.read_text(encoding="utf-8"))
        items: List[CurriculumItem] = []
        for track, track_items in data.get("tracks", {}).items():
            for entry in track_items:
                age_lo, age_hi = parse_age_range(entry["age"])
                items.append(
                    CurriculumItem(
                        track=track,
                        item_id=entry["id"],
                        min_age=age_lo,
                        max_age=age_hi,
                        target=entry["target"],
                        patterns=tuple(entry.get("patterns", [])),
                    )
                )
        return cls(items)

    def for_goal_and_age(self, goal: str, age_band: str) -> List[CurriculumItem]:
        lo, hi = parse_age_range(age_band)
        return [
            item
            for item in self._items
            if item.track == goal and item.min_age <= hi and item.max_age >= lo
        ]

    def tracks(self) -> List[str]:
        return sorted({item.track for item in self._items})

    def all_items(self) -> List[CurriculumItem]:
        return list(self._items)


__all__ = ["Curriculum", "CurriculumItem", "min_age_from_band", "max_age_from_band"]
