from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = ROOT / "app" / "main.py"
MODELS_PY = ROOT / "app" / "models.py"
RESET_SCORM_LEARNER = ROOT / "scripts" / "reset_scorm_learner.py"


def test_lexi_chat_messages_are_persisted_and_purged_with_raw_chat_ttl():
    models = MODELS_PY.read_text()
    main = MAIN_PY.read_text()
    reset_script = RESET_SCORM_LEARNER.read_text()

    assert "class LexiChatMessage(Base):" in models
    assert '__tablename__ = "lexi_chat_messages"' in models
    assert 'Index("ix_lexi_chat_messages_session_time", "session_id", "timestamp")' in models
    assert 'Index("ix_lexi_chat_messages_user_time", "user_id", "timestamp")' in models
    assert 'ForeignKey("sessions.id")' in models
    assert 'ForeignKey("users.id")' in models

    assert "LexiChatMessage," in main
    assert "def _lexi_log_user_content(req: LexiRequest) -> str:" in main
    assert 'marker = "Learner question:"' in main
    assert "return text_value.rsplit(marker, 1)[-1].strip()" in main
    assert main.count("LexiChatMessage(") >= 2
    assert 'role="user"' in main
    assert 'role="model"' in main
    assert 'mode=req.mode or "scenario"' in main

    assert "LexiChatMessage.__table__.delete()" in main
    assert '"lexi_chat_messages",' in reset_script
