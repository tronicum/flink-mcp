import asyncio

import httpx
from config import settings


class FlinkAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Flink API error {status_code}: {message}")


class FlinkClient:
    def __init__(self):
        self._token = settings.flink_token
        self._refresh_token = settings.flink_firebase_refresh_token
        self._hub_id = settings.flink_hub_id
        self._hub_slug = settings.flink_hub_slug
        self._base_url = settings.flink_base_url
        self._token_lock = asyncio.Lock()

    def _headers(self) -> dict:
        headers = {
            "User-Agent": "Flink/2026.13.0 (Android)",
            "Client-Version": "Android 2026.13.0",
            "locale": "de-DE",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._hub_id:
            headers["hub"] = self._hub_id
        if self._hub_slug:
            headers["hub-slug"] = self._hub_slug
        if settings.flink_datadome_cookie:
            headers["Cookie"] = f"datadome={settings.flink_datadome_cookie}"
        return headers

    def set_token(self, token: str) -> None:
        self._token = token

    def set_refresh_token(self, refresh_token: str) -> None:
        self._refresh_token = refresh_token

    def set_hub(self, hub_id: str, hub_slug: str) -> None:
        self._hub_id = hub_id
        self._hub_slug = hub_slug

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    @property
    def has_hub(self) -> bool:
        return bool(self._hub_id and self._hub_slug)

    async def _ensure_token(self) -> None:
        """Guarantee a valid Firebase ID token is available before making an API call.

        Priority:
          1. Already have a token → done.
          2. Have a refresh token → exchange for fresh ID token.
          3. No token at all → bootstrap via throwaway email sign-up (one-time).
        """
        if self._token:
            return
        async with self._token_lock:
            if self._token:
                return  # another coroutine already obtained a token
            if self._refresh_token:
                await self._do_refresh()
            else:
                # Bootstrap: sign-up creates a throwaway account and sets self._token.
                # After OTP verification the real account's tokens will replace this.
                from auth import bootstrap_firebase_token
                print("[FlinkClient] No Firebase token — bootstrapping via email sign-up...")
                await bootstrap_firebase_token(self)

    async def _do_refresh(self) -> bool:
        """Exchange the stored refresh token for a fresh Firebase ID token.

        Returns True on success. On failure logs and returns False.
        """
        if not self._refresh_token:
            return False
        try:
            from firebase import persist_refresh_token, refresh_id_token
            id_token, new_refresh = await refresh_id_token(self._refresh_token)
            self._token = id_token
            self._refresh_token = new_refresh
            persist_refresh_token(new_refresh)
            return True
        except Exception as exc:
            print(f"[FlinkClient] Token refresh failed: {exc}")
            return False

    async def get(self, path: str, params: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as http:
            response = await http.get(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=self._headers(),
                params=params,
                timeout=15.0,
            )
        if response.status_code == 401:
            async with self._token_lock:
                refreshed = await self._do_refresh()
            if refreshed:
                async with httpx.AsyncClient() as http:
                    response = await http.get(
                        f"{self._base_url}/{path.lstrip('/')}",
                        headers=self._headers(),
                        params=params,
                        timeout=15.0,
                    )
        return self._handle(response)

    async def put(self, path: str, json: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as http:
            response = await http.put(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=self._headers(),
                json=json or {},
                timeout=15.0,
            )
        if response.status_code == 401:
            async with self._token_lock:
                refreshed = await self._do_refresh()
            if refreshed:
                async with httpx.AsyncClient() as http:
                    response = await http.put(
                        f"{self._base_url}/{path.lstrip('/')}",
                        headers=self._headers(),
                        json=json or {},
                        timeout=15.0,
                    )
        return self._handle(response)

    async def post(self, path: str, json: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as http:
            response = await http.post(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=self._headers(),
                json=json or {},
                timeout=15.0,
            )
        if response.status_code == 401:
            async with self._token_lock:
                refreshed = await self._do_refresh()
            if refreshed:
                async with httpx.AsyncClient() as http:
                    response = await http.post(
                        f"{self._base_url}/{path.lstrip('/')}",
                        headers=self._headers(),
                        json=json or {},
                        timeout=15.0,
                    )
        return self._handle(response)

    def _handle(self, response: httpx.Response) -> dict:
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise FlinkAPIError(response.status_code, str(detail))
        try:
            return response.json()
        except Exception:
            return {"raw": response.text}


# Shared instance used by server.py
flink = FlinkClient()
