"""Dataclasses describing MCP payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class Activity:
    prompt_text: str
    target_phrase: str
    rubric: str
    timebox_sec: int
    item_id: str
    scaffold_cn: Optional[str] = None
    lexicon_words: Optional[List[str]] = None


@dataclass(slots=True)
class Award:
    xp: int
    stickers: int
    message: Optional[str] = None


@dataclass(slots=True)
class Feedback:
    feedback_text: str
    mastery_delta: int
    next_activity: Optional[Activity] = None
    scaffold_cn: Optional[str] = None
    award: Optional[Award] = None
    review_card: Optional[Activity] = None


@dataclass(slots=True)
class SessionSnapshot:
    session_id: str
    user_id: str
    age_band: str
    goal: str
    locale: str
    xp: int
    stickers: int
    attempts: List[dict] = field(default_factory=list)


@dataclass(slots=True)
class ProgressSummary:
    cefr_band_estimate: str
    xp: int
    stickers: int
    recent_items: List[str]
    due_reviews: int


__all__ = [
    "Activity",
    "Award",
    "Feedback",
    "SessionSnapshot",
    "ProgressSummary",
]
