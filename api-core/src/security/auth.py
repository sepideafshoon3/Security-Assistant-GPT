"""
Minimal auth placeholder.

In a real system:
- Use proper auth (OAuth2/JWT/etc.).
- Limit access to trusted operators only.
"""

from fastapi import Header, HTTPException


async def require_api_key(x_api_key: str = Header(...)) -> None:
    # Placeholder: replace with a secure check or remove if using other auth.
    if x_api_key != "dev-key":
        raise HTTPException(status_code=401, detail="Invalid API key")
