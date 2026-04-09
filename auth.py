"""
OTP-based authentication for the Flink consumer API.

Flow:
  1. send_otp(phone_number, country_code)  → triggers SMS
  2. verify_otp(phone_number, country_code, code)
       → PUT customer-http/v1/me with ActionDto (phoneNumber + verificationCode)
       → on success the bootstrap Firebase token is now valid for shopping
"""

import uuid

import httpx

from client import FlinkClient
from firebase import persist_refresh_token, sign_in_with_custom_token


async def bootstrap_firebase_token(client: FlinkClient) -> None:
    """Create a throwaway Flink email account to get a valid Firebase ID token.

    Used as a one-time bootstrap when no Firebase token or refresh token is
    available. After successful OTP verification the real account's tokens
    replace this throwaway token — the throwaway account is never used again.

    Flink's sign-up endpoint requires no authentication, so this breaks the
    circular dependency (send-otp needs a token, but we have no token yet).
    """
    from config import settings

    rand = uuid.uuid4().hex[:10]
    email = f"bootstrap{rand}@mailnull.com"
    password = f"B00t{rand[:6]}X!"

    headers = {
        "User-Agent": "Flink/2026.13.0 (Android)",
        "Client-Version": "Android 2026.13.0",
        "locale": "de-DE",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if settings.flink_datadome_cookie:
        headers["Cookie"] = f"datadome={settings.flink_datadome_cookie}"

    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"{settings.flink_base_url}/consumer-backend/users/v1/me/sign-up",
            headers=headers,
            json={"first_name": "Bootstrap", "last_name": "User", "email": email, "password": password},
            timeout=15.0,
        )

    if r.status_code not in (200, 201):
        raise RuntimeError(f"Bootstrap sign-up failed {r.status_code}: {r.text[:200]}")

    custom_token = r.json().get("access_token")
    if not custom_token:
        raise RuntimeError(f"Bootstrap sign-up returned no access_token: {r.text[:200]}")

    # Exchange Firebase custom token → ID token (don't save refresh token — throwaway)
    id_token, _ = await sign_in_with_custom_token(custom_token)
    client.set_token(id_token)


async def send_otp(client: FlinkClient, phone_number: str, country_code: str) -> None:
    """POST consumer-backend/customer-http/v1/send-otp — triggers SMS."""
    await client.post("consumer-backend/customer-http/v1/send-otp", json={
        "countryCode": country_code,
        "number": phone_number,
        "channel": "sms",
    })


async def verify_otp(client: FlinkClient, phone_number: str, country_code: str, code: str) -> str:
    """Verify OTP via PUT customer-http/v1/me with ActionDto.

    Links the verified phone number to the current (bootstrap) Firebase account.
    The bootstrap Firebase token remains valid for all subsequent API calls.

    Returns the current Firebase ID token.
    """
    try:
        await client.put("consumer-backend/customer-http/v1/me", json={
            "action": {
                "phoneNumber": {
                    "countryCode": country_code,
                    "number": phone_number,
                },
                "verificationCode": code,
            }
        })
    except Exception as e:
        if "409" in str(e) or "phone number already linked" in str(e).lower():
            # Phone is linked to another account — force re-link with override=true
            await client.put("consumer-backend/customer-http/v1/me", json={
                "action": {
                    "phoneNumber": {
                        "countryCode": country_code,
                        "number": phone_number,
                    },
                    "verificationCode": code,
                    "override": True,
                }
            })
        else:
            raise
    # PUT /me returns the updated profile — the bootstrap token stays valid.
    # Persist the refresh token so it survives restarts.
    if client._refresh_token:
        persist_refresh_token(client._refresh_token)
    return client._token
