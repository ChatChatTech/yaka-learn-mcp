"""Utterance evaluation heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple


TOKEN_RE = re.compile(r"[a-zA-Z']+")


@dataclass(slots=True)
class EvaluationResult:
    meaning: int
    form: int
    pronunciation: int
    fluency: int

    @property
    def total(self) -> int:
        return self.meaning + self.form + self.pronunciation + self.fluency


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text)]


def compare_tokens(predicted: list[str], target: list[str]) -> Tuple[int, int]:
    """Return (meaning_score, form_score)."""

    if not predicted:
        return 0, 0

    overlap = len({token for token in predicted if token in target})
    meaning = 2 if overlap >= max(1, len(target) // 2) else (1 if overlap else 0)
    form = 2 if predicted == target else (1 if overlap else 0)
    return meaning, form


def evaluate_utterance(utterance: str, target_phrase: str) -> EvaluationResult:
    """Heuristic scoring with small rewards for near matches."""

    utter_tokens = tokenize(utterance)
    target_tokens = tokenize(target_phrase)
    meaning, form = compare_tokens(utter_tokens, target_tokens)

    pronunciation = 1 if utter_tokens else 0
    fluency = 1 if utterance and not utterance.strip().endswith("...") else 0

    return EvaluationResult(meaning, form, pronunciation, fluency)


def score_to_outcome(score: int) -> str:
    if score <= 2:
        return "fail"
    if score <= 4:
        return "partial"
    return "pass"


def mastery_delta_for_outcome(outcome: str) -> int:
    if outcome == "fail":
        return -1
    if outcome == "partial":
        return 0
    return 2


def xp_for_outcome(outcome: str) -> int:
    return 5 if outcome == "pass" else (2 if outcome == "partial" else 0)


__all__ = [
    "EvaluationResult",
    "evaluate_utterance",
    "score_to_outcome",
    "mastery_delta_for_outcome",
    "xp_for_outcome",
]
