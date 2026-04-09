from fastmcp import FastMCP
from client import flink, FlinkAPIError
from auth import send_otp, verify_otp

mcp = FastMCP("flink", instructions=(
    "Flink grocery delivery assistant. "
    "Auth flow (no setup needed — fully automated): "
    "  1. login(phone_number) — sends OTP SMS; auto-bootstraps Firebase auth internally. "
    "  2. verify_otp_code(phone_number, code) — verifies OTP, links phone to account. "
    "Then: find_hub() → set_active_hub() → list_products() → create_cart() → place_order(). "
    "If a call returns 401, the Firebase token has expired — "
    "the client auto-refreshes via the saved refresh token. "
    "google_signin() is an alternative for Google-linked accounts. "
    "IMPORTANT — delivery coordinates: the rider navigates primarily to the GPS coordinates, "
    "NOT the street address. Wrong coordinates = cancelled order. "
    "Always use precise coordinates (right-click in Google Maps → 'What's here?'). "
    "The street address is still required and must match the coordinates exactly."
))


# ---------------------------------------------------------------------------
# Auth — Google OAuth → Firebase (preferred, automated)
# ---------------------------------------------------------------------------

@mcp.tool()
async def google_signin() -> str:
    """
    Authenticate via Google OAuth2 → Firebase.

    Opens the user's browser for Google sign-in, catches the callback on
    http://localhost:8080, and exchanges for a Firebase ID token.
    The Firebase refresh token is persisted to .env so future server starts
    skip this step.

    Call this once before any consumer-backend endpoint (products, cart, OTP, etc.).
    """
    from google_oauth import get_firebase_tokens_via_google
    from firebase import persist_refresh_token

    firebase_id_token, firebase_refresh_token = await get_firebase_tokens_via_google()
    flink.set_token(firebase_id_token)
    flink.set_refresh_token(firebase_refresh_token)
    return "Google sign-in successful. Firebase token set and refresh token saved to .env."


# ---------------------------------------------------------------------------
# Auth — Manual token injection (bootstrap for phone-only accounts)
# ---------------------------------------------------------------------------

@mcp.tool()
async def set_firebase_token(id_token: str) -> str:
    """
    Manually inject a Firebase ID token to bootstrap authentication.

    Use this when google_signin() fails because your Flink account was created
    via phone OTP only (not Google/Apple OAuth).

    HOW TO GET THE TOKEN (one-time setup):
      Option A — HTTP Toolkit (easiest):
        1. Download HTTP Toolkit (httptoolkit.com) on your Mac
        2. Launch it and choose "Android device via ADB"
        3. Open the Flink app on your phone — any screen that loads products
        4. In HTTP Toolkit, find any request to api.goflink.com/consumer-backend/
        5. Copy the Authorization header value (everything after "Bearer ")

      Option B — browser localStorage (if web app accessible):
        1. Open goflink.com in a browser and sign in with your phone
        2. Open DevTools → Application → Local Storage → flink-core-prod.firebaseapp.com
        3. Find the key starting with "firebase:authUser:" and copy idToken

    Once set, call login() + verify_otp_code() to get a permanent refresh token
    that survives server restarts automatically.
    """
    flink.set_token(id_token)
    return "Firebase ID token set. Call login() + verify_otp_code() to get a permanent refresh token."


# ---------------------------------------------------------------------------
# Auth — Email + password (if account has a password set via web)
# ---------------------------------------------------------------------------

@mcp.tool()
async def email_login(email: str, password: str) -> str:
    """Authenticate with Flink email + password. Persists refresh token to .env.

    Use this if your account has a password set (e.g. via password reset on goflink.com).
    This authenticates as your real Flink account — no OTP or Proxyman needed.
    """
    from firebase import persist_refresh_token, sign_in_with_custom_token
    result = await flink.post("consumer-backend/customer-http/v1/login/email", json={
        "email": email,
        "password": password,
    })
    custom_token = result.get("access_token") or (result.get("data") or {}).get("token")
    if not custom_token:
        return f"Login failed — no token in response: {result}"
    id_token, refresh_token = await sign_in_with_custom_token(custom_token)
    flink.set_token(id_token)
    flink.set_refresh_token(refresh_token)
    persist_refresh_token(refresh_token)
    return "Authenticated as real account. Refresh token saved to .env."


# ---------------------------------------------------------------------------
# Auth — Phone OTP (alternative if Google login is unavailable)
# ---------------------------------------------------------------------------

@mcp.tool()
async def login(phone_number: str, country_code: str = "+49") -> str:
    """Send an OTP SMS to the given phone number. Call verify_otp_code() once the SMS arrives.

    No prior authentication needed — Firebase auth is bootstrapped automatically
    if no token is present. Just call this and wait for the SMS.
    """
    await send_otp(flink, phone_number, country_code)
    return f"OTP sent to {country_code}{phone_number}. Check your SMS and call verify_otp_code()."


@mcp.tool()
async def verify_otp_code(phone_number: str, code: str, country_code: str = "+49") -> str:
    """Complete OTP login by providing the code from your SMS. Stores the token for this session."""
    token = await verify_otp(flink, phone_number, country_code, code)
    return f"Authenticated successfully. Token saved (first 20 chars: {token[:20]}...)."


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_profile() -> dict:
    """Get the current user's Flink profile. May include active cart ID if stored server-side."""
    return await flink.get("consumer-backend/customer-http/v1/me")


# ---------------------------------------------------------------------------
# Hub discovery
# ---------------------------------------------------------------------------

@mcp.tool()
async def find_hub(lat: float, lon: float) -> list[dict]:
    """Find the nearest Flink hubs for given coordinates. Returns hub IDs, slugs and addresses."""
    # hub-locator is at the root (no auth needed)
    result = await flink.get(
        "hub-locator/hub-locator/v1/locations/hub",
        params={"lat": lat, "long": lon},
    )
    if isinstance(result, list):
        return result
    return result.get("hubs") or result.get("data") or [result]


@mcp.tool()
async def get_hub(hub_id: str) -> dict:
    """Get details for a specific hub by ID."""
    return await flink.get(f"consumer-backend/hub/v1/hubs/{hub_id}")


@mcp.tool()
async def set_active_hub(hub_id: str, hub_slug: str) -> str:
    """Set the active hub for all subsequent product and cart calls. Persists to .env."""
    from firebase import persist_env_vars
    flink.set_hub(hub_id, hub_slug)
    persist_env_vars(FLINK_HUB_ID=hub_id, FLINK_HUB_SLUG=hub_slug)
    return f"Active hub set to {hub_id} ({hub_slug}) and saved to .env."


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_products() -> dict:
    """Return the home screen / product catalog for the active hub."""
    if not flink.has_hub:
        return {"error": "No active hub set. Call set_active_hub() first."}
    return await flink.get("consumer-backend/homescreen/v2/home")


@mcp.tool()
async def search_products(query: str) -> dict:
    """Search for products by name at the active hub."""
    if not flink.has_hub:
        return {"error": "No active hub set. Call set_active_hub() first."}
    return await flink.get("consumer-backend/discovery/v2/search", params={"query": query})


@mcp.tool()
async def get_product_stock(skus: list[str]) -> dict:
    """Check stock/availability for a list of product SKUs."""
    if not flink.has_hub:
        return {"error": "No active hub set. Call set_active_hub() first."}
    return await flink.post(
        "consumer-backend/discovery/v1/products/amounts-by-sku",
        json={"skus": skus},
    )


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_to_cart(cart_id: str, sku: str, quantity: int) -> dict:
    """Add or update an item in an existing cart (e.g. the app's active cart).

    Fetches the current cart, merges the item into the lines, then PUTs back.
    Set quantity=0 to remove an item.
    """
    cart = await flink.get(f"consumer-backend/cart/v3/cart/{cart_id}")

    # Extract existing lines and delivery coordinates from the cart response
    existing_lines: list[dict] = cart.get("lines") or cart.get("order", {}).get("lines") or []
    coords = cart.get("delivery_coordinates") or cart.get("order", {}).get("delivery_coordinates") or {}
    lat = coords.get("latitude", 52.5089)
    lon = coords.get("longitude", 13.4523)

    # Merge: update existing item or append
    lines = {l["product_sku"]: l["quantity"] for l in existing_lines if "product_sku" in l}
    if quantity == 0:
        lines.pop(sku, None)
    else:
        lines[sku] = quantity

    return await flink.put(f"consumer-backend/cart/v3/cart/{cart_id}", json={
        "lines": [{"product_sku": k, "quantity": v} for k, v in lines.items()],
        "delivery_coordinates": {"latitude": lat, "longitude": lon},
        "promised_delivery_time": 0,
    })

@mcp.tool()
async def create_cart(
    items: list[dict],
    delivery_lat: float,
    delivery_lon: float,
    street_address_1: str,
    house_number: str,
    city: str,
    postal_code: str,
    first_name: str,
    last_name: str,
    phone: str,
    country: str = "DE",
    floor_number: str = "",
    name_on_doorbell: str = "",
    building_type: str = "",
    building_location: str = "",
) -> dict:
    """
    Build a cart with the given items and return it for review.
    Does NOT place the order — call place_order() after confirming.

    items format: [{"sku": "product-sku-123", "quantity": 2}, ...]

    IMPORTANT: delivery_lat/delivery_lon are the primary delivery target — the rider
    navigates to these coordinates, not the street address. Use precise coordinates
    (right-click your front door in Google Maps → 'What's here?'). Wrong coordinates
    will cause the order to be cancelled. The address fields are also required and
    must match the coordinates.
    """
    if not flink.has_hub:
        return {"error": "No active hub set. Call set_active_hub() first."}

    address = {
        "tag": "home",
        "street_address_1": street_address_1,
        "house_number": house_number,
        "city": city,
        "postal_code": postal_code,
        "country": country,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "floor_number": floor_number,
        "name_on_doorbell": name_on_doorbell,
        "building_type": building_type,
        "building_location": building_location,
    }
    lines = [{"product_sku": item["sku"], "quantity": item["quantity"]} for item in items]

    return await flink.post("consumer-backend/cart/v3/cart", json={
        "lines": lines,
        "delivery_coordinates": {"latitude": delivery_lat, "longitude": delivery_lon},
        "billing_address": address,
        "shipping_address": address,
    })


@mcp.tool()
async def get_cart(cart_id: str) -> dict:
    """Retrieve current cart details and status by cart ID."""
    return await flink.get(f"consumer-backend/cart/v3/cart/{cart_id}")


@mcp.tool()
async def add_promo_code(cart_id: str, voucher_code: str) -> dict:
    """Apply a promo or discount code to an existing cart."""
    return await flink.post(
        f"consumer-backend/cart/v3/cart/{cart_id}/add-promo-code",
        json={"voucher_code": voucher_code},
    )


# ---------------------------------------------------------------------------
# Payment methods
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_payment_methods() -> dict:
    """Fetch saved payment methods for orders (Klarna, PayPal, card, etc.).

    Returns clientConfig (Adyen keys) and paymentMethods with:
      - available: payment method types enabled for the hub
      - tokens: saved/tokenized methods — each has type, name, token (use in place_order)
      - default: the user's default payment method

    The 'token' field on each saved method is what place_order() needs.
    """
    if not flink.has_hub:
        return {"error": "No active hub set. Call set_active_hub() first."}
    return await flink.get("consumer-backend/payment-bff/v1/payment-methods/orders")


# ---------------------------------------------------------------------------
# Order placement (last step — payment may require completing in the app)
# ---------------------------------------------------------------------------

@mcp.tool()
async def place_order(
    cart_id: str,
    stored_payment_id: str | None = None,
    payment_type: str = "paypal",
    amount: float | None = None,
) -> dict:
    """
    Submit the cart as a real order using a stored payment method.

    Flow:
      1. Call get_payment_methods() — find your saved method in paymentMethods.tokens[]
      2. Pass its 'token' field as stored_payment_id and its 'type' as payment_type
      3. amount is fetched from the cart automatically (totalPrice.centAmount / 100)

    Example:
      place_order(cart_id="...", stored_payment_id="M6ZWC62H3QZKNCQ9", payment_type="paypal")
    """
    import json as _json

    body: dict = {}
    if stored_payment_id:
        if amount is None:
            cart = await flink.get(f"consumer-backend/cart/v3/cart/{cart_id}")
            cent_amount = (
                (cart.get("totalPrice") or {}).get("centAmount")
                or (cart.get("order", {}).get("totalPrice") or {}).get("centAmount")
                or 0
            )
            amount = cent_amount / 100 if cent_amount else 0.0

        # Build Adyen PaymentComponentData JSON string (what the SDK would normally generate).
        # Amount must be in minor units (cents) inside the payment data.
        cent_amount = int(round(amount * 100)) if amount < 100 else int(amount)
        adyen_payment_data = _json.dumps({
            "paymentMethod": {
                "type": payment_type,
                "storedPaymentMethodId": stored_payment_id,
            },
            "amount": {"currency": "EUR", "value": cent_amount},
            "shopperInteraction": "ContAuth",
            "recurringProcessingModel": "Subscription",
            "returnUrl": "http://localhost:9999",
        }, separators=(",", ":"))
        body = {"amount": cent_amount, "token": adyen_payment_data}

    try:
        result = await flink.post(f"consumer-backend/cart/v1/cart/{cart_id}/checkout", json=body or None)
        if result.get("confirmation_needed"):
            import json as _j
            cd = result.get("confirmation_data", "{}")
            if isinstance(cd, str):
                cd = _j.loads(cd)
            result["_next_step"] = (
                f"Open this URL in your browser to authorize payment in PayPal: {cd.get('url')} "
                f"After approving, PayPal redirects to flink://checkout?... — "
                f"copy the full redirect URL and call confirm_order(cart_id='{cart_id}', redirect_url='...')"
            )
        return result
    except FlinkAPIError as e:
        return {
            "error": str(e),
            "hint": (
                "If this is a payment error, call get_payment_methods() to retrieve "
                "a saved payment method, then retry with place_order(cart_id, stored_payment_id=..., payment_type=...)."
            ),
        }


@mcp.tool()
async def confirm_order(cart_id: str, redirect_url: str) -> dict:
    """
    Finalize an order after PayPal redirect authorization.

    After place_order() returns confirmation_needed=true:
      1. Open the URL from confirmation_data in your browser
      2. Authorize the payment in PayPal
      3. PayPal redirects to flink://checkout?redirectResult=... (or similar params)
      4. Copy the full redirect URL and pass it here

    This sends the redirect result to Flink to complete the order.
    """
    import urllib.parse as _up
    import json as _j

    parsed = _up.urlparse(redirect_url)
    params = dict(_up.parse_qsl(parsed.query))

    # Adyen redirect result comes back as redirectResult or payload
    redirect_result = params.get("redirectResult") or params.get("payload") or redirect_url

    adyen_action_data = _j.dumps({"details": {"redirectResult": redirect_result}}, separators=(",", ":"))

    return await flink.post(
        f"consumer-backend/cart/v1/cart/{cart_id}/checkout/details",
        json={"token": adyen_action_data},
    )


if __name__ == "__main__":
    mcp.run()
