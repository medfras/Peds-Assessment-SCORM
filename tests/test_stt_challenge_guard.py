from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_challenge_modals_disable_stt_microphones():
    js = (ROOT / "static/js/app.js").read_text()

    assert "const _STT_MIC_BUTTON_IDS" in js
    for button_id in ("btn-voice-input", "btn-voice-dmist", "btn-voice-narrative", "btn-mc-stt"):
        assert button_id in js

    assert "const _STT_BLOCKING_CHALLENGE_MODAL_IDS" in js
    assert "modal-challenge" in js
    assert "modal-lung-sound" in js
    assert "function _isChallengeModalOpenForStt()" in js
    assert "function _stopSpeechRecognitionForChallenge()" in js
    assert "Voice input is disabled while a challenge is open." in js
    assert "if (_isChallengeModalOpenForStt())" in js
