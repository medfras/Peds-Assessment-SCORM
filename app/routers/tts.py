from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.auth import ActiveContext, get_active_context, limiter
from app.config import settings
from app.logging_config import get_logger
from app.services.tts_service import generate_speech, last_generation_meta

log = get_logger("app.routers.tts")
router = APIRouter(prefix="/api/tts", tags=["tts"])

_OPENAI_TTS_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
}


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    scenario_id: str | None = Field(default=None, max_length=120)
    speaker_role: Literal["patient", "bystander", "alex", "lexi", "physician"] = "bystander"
    gender: Literal["male", "female"] | None = None
    age: Literal["child", "elderly"] | None = None
    provider_voice: Literal[
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
    ] | None = None
    demeanor: str | None = Field(default=None, max_length=300)
    delivery: str | None = Field(default=None, max_length=300)
    avoid: str | None = Field(default=None, max_length=300)
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    spo2: int = Field(default=98, ge=0, le=100)
    rr: int = Field(default=16, ge=0, le=60)


@router.post("")
@limiter.limit(f"{settings.rate_limit_chat}/minute")
async def synthesize(
    request: Request,
    req: TTSRequest,
    ctx: ActiveContext = Depends(get_active_context),
):
    if settings.tts_provider not in ("google", "openai"):
        raise HTTPException(status_code=503, detail="Cloud TTS not configured")
    try:
        audio = await run_in_threadpool(
            generate_speech,
            text=req.text,
            scenario_id=req.scenario_id,
            speaker_role=req.speaker_role,
            gender=req.gender,
            age=req.age,
            provider_voice=req.provider_voice,
            demeanor=req.demeanor,
            delivery=req.delivery,
            avoid=req.avoid,
            speed=req.speed,
            spo2=req.spo2,
            rr=req.rr,
        )
        media_type = "audio/mpeg"
        if settings.tts_provider == "openai":
            media_type = _OPENAI_TTS_MEDIA_TYPES.get(settings.openai_tts_format, "audio/mpeg")
        response = Response(content=audio, media_type=media_type)
        meta = last_generation_meta()
        if meta:
            response.headers["X-TTS-Provider"] = str(meta.get("provider") or "")
            response.headers["X-TTS-Model"] = str(meta.get("model") or "")
            response.headers["X-TTS-Voice"] = str(meta.get("voice") or "")
            response.headers["X-TTS-Role"] = str(meta.get("role") or "")
            response.headers["X-TTS-Speed"] = str(meta.get("speed") or "")
            response.headers["X-TTS-Scenario"] = str(meta.get("scenario_id") or "")
        return response
    except Exception as exc:
        log.exception("tts_synthesis_failed", user_id=ctx.user_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Audio generation failed")
