from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx

from app.config import settings

_google_client = None
GEMINI_TTS_MODEL = settings.gemini_tts_model
OPENAI_TTS_MODEL = settings.openai_tts_model

_GOOGLE_VOICE_MAP = {
    "patient_female": "Kore",
    "patient_male": "Charon",
    "patient_child_female": "Kore",
    "patient_child_male": "Charon",
    "bystander_female": "Kore",
    "bystander_male": "Charon",
    "alex": "Charon",
    "lexi": "Kore",
    "physician": "Charon",
    "default": "Kore",
}

_OPENAI_VOICE_MAP = {
    "patient_female": "nova",
    "patient_male": "onyx",
    "patient_child_female": "shimmer",
    "patient_child_male": "fable",
    "bystander_female": "coral",
    "bystander_male": "echo",
    "alex": "onyx",
    "lexi": "shimmer",
    "physician": "onyx",
    "default": "coral",
}
_OPENAI_TTS1_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_OPENAI_TTS1_VOICE_FALLBACK = {
    "ash": "alloy",
    "ballad": "onyx",
    "coral": "nova",
    "sage": "alloy",
    "verse": "echo",
}

_last_generation_meta: dict[str, str | float | None] = {}


def _normalize_medical_pronunciation(text: str) -> str:
    """Expand common EMS abbreviations before they reach cloud TTS."""
    normalized = text
    replacements = [
        (r"\bmg\s*/\s*dL\b", "milligrams per deciliter"),
        (r"\bmm\s*Hg\b", "millimeters of mercury"),
        (r"\bSpO[₂2]\b", "S P O 2"),
        (r"\bEtCO[₂2]\b", "E T C O 2"),
        (r"\bBGL\b", "blood glucose"),
        (r"\bBG\b", "blood glucose"),
        (r"\bCGM\b", "C G M"),
        (r"\bBP\b", "blood pressure"),
        (r"\bHR\b", "heart rate"),
        (r"\bRR\b", "respiratory rate"),
        (r"\bBVM\b", "B V M"),
        (r"\bNRB\b", "N R B"),
        (r"\bNC\b", "nasal cannula"),
        (r"\bLPM\b", "liters per minute"),
        (r"\bbpm\b", "beats per minute"),
        (r"\bGCS\b", "G C S"),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("°F", " degrees Fahrenheit")
    normalized = normalized.replace("°C", " degrees Celsius")
    return normalized


def _texttospeech():
    from google.cloud import texttospeech

    return texttospeech


def _get_google_client():
    global _google_client
    if _google_client is None:
        _google_client = _texttospeech().TextToSpeechClient()
    return _google_client


def _resolve_voice_key(speaker_role: str, gender: str | None, age: str | None) -> str:
    if speaker_role in ("alex", "lexi", "physician"):
        return speaker_role
    if speaker_role == "bystander":
        return f"bystander_{gender or 'female'}"
    if age == "child":
        return f"patient_child_{gender or 'female'}"
    return f"patient_{gender or 'female'}"


def _inject_clinical_audio_cues(text: str, spo2: int, rr: int) -> str:
    """Cosmetic audio styling only; Phase 0 validates which cue tags work."""
    if spo2 < 90 or rr > 24:
        # Keep this deliberately light. Heavy bracket cue injection can be read
        # aloud or create odd filler words, depending on model behavior.
        text = text.replace(". ", ". [breath] ", 1)
        text = text.replace("! ", "! [breath] ", 1)
    return text


def _speaker_description(speaker_role: str, gender: str | None, age: str | None) -> str:
    age_label = "child" if age == "child" else "elderly adult" if age == "elderly" else "adult"
    gender_label = gender or "person"
    if speaker_role == "alex":
        return "adult male EMT partner"
    if speaker_role == "lexi":
        return "friendly female EMS training coach"
    if speaker_role == "physician":
        return f"{age_label} {gender_label} physician"
    if speaker_role == "bystander":
        return f"{age_label} {gender_label} family member or bystander"
    return f"{age_label} {gender_label} patient"


def _style_prompt(
    speaker_role: str,
    gender: str | None,
    age: str | None,
    spo2: int,
    rr: int,
    demeanor: str | None = None,
    delivery: str | None = None,
    avoid: str | None = None,
) -> str:
    speaker = _speaker_description(speaker_role, gender, age)
    base_demeanor = demeanor or "natural and clinically plausible"
    base_delivery = delivery or "clear, conversational delivery"
    avoid_line = avoid or "do not sound like a narrator or instructor"

    if speaker_role == "bystander":
        return "\n".join(
            [
                f"Character: {speaker} in an EMS simulation.",
                f"Voice Affect: {base_demeanor}. Genuinely worried and protective, with controlled fear.",
                f"Tone: {base_delivery}. Sincere, urgent, and emotionally present without becoming theatrical.",
                "Pacing: Slightly faster on worried questions; slow down for important details and reassurance.",
                "Emotions: Concern, fear for the patient, cooperation with EMS, and guarded hope when reassured.",
                "Pronunciation: Clear, natural American English. Keep medical words plain and understandable.",
                "Pauses: Brief pauses before worried questions and after emotionally important phrases.",
                f"Avoid: {avoid_line}. Do not sound physically ill, short of breath, sedated, playful, clinical, or like the patient.",
            ]
        )
    if speaker_role == "alex":
        return "\n".join(
            [
                f"Character: {speaker}.",
                f"Voice Affect: {base_demeanor}. Calm, composed, reassuring, competent, and in control.",
                f"Tone: {base_delivery}. Sincere, practical, concise, and team-oriented.",
                "Pacing: Efficient and steady. Slightly faster when acting, slower when clarifying a safety concern.",
                "Emotions: Calm confidence, focus, and quiet concern for the patient.",
                "Pronunciation: Clear and precise, especially vitals, equipment, and short commands.",
                "Pauses: Brief pauses between findings so the listener can process them.",
                f"Avoid: {avoid_line}. Do not sound like a narrator, instructor, parent, or patient.",
            ]
        )
    if speaker_role != "patient":
        return "\n".join(
            [
                f"Character: {speaker}.",
                f"Voice Affect: {base_demeanor}.",
                f"Tone: {base_delivery}.",
                "Pacing: Natural and easy to understand.",
                "Pronunciation: Clear and precise.",
                f"Avoid: {avoid_line}.",
            ]
        )
    if spo2 < 90 or rr > 24:
        return "\n".join(
            [
                f"Character: {speaker}.",
                f"Voice Affect: {base_demeanor}. Noticeable respiratory distress, anxious but understandable.",
                f"Tone: {base_delivery}. Vulnerable, strained, and realistic.",
                "Pacing: Short phrases with small pauses for breath. Do not rush.",
                "Emotions: Anxiety and discomfort without melodrama.",
                "Pronunciation: Clear enough for learners to understand clinically relevant details.",
                "Pauses: Brief breath-like pauses between phrases.",
                f"Avoid: {avoid_line}. Do not overact or add unspoken sound effects.",
            ]
        )
    if age == "child" and re.search(r"\b(cry|crying|tear|tearful|sob|sniff|pain|hurts?|pained)\b", f"{base_demeanor} {base_delivery}", re.IGNORECASE):
        return "\n".join(
            [
                f"Character: {speaker}.",
                f"Voice Affect: {base_demeanor}. Child has been crying from pain, with a tight throat, shaky affect, and urgent fear.",
                f"Tone: {base_delivery}. Vulnerable, frightened, pained, and varied in tone, but still understandable.",
                "Pacing: Faster short strained phrases with quick shaky breaths. Do not make it slow, smooth, calm, or conversational.",
                "Emotions: Pain, fear, and trying to cooperate through tears.",
                "Emphasis: Put audible emphasis and slight voice cracks on pain/fear words such as hurts, ow, arm, don't touch, and scared.",
                "Pronunciation: Clear enough for learners to understand, but with realistic tearful strain.",
                "Pauses: Very small tearful pauses only; avoid long dramatic pauses.",
                f"Avoid: {avoid_line}. Do not sound calm, monotone, fluent, cheerful, theatrical, or like an adult.",
            ]
        )
    return "\n".join(
        [
            f"Character: {speaker}.",
            f"Voice Affect: {base_demeanor}.",
            f"Tone: {base_delivery}.",
            "Pacing: Natural, conversational, and easy to understand.",
            "Pronunciation: Clear and precise.",
            f"Avoid: {avoid_line}.",
        ]
    )


def _cache_path(
    provider: str,
    model: str,
    scenario_id: str | None,
    voice_name: str,
    prompt: str,
    processed: str,
    audio_format: str = "mp3",
    speed: float | None = None,
    speaking_rate: float | None = None,
    pitch: float | None = None,
) -> Path:
    ext = "wav" if audio_format == "wav" else "opus" if audio_format == "opus" else "mp3"
    scenario_key = scenario_id or ""
    cache_key = hashlib.sha256(
        f"{provider}|{model}|{scenario_key}|{voice_name}|{speaking_rate}|{pitch}|{audio_format}|{speed}|{prompt}|{processed}".encode()
    ).hexdigest()
    cache_dir = Path(settings.tts_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{cache_key}.{ext}"


def _generate_google_speech(
    text: str,
    scenario_id: str | None,
    speaker_role: str,
    gender: str | None = None,
    age: str | None = None,
    spo2: int = 98,
    rr: int = 16,
) -> bytes:
    """Return MP3 bytes from cache if available, otherwise synthesize them."""
    processed = _normalize_medical_pronunciation(text)
    if speaker_role == "patient":
        processed = _inject_clinical_audio_cues(processed, spo2, rr)

    voice_key = _resolve_voice_key(speaker_role, gender, age)
    voice_name = _GOOGLE_VOICE_MAP.get(voice_key, _GOOGLE_VOICE_MAP["default"])
    speaking_rate = 0.9 if age == "child" else 1.0
    pitch = 3.0 if age == "child" else 0.0
    global _last_generation_meta
    _last_generation_meta = {
        "provider": "google",
        "model": GEMINI_TTS_MODEL,
        "voice": voice_name,
        "role": speaker_role,
        "scenario_id": scenario_id,
        "gender": gender,
        "age": age,
        "speed": speaking_rate,
    }

    prompt = _style_prompt(speaker_role, gender, age, spo2, rr)
    cache_path = _cache_path(
        "google", GEMINI_TTS_MODEL, scenario_id, voice_name, prompt, processed, "mp3", None, speaking_rate, pitch
    )

    if cache_path.exists():
        return cache_path.read_bytes()

    texttospeech = _texttospeech()
    response = _get_google_client().synthesize_speech(
        input=texttospeech.SynthesisInput(text=processed, prompt=prompt),
        voice=texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name,
            model_name=GEMINI_TTS_MODEL,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
            pitch=pitch,
        ),
    )

    cache_path.write_bytes(response.audio_content)
    return response.audio_content


def _generate_openai_speech(
    text: str,
    scenario_id: str | None,
    speaker_role: str,
    gender: str | None = None,
    age: str | None = None,
    provider_voice: str | None = None,
    demeanor: str | None = None,
    delivery: str | None = None,
    avoid: str | None = None,
    speed: float | None = None,
    spo2: int = 98,
    rr: int = 16,
) -> bytes:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when TTS_PROVIDER=openai")

    processed = _normalize_medical_pronunciation(text)
    voice_key = _resolve_voice_key(speaker_role, gender, age)
    voice_name = provider_voice or _OPENAI_VOICE_MAP.get(voice_key, _OPENAI_VOICE_MAP["default"])
    prompt = _style_prompt(speaker_role, gender, age, spo2, rr, demeanor, delivery, avoid)
    if age == "child" and re.search(r"\b(cry|crying|tear|tearful|sob|sniff|pain|hurts?|pained)\b", f"{demeanor or ''} {delivery or ''}", re.IGNORECASE):
        processed = re.sub(r"\.{2,}", ",", processed)
    has_authored_style = any([provider_voice, demeanor, delivery, avoid, speed])
    compact_prompt = speaker_role in ("alex", "bystander") and len(processed) <= 90 and not has_authored_style
    if compact_prompt:
        prompt = "Speak naturally and clearly in character. Keep the emotion realistic, concise, and not theatrical."
    audio_format = settings.openai_tts_format
    speech_speed = speed or settings.openai_tts_speed
    request_model = OPENAI_TTS_MODEL
    request_voice = voice_name
    # Live simulator speech is latency-sensitive. Use OpenAI's faster TTS model
    # for dynamic lines when the richer model is configured for authored audio.
    if OPENAI_TTS_MODEL == "gpt-4o-mini-tts":
        if not has_authored_style:
            request_model = "tts-1"
            request_voice = voice_name if voice_name in _OPENAI_TTS1_VOICES else _OPENAI_TTS1_VOICE_FALLBACK.get(voice_name, "alloy")
    elif has_authored_style:
        request_model = "gpt-4o-mini-tts"
    global _last_generation_meta
    _last_generation_meta = {
        "provider": "openai",
        "model": request_model,
        "voice": request_voice,
        "role": speaker_role,
        "scenario_id": scenario_id,
        "gender": gender,
        "age": age,
        "speed": speech_speed,
    }
    cache_path = _cache_path(
        "openai", request_model, scenario_id, request_voice, prompt, processed, audio_format, speech_speed
    )

    if cache_path.exists():
        return cache_path.read_bytes()

    payload = {
        "model": request_model,
        "voice": request_voice,
        "input": processed,
        "instructions": prompt,
        "response_format": audio_format,
        "speed": speech_speed,
    }
    try:
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(2.0, connect=2.0),
        )
    except httpx.ReadTimeout:
        # Retry once with compact instructions so live scenarios keep a cloud
        # voice instead of skipping the line or falling back to native browser
        # synthesis.
        payload["instructions"] = "Speak naturally and clearly in character. Keep the emotion realistic, not theatrical."
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(4.0, connect=3.0),
        )
    response.raise_for_status()
    cache_path.write_bytes(response.content)
    return response.content


def generate_speech(
    text: str,
    scenario_id: str | None,
    speaker_role: str,
    gender: str | None = None,
    age: str | None = None,
    provider_voice: str | None = None,
    demeanor: str | None = None,
    delivery: str | None = None,
    avoid: str | None = None,
    speed: float | None = None,
    spo2: int = 98,
    rr: int = 16,
) -> bytes:
    """Return MP3 bytes from cache if available, otherwise synthesize them."""
    if settings.tts_provider == "openai":
        return _generate_openai_speech(
            text, scenario_id, speaker_role, gender, age, provider_voice, demeanor, delivery, avoid, speed, spo2, rr
        )
    return _generate_google_speech(text, scenario_id, speaker_role, gender, age, spo2, rr)


def last_generation_meta() -> dict[str, str | float | None]:
    return dict(_last_generation_meta)
