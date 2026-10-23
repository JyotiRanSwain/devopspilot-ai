"""Optional bearer-token authentication for the API."""
import hmac

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings, get_settings


def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if not settings.api_token:
        return
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), settings.api_token.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid API token.",
                            headers={"WWW-Authenticate": "Bearer"})
