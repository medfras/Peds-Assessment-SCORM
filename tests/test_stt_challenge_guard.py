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


def test_lung_sound_challenge_has_no_blowby_care_action_or_answer_choice():
    html = (ROOT / "static/index.html").read_text()
    js = (ROOT / "static/js/app.js").read_text()
    choices_block = js[js.index("const _LUNG_SOUND_CHOICES"):js.index("// Matches any lung sounds EXAM tag variant")]

    assert 'id="btn-lung-sound-blowby"' not in html
    assert 'id="lung-sound-care-action-panel"' not in html
    assert "function _syncLungSoundCareAction(config = {})" not in js
    assert "btn-lung-sound-blowby" not in js
    assert "blowby" not in choices_block


def test_lung_sound_continue_closes_modal_and_resets_audio():
    js = (ROOT / "static/js/app.js").read_text()
    block = js[
        js.index('el("btn-lung-sound-continue")?.addEventListener("click"'):
        js.index("/* ═══════════════════════════════════════════════════════════════════\n   TREATMENT MODAL", js.index('el("btn-lung-sound-continue")?.addEventListener("click"'))
    ]

    assert 'hide("modal-lung-sound");' in block
    assert "isPopupOpen = false;" in block
    assert "speakPendingIfAny();" in block
    assert "_resumePendingImpressionChallengeAfterModal();" in block
    assert 'const audio = el("lung-sound-audio");' in block
    assert "audio.pause();" in block
    assert "audio.currentTime = 0;" in block
    assert 'setText("lung-sound-play-icon", "▶");' in block


def test_o2_modal_blowby_checkbox_is_visible_and_unchecked_by_default():
    html = (ROOT / "static/index.html").read_text()
    js = (ROOT / "static/js/app.js").read_text()
    label_start = html.index('id="o2-blowby-label"')
    label_tag = html[html.rfind("<label", 0, label_start):html.index(">", label_start)]
    show_block = js[js.index("function showO2Popup"):js.index("function updateO2FlowForDevice")]
    update_block = js[js.index("function updateO2FlowForDevice"):js.index("// Wire O2 device buttons")]
    change_block = js[js.index('el("o2-blowby")?.addEventListener("change"'):js.index('el("btn-o2-cancel")')]

    assert "hidden" not in label_tag
    assert "Blow-by held near face" in html
    assert "Blow-by with NRB held near face" not in html
    assert "Blow-by O₂ held near face" in js
    assert "blowbyEl.checked = false;" in show_block
    assert 'blowbyLabel.classList.remove("hidden")' in update_block
    assert 'blowbyLabel.classList.add("hidden")' not in update_block
    assert 'data-device="nrb"' in change_block
