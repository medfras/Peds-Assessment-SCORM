# TTS Upgrade Plan — Cloud TTS Integration

**Target:** Provide opt-in, realistic text-to-speech for scenario patients, family members, partners, and physicians through the FastAPI backend while preserving cost controls and graceful no-audio behavior.

**Current implementation status (May 2026):**
- `TTS_PROVIDER=openai` is the active local cloud path.
- `TTS_PROVIDER=browser` disables paid cloud calls and uses native browser synthesis only.
- All paid cloud calls are gated by the frontend TTS toggle; when the toggle is off, `speakText()` returns before calling `/api/tts`.
- `/api/tts` supports OpenAI and Google provider paths, scenario-aware cache keys, persona voice metadata, and diagnostic headers.
- OpenAI output defaults to MP3 for smaller payloads and more reliable live playback.
- Cloud provider failures skip the line instead of falling back to robotic browser speech, except when cloud TTS is intentionally disabled.
- Initial deterministic-line prewarming is implemented; the next optimization phase is authored audio packs and TTS usage logging.

**Provider notes:**
- OpenAI `tts-1` is currently preferred for live scenario speech because responsiveness matters more than maximum expressiveness during gameplay.
- OpenAI `gpt-4o-mini-tts` remains a candidate for pre-generated/static audio packs where startup delay does not affect learner interaction.
- Google Gemini TTS remains a planned/available alternate path, but setup friction and voice behavior made OpenAI the better near-term choice.
- Browser TTS remains a zero-cost fallback only when cloud TTS is intentionally disabled.

**Why cloud TTS over native browser synthesis:**
- Style/emotion prompting lets the backend inject the patient's clinical state into a "Director's Notes" style prompt
- Scenario personas can carry age, sex/gender voice hints, provider voice, speed, demeanor, delivery, and avoid instructions
- OS-dependent robotic browser voices are avoided for learners who enable TTS
- Backend routing keeps provider credentials out of the frontend
- Caching and authored audio packs can reduce both cost and delay

**Estimated cost direction:** Runtime OpenAI TTS is acceptable for pilot testing when opt-in and cached, but production should not depend on live generation for every deterministic line. Long-term cost and latency control should come from prewarmed cache and static scenario audio packs.

---

## Current State Inventory

The active simulator TTS path is split between frontend orchestration and backend provider generation:

- `static/js/app.js` — `isTtsEnabled` flag, toggle button, speaker parsing, persona lookup, queueing, mic pause/resume, and `Audio()` playback
- `static/js/app.js` — `speakText(text)` is the single frontend entry point for scenario chat/action audio; it returns immediately when TTS is off
- `app/routers/tts.py` — authenticated, rate-limited `POST /api/tts` endpoint
- `app/services/tts_service.py` — provider selection, OpenAI/Google synthesis, cache keys, provider retry, and diagnostic metadata
- `app/scenarios/**.json` — persona `tts` metadata for scenario-specific voice, age/sex hints, speed, demeanor, delivery, and avoid instructions
- `.env` / `.env.example` — `TTS_PROVIDER`, cache directory, OpenAI model/format/speed, and optional Google model/credentials settings

**Known weaknesses / next work:**
1. Live provider generation can still create a 1-3 second delay on uncached lines, with occasional provider stalls
2. Deterministic scenario lines are prewarmed best-effort when TTS is enabled, but dynamic LLM dialogue still requires live generation
3. Static authored audio packs are not yet supported
4. TTS usage logging does not yet distinguish static audio, cache hit, prewarm generation, and live provider generation
5. Medical Control TTS remains a separate path and has not been upgraded in this pass

---

## Architecture Decision

All paid cloud TTS calls go through the FastAPI backend. The frontend calls `POST /api/tts`, receives an audio blob, and plays it via the `Audio` Web API. The backend handles provider credentials, audio caching, scenario-aware voice metadata, and clinical audio styling.

The frontend must call `/api/tts` only through `speakText()`, and `speakText()` must remain guarded by `isTtsEnabled`. This is the primary cost-control boundary: no TTS toggle, no paid cloud call.

Native `window.speechSynthesis` is not used as a general fallback for provider failures because it creates jarring voice changes. It is reserved for the explicit `TTS_PROVIDER=browser` case.

```
speakText(text)
    │
    ├─► if TTS toggle is off → return, no API call, no cost
    │
    ├─► POST /api/tts  ──► tts_service.py
    │       │                   ├─► Cache hit? → return cached MP3
    │       │                   └─► OpenAI or Google TTS API
    │       │                           └─► persona/style prompt + provider retry policy
    │       └─ audio blob → Audio() → play
    │
    └─► browser fallback only when cloud TTS is intentionally disabled
```

### Latency and Cost Optimization Roadmap

These items should be implemented in this order:

1. **Prewarm deterministic scenario lines**
   - Implemented initial setup: when a scenario starts and TTS is enabled, enqueue background `/api/tts` calls for `initial_complaint`, `history_response_map` answers, common Alex clarifiers, and popup prompts.
   - Prewarm uses the same speaker parsing and sentence chunking as playback so long deterministic lines warm the cache entries that playback will actually request.
   - Prewarm only when the learner has enabled TTS, so unused scenarios do not generate paid audio.
   - Keep this best-effort and non-blocking; scenario start must not wait on prewarm completion.

2. **Static authored audio packs**
   - For production/pilot-stable scenarios, generate approved audio files offline for deterministic lines and serve them as static assets or object-storage URLs.
   - Use static audio first, cache second, live provider generation third.
   - This removes both per-run cost and live generation delay for repeated authored content.

3. **Line-type routing**
   - Use fast OpenAI voice/style for live patient and family dialogue.
   - Use premium OpenAI voice/style only for pre-generated/static authored audio where delay is hidden.
   - Use compact prompts or prebuilt audio for partner utility lines such as vitals, popup prompts, and brief acknowledgements.
   - Keep voice consistency; do not silently switch to robotic browser voices during a run.

4. **Streaming TTS evaluation**
   - Evaluate provider streaming only after cache/prewarm/audio-pack paths are stable.
   - Streaming may reduce perceived delay for dynamic LLM responses, but it is more complex than prewarming deterministic lines.

---

## Implementation Phases

### Phase 0: Google Cloud Setup (manual — you do this)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project named `rescue-trails-tts` (or use your existing project)
3. Open the Cloud Shell terminal (`>_` icon top right) and run:
   `gcloud services enable aiplatform.googleapis.com texttospeech.googleapis.com`
4. Create a service account named `tts-backend`:
   `gcloud iam service-accounts create tts-backend --display-name="TTS Backend"`
5. Grant it the **Vertex AI User** role (`roles/aiplatform.user`):
   `gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:tts-backend@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/aiplatform.user"`
6. Go to **IAM & Admin → Service Accounts**, click `tts-backend`, go to the **KEYS** tab, click **ADD KEY** -> **Create new key** (JSON), and save it securely outside the repo.
7. Add to your `.env` file:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/rescue-trails-tts.json
   TTS_PROVIDER=google   # "google" or "browser" — "browser" disables the cloud path
   TTS_CACHE_DIR=/tmp/tts_cache
   GEMINI_TTS_MODEL=gemini-2.5-flash-tts
   ```
8. Add `GOOGLE_APPLICATION_CREDENTIALS` and `TTS_PROVIDER` to `.env.example` with placeholder values

**Phase 0 spike (do this before writing backend code):** Run a one-off Python script using the SDK directly to confirm:
- `google-cloud-texttospeech>=2.29.0` authenticates with the service account
- A `VoiceSelectionParams` call with `model_name="gemini-2.5-flash-tts"` and a Gemini voice name (e.g., `Kore`, `Charon`) returns audio without error
- Sending text with `[cough]` and `[gasp]` in the input actually produces audible respiratory sounds (not just reads the words aloud). **If these tags don't produce the desired effect, the backend prompt-injection strategy in `_inject_clinical_tags` should fall back to styling via `SynthesisInput(prompt=...)` instead.**

---

### Phase 1: Backend — Service + Router

**Prerequisite files to create first:**
- `app/auth.py` — extract auth helpers AND the rate limiter from `main.py` to avoid circular imports (see note below)

**Then create:**
- `app/routers/` directory (new — required by CLAUDE.md; does not exist yet)
- `app/routers/__init__.py`
- `app/routers/tts.py`
- `app/services/tts_service.py`

**Files to modify:**
- `app/main.py` — import `get_active_context` and `limiter` from `app.auth`; register the new router
- `app/config.py` — add `tts_provider`, `tts_cache_dir`, and `gemini_tts_model` settings
- `requirements.txt` — add `google-cloud-texttospeech>=2.29.0` (minimum required for Gemini TTS; `>=2.16.0` targets legacy Neural2/Journey voices only)

> **Circular import note:** Auth dependencies (`get_active_context`, `get_instructor_context`, `_extract_token`, `_decode_token`, `ActiveContext`) AND the rate limiter (`_rate_limit_key` at `main.py:408`, `limiter` at `main.py:421`) all live in `app/main.py`. Any router that imports either will circular-import once `main.py` includes that router. Fix: extract both groups to `app/auth.py`. Both `main.py` and every router then import from `app.auth`. This is a one-time prerequisite for ALL future router work. Extract first, run the test suite, then build the router.

#### `app/services/tts_service.py`

```python
import os
import hashlib
from pathlib import Path
from google.cloud import texttospeech
from app.config import settings

_client: texttospeech.TextToSpeechClient | None = None

def _get_client() -> texttospeech.TextToSpeechClient:
    global _client
    if _client is None:
        _client = texttospeech.TextToSpeechClient()
    return _client

# Gemini TTS voice names (confirmed via Phase 0 spike).
# These are single-word identifiers, NOT the en-US-Journey-* legacy format.
# Verify current voice list at: https://cloud.google.com/text-to-speech/docs/gemini-tts
GEMINI_TTS_MODEL = settings.gemini_tts_model
_VOICE_MAP = {
    "patient_female":       "Kore",     # female patient
    "patient_male":         "Charon",   # male patient
    "patient_child_female": "Kore",     # pitch-adjusted
    "patient_child_male":   "Charon",   # pitch-adjusted
    "alex":                 "Charon",   # male EMS partner
    "lexi":                 "Kore",     # female coach
    "physician":            "Charon",   # MC physician default
    "default":              "Kore",
}

def _resolve_voice_key(speaker_role: str, gender: str | None, age: str | None) -> str:
    if speaker_role in ("alex", "lexi", "physician"):
        return speaker_role
    if age == "child":
        return f"patient_child_{gender or 'female'}"
    return f"patient_{gender or 'female'}"

def _inject_clinical_tags(text: str, spo2: int, rr: int) -> str:
    """Inject Gemini bracket markup for audible respiratory distress."""
    if spo2 < 90 or rr > 24:
        # Insert [gasp] at sentence boundaries and [breath] at commas
        text = text.replace(". ", ". [gasp] ")
        text = text.replace("! ", "! [gasp] ")
        text = text.replace(", ", ", [breath] ")
    # Pass through any [cough] / [gasp] / [wheeze] already in the text from the LLM
    return text

def generate_speech(
    text: str,
    speaker_role: str,
    gender: str | None = None,
    age: str | None = None,
    spo2: int = 98,
    rr: int = 16,
) -> bytes:
    """Return MP3 bytes — from cache if available, otherwise synthesized."""
    processed = text
    if speaker_role == "patient":
        processed = _inject_clinical_tags(text, spo2, rr)

    voice_key = _resolve_voice_key(speaker_role, gender, age)
    voice_name = _VOICE_MAP.get(voice_key, _VOICE_MAP["default"])
    speaking_rate = 0.9 if age == "child" else 1.0
    pitch = 3.0 if age == "child" else 0.0

    # Include model + voice + audio config in the key so cached audio
    # is never reused after a voice/model change.
    cache_key = hashlib.sha256(
        f"{GEMINI_TTS_MODEL}|{voice_name}|{speaking_rate}|{pitch}|MP3|{processed}".encode()
    ).hexdigest()
    cache_dir = Path(settings.tts_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}.mp3"

    if cache_path.exists():
        return cache_path.read_bytes()

    client = _get_client()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=processed),
        voice=texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name,
            # Gemini TTS requires model_name — verify exact param name in SDK 2.29+
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
```

#### `app/routers/tts.py`

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.auth import get_active_context, limiter   # extracted from main.py (see prerequisite)
from app.services.tts_service import generate_speech
from app.config import settings
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/tts", tags=["tts"])

class TTSRequest(BaseModel):
    text:         str = Field(min_length=1, max_length=1000)  # hard cap prevents abuse
    speaker_role: str = "patient"                             # patient | alex | lexi | physician
    gender:       str | None = None                           # male | female | None
    age:          str | None = None                           # child | elderly | None
    spo2:         int = Field(default=98, ge=0, le=100)
    rr:           int = Field(default=16, ge=0, le=60)

# TTS is LLM-equivalent cost — use the same rate category as chat endpoints.
# DEVELOPMENT_GUIDELINES.md §Rate Limiting requires @limiter.limit on every public endpoint.
@router.post("")
@limiter.limit(f"{settings.rate_limit_chat}/minute")
async def synthesize(request: Request, req: TTSRequest, ctx=Depends(get_active_context)):
    if settings.tts_provider != "google":
        raise HTTPException(status_code=503, detail="Cloud TTS not configured")
    try:
        audio = generate_speech(
            text=req.text,
            speaker_role=req.speaker_role,
            gender=req.gender,
            age=req.age,
            spo2=req.spo2,
            rr=req.rr,
        )
        return Response(content=audio, media_type="audio/mpeg")
    except Exception as e:
        logger.error("tts_synthesis_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Audio generation failed")
```

> **Vitals trust boundary note:** `spo2` and `rr` sent by the frontend are used only for cosmetic audio styling (breathing sounds). They do not affect scoring or session state, so frontend-sourced values are acceptable here. If in a future iteration the clinical presentation must be authoritative, pass `session_id` instead and have `tts_service` load vitals from the session store.

#### `app/main.py` change

After the `app/auth.py` extraction, update the two lines that define `limiter` and `get_active_context` to imports, then add the router:

```python
from app.auth import get_active_context, get_instructor_context, get_admin_context, get_superuser_context, limiter
from app.routers import tts as tts_router
app.include_router(tts_router.router)
```

---

### Phase 2: Frontend — Cloud TTS with Fallback

**File to modify:** `static/js/app.js`

The changes are surgical — replace the body of `speakText` and `speakPendingIfAny`, and add an audio queue. The existing `_profileFromText`, `_CHAR_PROFILES`, `_pickVoice`, and `_makeUtterance` all stay in place (needed for the fallback path).

#### Replace the single-slot `pendingSpeech` queue with a proper queue

At `app.js:3668` (alongside existing TTS state vars), add:

```js
let _ttsAudioQueue = [];        // { url: ObjectURL, cleanup: fn } items
let _ttsAudioPlaying = false;
```

#### Replace `speakText` body (keep signature identical — `function speakText(text)`)

> **Ordering note:** `speakText` is called synchronously in conversation order, but `authFetch` resolves asynchronously — responses can arrive out of order if the network varies per request. Fix: allocate a queue slot synchronously before the fetch so the slot index is locked in call order. The slot is filled when the fetch completes; `_playNextTts` only advances when the front slot is ready.

```js
// Queue slot shape: { url: string|null, ready: boolean, cleanup: fn|null }
// A slot is allocated synchronously; url/ready are filled when the fetch resolves.

async function speakText(text) {
  if (!isTtsEnabled) return;
  const { gender, age } = _profileFromText(text);

  // Determine speaker role from character tag
  let role = "patient";
  const tagMatch = text.match(/^\*([^*:]+)\*?:/);
  if (tagMatch) {
    const name = tagMatch[1].trim().toLowerCase();
    if (name === "alex")  role = "alex";
    if (name === "lexi")  role = "lexi";
  }

  let cleanText = text.replace(/\[\[.*?\]\]/g, '').replace(/\*.*?\*:/g, '').trim();
  if (cleanText.length === 0) return;

  // Grab live vitals for cosmetic clinical audio styling (patient role only)
  const spo2 = Number(state.currentVitals?.spo2 ?? 98);
  const rr   = Number(state.currentVitals?.rr   ?? 16);

  // --- Attempt cloud TTS ---
  // Allocate slot synchronously to preserve call order regardless of fetch timing.
  const slot = { url: null, ready: false, cleanup: null };
  _ttsAudioQueue.push(slot);

  try {
    const res = await authFetch(`${API}/api/tts`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ text: cleanText, speaker_role: role, gender, age, spo2, rr }),
    });
    if (!res.ok) throw new Error(`TTS ${res.status}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    slot.url     = url;
    slot.ready   = true;
    slot.cleanup = () => URL.revokeObjectURL(url);
    _playNextTts();
    return;
  } catch (err) {
    console.warn("Cloud TTS failed; skipping synthesized speech to avoid voice mismatch:", err);
    if (!synth || synth.getVoices().length === 0) {
      // No cloud audio and no native voices available. Mark this slot skippable
      // so later ready slots are not blocked behind it.
      slot.url = "__skip__";
      slot.ready = true;
      _playNextTts();
      return;
    }
    // Fill the original slot in-place rather than removing and re-appending.
    // Removing and pushing would move this message to the end of the queue,
    // causing it to play after any later calls that already have their cloud
    // audio ready — breaking call order. Filling in-place preserves position.
    cleanText = cleanText
      .replace(/\bSpO2\b/gi, "S P O 2").replace(/\bEtCO2\b/gi, "E T C O 2")
      .replace(/\bBVM\b/gi, "B V M").replace(/\bSVN\b/gi, "S V N")
      .replace(/\bNRB\b/gi, "N R B").replace(/\bLPM\b/gi, "liters per minute")
      .replace(/\bbpm\b/gi, "beats per minute").replace(/\bmg\/dL\b/gi, "milligrams per deciliter");
    slot.url     = "__native__";
    slot.ready   = true;
    slot.cleanup = null;
    slot._text   = cleanText;
    slot._gender = gender;
    slot._age    = age;
    _playNextTts();
  }
}
```

#### Add `_playNextTts()` after the existing TTS state vars

```js
function _playNextTts() {
  if (_ttsAudioPlaying || isPopupOpen) return;
  // Skip slots that aren't ready yet (fetch still in flight)
  if (_ttsAudioQueue.length === 0 || !_ttsAudioQueue[0].ready) return;

  _ttsAudioPlaying = true;
  const slot = _ttsAudioQueue.shift();

  // Slot could not be synthesized by cloud or native TTS.
  if (slot.url === "__skip__") {
    _ttsAudioPlaying = false;
    _playNextTts();
    return;
  }

  // Native browser fallback slot
  if (slot.url === "__native__") {
    const utt = _makeUtterance(slot._text, slot._gender, slot._age);
    utt.onend = utt.onerror = () => { _ttsAudioPlaying = false; _playNextTts(); };
    synth.speak(utt);
    return;
  }

  const audio = new Audio(slot.url);
  audio.onended = () => { _ttsAudioPlaying = false; slot.cleanup?.(); _playNextTts(); };
  audio.onerror = () => { _ttsAudioPlaying = false; slot.cleanup?.(); _playNextTts(); };
  audio.play().catch((err) => {
    console.warn("Cloud TTS playback blocked or failed:", err);
    _ttsAudioPlaying = false;
    slot.cleanup?.();
    _playNextTts();
  });
}
```

#### Update `speakPendingIfAny` to flush the queue

`pendingSpeech` is no longer needed — both cloud and fallback speech go through `_ttsAudioQueue`. Simplify:

```js
function speakPendingIfAny() {
  if (!isTtsEnabled) return;
  if (!isPopupOpen) _playNextTts();
}
```

**No changes needed to the Medical Control TTS path** (`static/js/app.js:26095`) in Phase 2 — that's a separate call that can be upgraded in a later pass.

---

### Phase 3: Config + Environment

**`app/config.py`** — add to the `Settings` class:

```python
tts_provider: str = "browser"   # "browser" | "google" | "openai"
tts_cache_dir: str = "/tmp/tts_cache"
gemini_tts_model: str = "gemini-2.5-flash-tts"
openai_api_key: str = ""
openai_tts_model: str = "tts-1"
openai_tts_format: str = "mp3"
openai_tts_speed: float = 1.12
```

**`.env.example`** — add:

```
TTS_PROVIDER=browser
TTS_CACHE_DIR=/tmp/tts_cache

OPENAI_TTS_MODEL=tts-1
OPENAI_TTS_FORMAT=mp3
OPENAI_TTS_SPEED=1.12
# OPENAI_API_KEY=your_openai_api_key_here

GEMINI_TTS_MODEL=gemini-2.5-flash-tts
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

To activate cloud TTS locally, set `TTS_PROVIDER=openai` and provide `OPENAI_API_KEY`, or set `TTS_PROVIDER=google` after completing the Google setup.

---

### Phase 4: LLM Prompt Enrichment (after Phase 1-3 are stable and spike confirms tag behavior)

After the Phase 0 spike confirms which non-speech tags Gemini TTS actually supports, update the patient character system prompt in `app/ai_client.py` to emit those tags in patient dialogue. Do not update this prompt until the spike results are known — if `[cough]` and `[gasp]` don't produce respiratory sounds, use the `SynthesisInput(prompt=...)` "Director's Notes" path instead for clinical tone control.

---

## Testing Checklist

- [ ] **Phase 0 spike:** One-off script confirms Gemini TTS model name, voice names (Kore/Charon or updated), and whether `[cough]`/`[gasp]` produce respiratory sounds vs. reading the word aloud
- [ ] `app/auth.py` extraction: existing tests still pass after moving `get_active_context` and `limiter` out of `main.py`
- [ ] `TTS_PROVIDER=openai` activates OpenAI cloud path; `TTS_PROVIDER=google` activates Google cloud path; `TTS_PROVIDER=browser` stays on native browser synthesis
- [ ] TTS toggle OFF sends no `/api/tts` requests and creates no paid provider calls
- [ ] `/api/tts` returns 401 for unauthenticated requests
- [ ] `/api/tts` returns 429 when rate limit is exceeded (20/min per user)
- [ ] `/api/tts` returns 422 for text > 1000 chars
- [ ] Cache: second call with identical scenario/text/persona styling returns same bytes without a new provider call (log confirms cache hit)
- [ ] Cache key: changing scenario id, provider, model, voice, speed, format, prompt styling, clinical cues, or text invalidates the cache
- [ ] **Ordering:** Rapidly trigger 3 consecutive `speakText()` calls; audio plays in call order, not network-arrival order
- [ ] **Fallback:** With `TTS_PROVIDER=browser`, all audio routes through `window.speechSynthesis` with no paid cloud calls
- [ ] **Provider failure:** With `TTS_PROVIDER=openai` and forced provider failure, the app skips the failed line rather than switching to robotic native browser voice
- [ ] **OpenAI reliability:** Styled OpenAI timeout retries once with compact instructions and returns the same voice/model/text when provider behavior permits
- [ ] **Popup guard:** Speech queues correctly when a popup is open; plays in order after close
- [ ] `peds_asthma_01` scenario: audio plays when SpO2 drops and patient responds
- [ ] MC physician TTS (`_mc.ttsEnabled` at `app.js:26095`) still works — not touched by this change

### Latency / Cost Checklist

- [x] Scenario-start prewarm exists for deterministic `initial_complaint`, `history_response_map` answers, common Alex clarifiers, and popup prompts
- [x] Prewarm runs only when the learner has enabled TTS
- [x] Prewarm is best-effort and never blocks scenario start or chat interaction
- [x] Prewarm uses the same sentence chunking/cache payloads as playback
- [ ] Prewarmed lines hit cache during the scenario and start playback in under 500ms on a local browser test
- [ ] Static authored audio-pack contract is designed: scenario line IDs, voice/persona metadata, file path/URL, cache-busting, and fallback order
- [ ] Static audio packs are supported for deterministic lines before live provider generation
- [ ] Pilot scenarios selected for TTS have authored persona `tts` metadata for patient, family/bystanders, and partner
- [ ] TTS usage/cost logging distinguishes cache hit, prewarm generation, static audio, and live provider generation
- [ ] Per-tenant/user budget cap or quota alert exists before broad SaaS release

---

## Production Considerations (Phase 4+ / SaaS hardening)

- **Cache storage:** Replace `/tmp/tts_cache` with S3 or a persistent volume — `/tmp` is ephemeral in containerized deployments
- **Budget cap:** Set provider quota alerts and app-level usage caps to catch unexpected spikes
- **Audio format:** Default to MP3 for live browser playback reliability; evaluate Opus only after cross-browser testing
- **SSML migration:** If bracket tag support proves limited, migrate to SSML (`<speak>`) which gives precise control over prosody, pauses, and emphasis via the W3C standard
- **Audio packs:** Store production authored audio packs in versioned object storage or a CDN with explicit scenario/version paths
