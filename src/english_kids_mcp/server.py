"""Kid English MCP server implementing the tool surface described in the spec."""

from __future__ import annotations

import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .config import Settings
from .curriculum import Curriculum, CurriculumItem
from .db import SQLiteStore
from .evaluation import (
    evaluate_utterance,
    mastery_delta_for_outcome,
    score_to_outcome,
    xp_for_outcome,
)
from .references import ReferenceLexicon
from .schemas import Activity, Award, Feedback, ProgressSummary, SessionSnapshot


TOOL_DESCRIPTIONS = {
    "start_session": "Create or resume a tutoring session for a learner.",
    "next_activity": "Fetch the next speaking prompt for the active session.",
    "submit_utterance": "Score the learner utterance and advance the session loop.",
    "set_goal": "Switch the curriculum goal mid-session.",
    "get_progress": "Summarise the learner progress for caretakers.",
    "save_note_for_parent": "Attach a Chinese note for parents to review.",
}


def _tool_input_schema(name: str) -> dict:
    if name == "start_session":
        return {
            "type": "object",
            "required": ["user_id", "age_band", "goal"],
            "properties": {
                "user_id": {"type": "string", "description": "Stable user identifier"},
                "age_band": {
                    "type": "string",
                    "enum": ["3-4", "5-6", "7-8", "9-10"],
                },
                "goal": {
                    "type": "string",
                    "enum": [
                        "greetings",
                        "daily-life",
                        "phonics",
                        "colors-numbers",
                        "custom",
                    ],
                },
                "locale": {
                    "type": "string",
                    "enum": ["zh-CN", "zh-TW"],
                    "default": "zh-CN",
                },
            },
        }
    if name == "next_activity":
        return {
            "type": "object",
            "required": ["session_id"],
            "properties": {"session_id": {"type": "string"}},
        }
    if name == "submit_utterance":
        return {
            "type": "object",
            "required": ["session_id", "utterance_text"],
            "properties": {
                "session_id": {"type": "string"},
                "utterance_text": {"type": "string"},
                "latency_ms": {"type": "integer", "minimum": 0},
            },
        }
    if name == "set_goal":
        return {
            "type": "object",
            "required": ["session_id", "goal"],
            "properties": {
                "session_id": {"type": "string"},
                "goal": {
                    "type": "string",
                    "enum": [
                        "greetings",
                        "daily-life",
                        "phonics",
                        "colors-numbers",
                        "custom",
                    ],
                },
            },
        }
    if name == "get_progress":
        return {
            "type": "object",
            "required": ["user_id"],
            "properties": {"user_id": {"type": "string"}},
        }
    if name == "save_note_for_parent":
        return {
            "type": "object",
            "required": ["session_id", "note_cn"],
            "properties": {
                "session_id": {"type": "string"},
                "note_cn": {"type": "string"},
            },
        }
    raise KeyError(f"Unknown tool {name}")
from .srs import SRSItem, SRSState
from .vectorstore import VectorItem, VectorStore


SYSTEM_PROMPT = (
    "You are a warm English-speaking kids' tutor for Chinese learners aged 3–10."
    " Output SHORT, SIMPLE English lines for the child to speak back."
    " Never exceed 2 short sentences per turn for ages ≤6, or 3 sentences for older kids."
    " Use Chinese only for a separate hint field when asked (for parents/scaffold)."
    " Keep a CEFR A0–A1 vocabulary. Encourage, never shame. Give at most one correction per turn."
)


def _now_ts() -> int:
    return int(time.time())


class KidEnglishMCPServer:
    """Core orchestration class implementing the MCP tools as Python methods."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        curriculum_path: Optional[Path] = None,
        references_path: Optional[Path] = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.store = SQLiteStore(self.settings.database_path)
        default_curriculum = Path(__file__).resolve().parent / "curriculum.json"
        self.curriculum = Curriculum.from_json(curriculum_path or default_curriculum)
        default_references = Path(__file__).resolve().parent / "references"
        self.references = ReferenceLexicon(references_path or default_references)
        self.vector_store = VectorStore(self.settings)
        if not self.vector_store.metadata:
            self._bootstrap_vectors()

    # ------------------------------------------------------------------
    # Public MCP-style methods

    def start_session(
        self,
        user_id: str,
        age_band: str,
        goal: str,
        locale: str = "zh-CN",
    ) -> dict:
        existing = self.store.get_latest_session_for_user(user_id)
        if existing:
            state = self._state_from_row(existing)
            state["user_id"] = user_id
            state["age_band"] = age_band
            state["goal"] = goal
            state["locale"] = locale
            session_id = existing.session_id
            self.store.upsert_session(
                session_id=session_id,
                user_id=user_id,
                age_band=age_band,
                goal=goal,
                locale=locale,
                state=state,
                timestamp=_now_ts(),
            )
            if state.get("pending"):
                activity = self._activity_from_pending(state["pending"])
            else:
                activity = self._plan_next_activity(state)
                self._persist_state(session_id, state)
            snapshot = self._snapshot(session_id, state)
            return {
                "session_id": session_id,
                "next_activity": activity,
                "state_snapshot": snapshot,
            }

        now = _now_ts()
        session_id = f"sess_{uuid.uuid4().hex}"
        state = {
            "user_id": user_id,
            "age_band": age_band,
            "goal": goal,
            "locale": locale,
            "xp": 0,
            "stickers": 0,
            "pending": None,
            "new_cursor": 0,
            "new_since_review": 0,
            "attempts": [],
        }
        self.store.upsert_session(
            session_id=session_id,
            user_id=user_id,
            age_band=age_band,
            goal=goal,
            locale=locale,
            state=state,
            timestamp=now,
        )
        activity = self._plan_next_activity(state)
        self._persist_state(session_id, state)
        snapshot = self._snapshot(session_id, state)
        return {
            "session_id": session_id,
            "next_activity": activity,
            "state_snapshot": snapshot,
        }

    def next_activity(self, session_id: str) -> Activity:
        row, state = self._load_state(session_id)
        activity = self._plan_next_activity(state)
        self._persist_state(row.session_id, state)
        return activity

    def submit_utterance(
        self,
        session_id: str,
        utterance_text: str,
        latency_ms: Optional[int] = None,
    ) -> Feedback:
        row, state = self._load_state(session_id)
        if not state.get("pending"):
            self._plan_next_activity(state)
            self._persist_state(row.session_id, state)
        pending = state.get("pending")
        if pending is None:
            raise ValueError("Pending activity missing")

        evaluation = evaluate_utterance(utterance_text, pending["target"])
        outcome = score_to_outcome(evaluation.total)
        mastery_delta = mastery_delta_for_outcome(outcome)
        xp_delta = xp_for_outcome(outcome)

        state.setdefault("xp", 0)
        state.setdefault("stickers", 0)
        state.setdefault("attempts", [])

        if xp_delta:
            state["xp"] += xp_delta

        award = None
        if xp_delta:
            stickers_before = state["stickers"]
            if state["xp"] // 20 > stickers_before:
                state["stickers"] += 1
            award = Award(xp=xp_delta, stickers=state["stickers"])

        now = datetime.fromtimestamp(_now_ts())
        srs_state = self._load_srs(row.user_id)
        item = srs_state.get(pending["item_id"], SRSItem())
        item.schedule(outcome, now)
        srs_state[pending["item_id"]] = item
        self._persist_srs(row.user_id, pending["item_id"], item)

        attempt_log = {
            "item_id": pending["item_id"],
            "outcome": outcome,
            "score": evaluation.total,
            "timestamp": now.timestamp(),
        }
        state["attempts"].append(attempt_log)

        feedback_text, scaffold_cn = self._build_feedback(outcome, pending["target"])

        if outcome == "fail":
            pending["attempts"] += 1
            review = self._make_review_card(pending, state)
            self._persist_state(row.session_id, state)
            return Feedback(
                feedback_text=feedback_text,
                mastery_delta=mastery_delta,
                scaffold_cn=scaffold_cn,
                award=award,
                review_card=review,
            )

        next_activity = self._plan_next_activity(state)
        self._persist_state(row.session_id, state)
        return Feedback(
            feedback_text=feedback_text,
            mastery_delta=mastery_delta,
            scaffold_cn=scaffold_cn if outcome != "pass" else None,
            award=award,
            next_activity=next_activity,
        )

    def set_goal(self, session_id: str, goal: str) -> SessionSnapshot:
        row, state = self._load_state(session_id)
        state["goal"] = goal
        state["new_cursor"] = 0
        state["new_since_review"] = 0
        state["pending"] = None
        self._persist_state(row.session_id, state)
        return self._snapshot(session_id, state)

    def get_progress(self, user_id: str) -> ProgressSummary:
        row = self.store.get_latest_session_for_user(user_id)
        xp = stickers = 0
        recent: list[str] = []
        due_reviews = 0
        if row:
            state = self._state_from_row(row)
            xp = state.get("xp", 0)
            stickers = state.get("stickers", 0)
            recent = [attempt["item_id"] for attempt in state.get("attempts", [])][-5:]
        now_ts = _now_ts()
        for progress in self.store.iter_progress(user_id):
            if progress.due_at <= now_ts:
                due_reviews += 1
        return ProgressSummary(
            cefr_band_estimate="A0-A1",
            xp=xp,
            stickers=stickers,
            recent_items=recent,
            due_reviews=due_reviews,
        )

    def save_note_for_parent(self, session_id: str, note_cn: str) -> dict:
        timestamp = _now_ts()
        self.store.save_parent_note(session_id, note_cn, timestamp)
        return {"status": "ok", "timestamp": timestamp}

    # ------------------------------------------------------------------
    # MCP metadata helpers

    def list_tools(self) -> dict:
        """Return tool metadata for MCP discovery."""

        tools = []
        for name, description in TOOL_DESCRIPTIONS.items():
            tools.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": _tool_input_schema(name),
                }
            )
        return {"tools": tools}

    def call_tool(self, name: str, arguments: Dict[str, object]) -> object:
        """Invoke a public tool method in a transport-friendly fashion."""

        if not hasattr(self, name):
            raise ValueError(f"Unknown tool: {name}")
        method = getattr(self, name)
        if not callable(method):
            raise ValueError(f"Attribute {name} is not callable")
        return method(**arguments)

    # ------------------------------------------------------------------
    # Internal helpers

    def _load_state(self, session_id: str) -> tuple:
        row = self.store.get_session(session_id)
        if row is None:
            raise ValueError("Session not found")
        state = self._state_from_row(row)
        return row, state

    def _state_from_row(self, row) -> Dict:
        import json

        return json.loads(row.state_json)

    def _persist_state(self, session_id: str, state: Dict) -> None:
        now = _now_ts()
        self.store.update_session_state(session_id, state, now)

    def _load_srs(self, user_id: str) -> SRSState:
        payload: Dict[str, Dict[str, float]] = {}
        for row in self.store.iter_progress(user_id):
            payload[row.item_id] = {
                "ease": row.ease,
                "interval_days": row.interval_days,
                "due_at": row.due_at,
                "streak": row.streak,
            }
        return SRSState.from_dict(payload)

    def _persist_srs(self, user_id: str, item_id: str, item: SRSItem) -> None:
        self.store.upsert_progress(
            user_id=user_id,
            item_id=item_id,
            ease=item.ease,
            interval_days=item.interval_days,
            due_at=int(item.due_at.timestamp()),
            streak=item.streak,
        )

    def _plan_next_activity(self, state: Dict) -> Activity:
        pending = {
            "item_id": None,
            "target": "",
            "attempts": 0,
        }
        options = self.curriculum.for_goal_and_age(state["goal"], state["age_band"])
        if not options:
            raise ValueError(f"No curriculum items for goal {state['goal']}")
        srs_state = self._load_srs(state["user_id"])
        now_dt = datetime.fromtimestamp(_now_ts())
        due_items = [
            item
            for item in options
            if item.item_id in srs_state
            and srs_state[item.item_id].due_at <= now_dt
        ]
        due_items.sort(key=lambda item: srs_state[item.item_id].due_at)
        new_items = [item for item in options if item.item_id not in srs_state]
        activity_item: CurriculumItem
        if due_items and state.get("new_since_review", 0) >= 2:
            activity_item = due_items[0]
            state["new_since_review"] = 0
        elif new_items:
            cursor = state.get("new_cursor", 0)
            activity_item = new_items[cursor % len(new_items)]
            state["new_cursor"] = cursor + 1
            state["new_since_review"] = state.get("new_since_review", 0) + 1
        elif due_items:
            activity_item = due_items[0]
            state["new_since_review"] = 0
        else:
            cursor = state.get("new_cursor", 0)
            activity_item = options[cursor % len(options)]
            state["new_cursor"] = cursor + 1

        scaffold = "我们一起慢慢说：" + activity_item.target
        rubric = (
            "Meaning first, allow small grammar errors, offer one gentle correction."
        )
        prompt_text = activity_item.for_prompt(state["age_band"])
        lexicon_words = self.references.sample(state["age_band"], state["goal"], limit=3)

        activity = Activity(
            prompt_text=prompt_text,
            target_phrase=activity_item.target,
            rubric=rubric,
            timebox_sec=12,
            item_id=activity_item.item_id,
            scaffold_cn=scaffold,
            lexicon_words=lexicon_words or None,
        )
        pending.update(
            {
                "item_id": activity.item_id,
                "target": activity.target_phrase,
                "prompt_text": activity.prompt_text,
                "scaffold_cn": activity.scaffold_cn,
                "rubric": activity.rubric,
                "timebox_sec": activity.timebox_sec,
                "lexicon_words": activity.lexicon_words,
                "attempts": 0,
            }
        )
        state["pending"] = pending
        return activity

    def _make_review_card(self, pending: Dict, state: Dict) -> Activity:
        prompt_text = f"Let's say it slowly: {pending['target']}"
        scaffold = f"试试：{pending['target']}"
        return Activity(
            prompt_text=prompt_text,
            target_phrase=pending["target"],
            rubric="Repeat with clear words. Encourage and stay positive.",
            timebox_sec=15,
            item_id=pending["item_id"],
            scaffold_cn=scaffold,
        )

    def _build_feedback(self, outcome: str, target_phrase: str) -> tuple[str, Optional[str]]:
        if outcome == "fail":
            return (
                f"Let's try again. Say: \"{target_phrase}\".",
                f"我们一起慢慢说：{target_phrase}",
            )
        if outcome == "partial":
            return (
                f"Good try! One more time: \"{target_phrase}\".",
                f"再练一次：{target_phrase}",
            )
        return (
            random.choice(
                [
                    f"Awesome! \"{target_phrase}\"!",
                    f"Great job saying \"{target_phrase}\"!",
                    f"High five! You said \"{target_phrase}\".",
                ]
            ),
            None,
        )

    def _snapshot(self, session_id: str, state: Dict) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=session_id,
            user_id=state["user_id"],
            age_band=state["age_band"],
            goal=state["goal"],
            locale=state.get("locale", "zh-CN"),
            xp=state.get("xp", 0),
            stickers=state.get("stickers", 0),
            attempts=list(state.get("attempts", [])),
        )

    def _bootstrap_vectors(self) -> None:
        items = [
            VectorItem(text=item.target, goal=item.track, topic=item.track)
            for item in self.curriculum.all_items()
        ]
        self.vector_store.add_items(items)

    def _activity_from_pending(self, pending: Dict) -> Activity:
        return Activity(
            prompt_text=pending.get("prompt_text", f"Say: {pending['target']}"),
            target_phrase=pending["target"],
            rubric=pending.get(
                "rubric",
                "Meaning first, allow small grammar errors, offer one gentle correction.",
            ),
            timebox_sec=int(pending.get("timebox_sec", 12)),
            item_id=pending["item_id"],
            scaffold_cn=pending.get("scaffold_cn"),
            lexicon_words=pending.get("lexicon_words"),
        )


__all__ = ["KidEnglishMCPServer", "SYSTEM_PROMPT"]
