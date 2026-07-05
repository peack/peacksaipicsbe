from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config import API_KEY

security = HTTPBearer(auto_error=False)


def auth(
    api_key: Optional[str] = Query(default=None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if not API_KEY:
        return
    key = api_key or (creds.credentials if creds else None)
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")