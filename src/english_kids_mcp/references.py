"""Optional reference lexicon loader for age/goal word lists."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


def _read_words(path: Path) -> List[str]:
    if not path.exists():
        return []
    words: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        words.append(entry)
    return words


@dataclass(slots=True)
class ReferenceLexicon:
    """Look up optional words organised by age band and goal."""

    base_path: Path
    _cache: Dict[Tuple[str, str], List[str]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.base_path = self.base_path.expanduser().resolve()

    def words_for(self, age_band: str, goal: str) -> List[str]:
        """Return customised vocabulary for an age band/goal combination."""

        key = (age_band, goal)
        if key in self._cache:
            return self._cache[key]

        candidates: List[Path] = []
        candidates.append(self.base_path / age_band / goal / "words.txt")
        candidates.append(self.base_path / age_band / "words.txt")
        candidates.append(self.base_path / goal / "words.txt")

        collected: List[str] = []
        for candidate in candidates:
            collected.extend(_read_words(candidate))

        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: List[str] = []
        for word in collected:
            if word not in seen:
                seen.add(word)
                unique.append(word)

        self._cache[key] = unique
        return unique

    def sample(self, age_band: str, goal: str, limit: int = 3) -> List[str]:
        """Return up to ``limit`` lexical hints for UI display."""

        words = self.words_for(age_band, goal)
        return words[:limit]


__all__ = ["ReferenceLexicon"]
