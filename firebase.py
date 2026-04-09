"""
Firebase REST auth helpers.

Operations:
  1. refresh_id_token(refresh_token)           → (id_token, refresh_token)
  2. sign_in_with_google(google_id_token)      → (id_token, refresh_token)
  3. sign_in_with_custom_token(custom_token)   → (id_token, refresh_token)
     Used after Flink OTP: Flink backend returns a Firebase custom token;
     this exchanges it for a proper ID + refresh token pair.
"""

import httpx
from pathlib import Path

FIREBASE_API_KEY = "AIzaSyB1d_TI3VVh6c0QHe_jOTph4hvMOydZyvg"
_TOKEN_URL = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
_IDP_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key={FIREBASE_API_KEY}"
_CUSTOM_TOKEN_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_API_KEY}"


async def refresh_id_token(refresh_token: str) -> tuple[str, str]:
    """Exchange a Firebase refresh token for a fresh ID token.

    Returns (id_token, new_refresh_token).
    """
    async with httpx.AsyncClient() as http:
        r = await http.post(
            _TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=10.0,
        )
    r.raise_for_status()
    data = r.json()
    return data["id_token"], data["refresh_token"]


async def sign_in_with_google(google_id_token: str) -> tuple[str, str]:
    """Exchange a Google ID token for a Firebase ID token + refresh token.

    Returns (firebase_id_token, firebase_refresh_token).
    """
    async with httpx.AsyncClient() as http:
        r = await http.post(
            _IDP_URL,
            json={
                "postBody": f"id_token={google_id_token}&providerId=google.com",
                "requestUri": "http://localhost:8080",
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
            timeout=10.0,
        )
    r.raise_for_status()
    data = r.json()
    return data["idToken"], data["refreshToken"]


async def sign_in_with_custom_token(custom_token: str) -> tuple[str, str]:
    """Exchange a Firebase custom token (issued by Flink backend after OTP) for
    a proper Firebase ID token + refresh token pair.

    Returns (firebase_id_token, firebase_refresh_token).
    """
    async with httpx.AsyncClient() as http:
        r = await http.post(
            _CUSTOM_TOKEN_URL,
            json={"token": custom_token, "returnSecureToken": True},
            timeout=10.0,
        )
    r.raise_for_status()
    data = r.json()
    return data["idToken"], data["refreshToken"]


def persist_env_vars(**kwargs: str) -> None:
    """Write one or more key=value pairs to .env, updating existing lines in place."""
    env_path = Path(".env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(kwargs)
    new_lines = []
    for line in lines:
        matched = False
        for key in list(remaining):
            if line.startswith(f"{key}=") or line == key:
                new_lines.append(f"{key}={remaining.pop(key)}")
                matched = True
                break
        if not matched:
            new_lines.append(line)
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def persist_refresh_token(token: str) -> None:
    persist_env_vars(FLINK_FIREBASE_REFRESH_TOKEN=token)
