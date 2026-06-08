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


def test_lung_sound_challenge_keeps_blowby_as_care_action_not_answer_choice():
    html = (ROOT / "static/index.html").read_text()
    js = (ROOT / "static/js/app.js").read_text()
    choices_block = js[js.index("const _LUNG_SOUND_CHOICES"):js.index("// Matches any lung sounds EXAM tag variant")]

    assert 'id="btn-lung-sound-blowby"' in html
    assert 'applyInterventionAndRecord(\n    "o2_blowby"' in js
    assert "lung_sound_challenge" in js
    assert "blowby" not in choices_block
