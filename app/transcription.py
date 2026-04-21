from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import HTTPException, UploadFile, status

from app.config import Settings


def _bool_value(value: bool) -> str:
    return "true" if value else "false"


async def transcribe_with_xai(
    *,
    settings: Settings,
    upload: UploadFile,
    language: str | None,
    diarize: bool,
    multichannel: bool,
    channels: int | None,
    audio_format: str | None,
    sample_rate: int | None,
    apply_formatting: bool,
) -> Mapping[str, Any]:
    if not settings.xai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="xai stt is not configured",
        )

    file_bytes = await upload.read()
    return await transcribe_bytes_with_xai(
        settings=settings,
        filename=upload.filename or "audio.bin",
        file_bytes=file_bytes,
        content_type=upload.content_type or "application/octet-stream",
        language=language,
        diarize=diarize,
        multichannel=multichannel,
        channels=channels,
        audio_format=audio_format,
        sample_rate=sample_rate,
        apply_formatting=apply_formatting,
    )


async def transcribe_bytes_with_xai(
    *,
    settings: Settings,
    filename: str,
    file_bytes: bytes,
    content_type: str,
    language: str | None,
    diarize: bool,
    multichannel: bool,
    channels: int | None,
    audio_format: str | None,
    sample_rate: int | None,
    apply_formatting: bool,
) -> Mapping[str, Any]:
    if not settings.xai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="xai stt is not configured",
        )

    data: dict[str, str] = {"format": _bool_value(apply_formatting), "diarize": _bool_value(diarize)}
    if language:
        data["language"] = language
    if multichannel:
        data["multichannel"] = "true"
    if channels is not None:
        data["channels"] = str(channels)
    if audio_format:
        data["audio_format"] = audio_format
    if sample_rate is not None:
        data["sample_rate"] = str(sample_rate)

    files = {
        "file": (
            filename or "audio.bin",
            file_bytes,
            content_type or "application/octet-stream",
        )
    }

    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(settings.xai_stt_url, headers=headers, data=data, files=files)

    if response.status_code >= 400:
        detail = response.text.strip() or "xai stt request failed"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"xai stt error: {detail}")

    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="xai stt returned a non-object payload")
    return payload
