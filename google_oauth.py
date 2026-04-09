"""
Google sign-in via Google Identity Services (GIS) → Flink social-sign-up → Firebase tokens.

Why GIS instead of Firebase JS SDK:
  Firebase's beforeCreate Cloud Function blocks client-side sign-ups with
  "Direct sign-ups forbidden, use Flink API instead."  This fires for any
  new user created via Firebase's signInWithIdp — including Google.

  Solution: get a raw Google ID token using GIS (accounts.google.com/gsi/client),
  bypassing Firebase entirely for the OAuth step. Then:
    1. POST consumer-backend/users/v1/me/social-sign-up  (Authorization: Bearer <google_id_token>)
       This creates/confirms the Flink user server-side, which also handles Firebase user
       creation via Admin SDK (bypassing beforeCreate).
    2. Call Firebase signInWithIdp with the same Google ID token → Firebase ID + refresh tokens.

Returns (firebase_id_token, firebase_refresh_token).
"""

import asyncio
import base64
import http.server
import json
import os
import threading

from firebase import persist_refresh_token, sign_in_with_google

_REDIRECT_URI = "http://localhost:8080"
_CLIENT_ID = "946302416611-lt9egl5tv5k82eg5u67msnj4p2a9d70v.apps.googleusercontent.com"


def _generate_nonce() -> str:
    """32 random bytes, URL-safe base64 (matches Android app's GenerateNonce.kt)."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload without verification (for extracting name/email claims)."""
    try:
        payload = token.split(".")[1]
        # Add padding if needed
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _build_relay_html(nonce: str) -> str:
    """Relay page using Google Identity Services to get a Google ID token.

    GIS handles the OAuth flow natively and calls our callback with the credential.
    The nonce is embedded in the ID token so the backend can verify it.
    """
    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Flink sign-in</title>
  <style>
    body {{ font-family: sans-serif; display: flex; flex-direction: column;
           align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
    #status {{ margin-bottom: 20px; font-size: 16px; color: #333; }}
    #signin-btn {{ margin-top: 20px; }}
  </style>
  <script src="https://accounts.google.com/gsi/client" async defer></script>
</head>
<body>
  <div id="status">Loading Google sign-in...</div>

  <div id="g_id_onload"
       data-client_id="{_CLIENT_ID}"
       data-callback="handleCredentialResponse"
       data-nonce="{nonce}"
       data-auto_prompt="false"
       data-context="signin">
  </div>
  <div class="g_id_signin"
       data-type="standard"
       data-shape="rectangular"
       data-theme="outline"
       data-text="sign_in_with"
       data-size="large">
  </div>

  <script>
    document.addEventListener('DOMContentLoaded', function() {{
      document.getElementById('status').textContent =
        'Click the button below to sign in with your Google account.';
    }});

    function handleCredentialResponse(response) {{
      document.getElementById('status').textContent = 'Google sign-in successful — sending token...';
      fetch('/token', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          idToken: response.credential,
          nonce: '{nonce}'
        }})
      }}).then(function() {{
        document.getElementById('status').textContent =
          'Sign-in complete. You can close this tab.';
      }}).catch(function(err) {{
        document.getElementById('status').textContent = 'Error sending token: ' + err;
        fetch('/error', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{error: err.toString()}})
        }});
      }});
    }}

    // If GIS fails to load, show manual instructions
    setTimeout(function() {{
      var status = document.getElementById('status');
      if (status.textContent === 'Loading Google sign-in...') {{
        status.textContent =
          'Google sign-in failed to load. ' +
          'Check that http://localhost is an authorized JavaScript origin for the Flink app.';
      }}
    }}, 5000);
  </script>
</body>
</html>
"""


def _wait_for_token(relay_html: str, timeout: int = 120) -> dict:
    """Serve relay page + /token endpoint; block until GIS POSTs the credential."""
    result: list[dict] = []
    error: list[dict] = []
    event = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(relay_html.encode())

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            try:
                data = json.loads(body)
            except Exception:
                data = {"raw": body.decode()}
            if "/error" in self.path:
                error.append(data)
            else:
                result.append(data)
            event.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8080), _Handler)
    server.timeout = 1

    def _serve():
        while not event.is_set():
            server.handle_request()
        server.server_close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    if not event.wait(timeout=timeout):
        raise TimeoutError("Google sign-in not completed within timeout.")
    if error:
        raise RuntimeError(f"Google sign-in error: {error[0]}")
    return result[0]


async def get_firebase_tokens_via_google() -> tuple[str, str]:
    """GIS sign-in → Flink social-sign-up → Firebase ID + refresh tokens.

    Opens browser to http://localhost:8080. User clicks "Sign in with Google".
    GIS handles OAuth → returns Google ID token → Python calls:
      1. POST consumer-backend/users/v1/me/social-sign-up  (creates/confirms account)
      2. Firebase signInWithIdp  (returns Firebase ID + refresh tokens)

    Returns (firebase_id_token, firebase_refresh_token).
    Persists the Firebase refresh token to .env.
    """
    import webbrowser
    import httpx

    nonce = _generate_nonce()
    relay_html = _build_relay_html(nonce)

    print("\nOpening browser to http://localhost:8080 — sign in with your Google account.\n")
    webbrowser.open(_REDIRECT_URI)

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(None, lambda: _wait_for_token(relay_html))

    google_id_token = payload.get("idToken")
    if not google_id_token:
        raise ValueError(f"No idToken in payload: {payload}")

    # Extract name from Google ID token claims
    claims = _decode_jwt_claims(google_id_token)
    first_name = claims.get("given_name", "")
    last_name = claims.get("family_name", "")

    # Step 1: social-sign-up — creates/confirms Flink account via backend Admin SDK
    # (bypasses Firebase beforeCreate Cloud Function)
    from config import settings
    headers = {
        "Authorization": f"Bearer {google_id_token}",
        "locale": "de-DE",
        "User-Agent": "Flink/2026.13.0 (Android)",
        "Client-Version": "Android 2026.13.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if settings.flink_datadome_cookie:
        headers["Cookie"] = f"datadome={settings.flink_datadome_cookie}"

    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"{settings.flink_base_url}/consumer-backend/users/v1/me/social-sign-up",
            headers=headers,
            json={"first_name": first_name, "last_name": last_name, "nonce": nonce},
            timeout=15.0,
        )

    if r.status_code == 204:
        print("[google_signin] social-sign-up: existing user (204).")
    elif r.status_code in (200, 201):
        print("[google_signin] social-sign-up: new user created.")
    else:
        print(f"[google_signin] social-sign-up returned {r.status_code}: {r.text[:200]}")
        # Non-fatal: proceed to Firebase sign-in anyway

    # Step 2: Firebase signInWithIdp → Firebase ID + refresh tokens
    firebase_id_token, firebase_refresh_token = await sign_in_with_google(google_id_token)

    persist_refresh_token(firebase_refresh_token)
    return firebase_id_token, firebase_refresh_token
