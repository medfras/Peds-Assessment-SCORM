"""Smoke-test Google Cloud Gemini-TTS credentials outside FastAPI.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/abs/path/key.json \
    GOOGLE_CLOUD_PROJECT=your-project-id \
    python scripts/test_gemini_tts.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import texttospeech


def main() -> None:
    load_dotenv()
    credentials = os.getenv("GCP_TTS_CREDENTIALS_HOST_PATH") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials:
        raise SystemExit("GOOGLE_APPLICATION_CREDENTIALS is not set.")
    if not Path(credentials).exists():
        raise SystemExit(f"Credential file does not exist: {credentials}")

    model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-tts")
    prompt = "Say the following as a calm EMS simulation patient."
    text = "This is a test. The Gemini text to speech API is working."

    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text, prompt=prompt),
        voice=texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="Kore",
            model_name=model,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        ),
    )

    output = Path("test_tts.mp3")
    output.write_bytes(response.audio_content)
    print(f"SUCCESS: wrote {output.resolve()}")


if __name__ == "__main__":
    main()
