import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from english_kids_mcp import KidEnglishMCPServer, Settings


def test_full_flow(tmp_path):
    settings = Settings(
        database_path=tmp_path / "test.sqlite",
        faiss_index_path=tmp_path / "test.index",
        embedding_dim=32,
    )
    server = KidEnglishMCPServer(settings=settings)

    session = server.start_session(
        user_id="kid-1",
        age_band="5-6",
        goal="greetings",
        locale="zh-CN",
    )

    activity = session["next_activity"]
    assert activity.target_phrase
    assert activity.prompt_text
    assert activity.lexicon_words is None or isinstance(activity.lexicon_words, list)

    feedback = server.submit_utterance(session["session_id"], "hi")
    assert feedback.next_activity is not None
    assert feedback.mastery_delta >= 0

    retry_feedback = server.submit_utterance(session["session_id"], "")
    assert retry_feedback.review_card is not None
    assert retry_feedback.mastery_delta < 1

    progress = server.get_progress("kid-1")
    assert progress.xp >= 0
    assert isinstance(progress.recent_items, list)
