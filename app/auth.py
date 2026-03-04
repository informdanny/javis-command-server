from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def require_agent_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_agent_key: Annotated[str | None, Header()] = None,
) -> None:
    if not x_agent_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing x-agent-key")
    if x_agent_key != settings.agent_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid x-agent-key")
