"""Simple spaced repetition scheduling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict


@dataclass(slots=True)
class SRSItem:
    ease: float = 1.3
    interval_days: float = 0.0
    due_at: datetime = datetime.fromtimestamp(0)
    streak: int = 0

    def schedule(self, outcome: str, now: datetime) -> None:
        """Update scheduling according to the outcome."""

        if outcome == "fail":
            self.ease = 1.3
            self.interval_days = 0.0
            self.due_at = now
            self.streak = 0
            return

        if outcome == "partial":
            self.interval_days = max(1.0, max(self.interval_days, 1.0) * 0.8)
            self.due_at = now + timedelta(days=self.interval_days)
            return

        if outcome == "pass":
            self.ease = min(self.ease + 0.05, 2.5)
            interval = max(1.0, self.interval_days if self.interval_days else 1.0)
            interval *= self.ease
            self.interval_days = interval
            self.due_at = now + timedelta(days=interval)
            self.streak += 1


class SRSState(dict[str, SRSItem]):
    """Dictionary-like wrapper storing SRS metadata per item."""

    @classmethod
    def from_dict(cls, payload: Dict[str, Dict[str, float]]) -> "SRSState":
        state = cls()
        for item_id, data in payload.items():
            state[item_id] = SRSItem(
                ease=float(data.get("ease", 1.3)),
                interval_days=float(data.get("interval_days", 0.0)),
                due_at=datetime.fromtimestamp(float(data.get("due_at", 0.0))),
                streak=int(data.get("streak", 0)),
            )
        return state

    def to_dict(self) -> Dict[str, Dict[str, float]]:
        return {
            item_id: {
                "ease": item.ease,
                "interval_days": item.interval_days,
                "due_at": item.due_at.timestamp(),
                "streak": item.streak,
            }
            for item_id, item in self.items()
        }


__all__ = ["SRSItem", "SRSState"]
