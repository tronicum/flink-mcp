# flink-mcp

A [FastMCP](https://github.com/jlowin/fastmcp) server that wraps the unofficial Flink grocery delivery API, enabling Claude (or any MCP client) to browse products, build a cart, and place real orders — fully headless.

> **Unofficial.** This uses the reverse-engineered Flink consumer API (`api.goflink.com`). Field names, endpoint paths and auth flows were derived by decompiling the Android APK (v2026.13.0) using jadx. It may break if Flink changes their API.

> **Disclaimer.** This project is for educational and personal use only. It automates access to Flink's private, undocumented API, which likely violates their Terms of Service. Use at your own risk. The author is not affiliated with Flink and takes no responsibility for account suspension, order issues, or any other consequences of use.

## Status

**Working end-to-end.** A real order was placed on 2026-04-04. The full flow — auth, hub selection, product discovery, cart creation, payment, and order placement — is automated. The only manual step per order is a PayPal browser redirect (~5 seconds).

## How it works

Flink has no public API. The endpoints, request/response shapes and auth flows were reverse-engineered from the APK. Key findings:

- **Auth:** Firebase ID tokens (short-lived, ~1h). The server auto-refreshes via a persisted refresh token so you only authenticate once.
- **Payment:** Flink uses Adyen as its payment processor. Stored PayPal billing agreements are returned by a `payment-bff` endpoint. The checkout endpoint accepts an Adyen `PaymentComponentData` JSON string — no SDK required for recurring payments.
- **Delivery coordinates:** The rider navigates to GPS coordinates, not the street address. Precise coordinates (right-click in Google Maps) are mandatory — wrong coordinates cause order cancellation.

See `openapi.yaml` for the full API surface and `MCP.md` for the MCP tool reference.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```bash
cp .env.example .env
```

## Authentication

The recommended flow is email + password, which requires a one-time setup via the Flink website:

1. Go to `goflink.com`, log in with your phone number, then set a password via account settings or password reset
2. Call `email_login(email="...", password="...")` — authenticates as your real account and persists the Firebase refresh token to `.env`
3. All subsequent server starts auto-refresh the token from `.env` — no re-login needed

For phone-only accounts without a password, use `login(phone_number)` + `verify_otp_code(phone_number, code)`.

## Payment setup (one-time)

Before placing orders you need a saved PayPal billing agreement:

1. Open the Flink app, go to checkout, and complete one order using PayPal
2. This saves your PayPal account as a stored payment method in Adyen
3. Call `get_payment_methods()` — you should see PayPal in the `tokens` array
4. The `token` value from that response is reusable for all future orders

## Running

```bash
# Development (with MCP inspector)
fastmcp dev server.py

# Production / Claude Desktop
fastmcp install server.py --name flink
```

## Order flow

```
1. get_payment_methods()
   → note the PayPal token (e.g. "M6ZWC62H3QZKNCQ9")

2. find_hub(lat=52.50, lon=13.45)
   set_active_hub(hub_id, hub_slug)

3. search_products(query="Milch") / list_products()
   → find SKUs

4. create_cart(
       items=[{"sku": "...", "quantity": 1}],
       delivery_lat=52.5011,   # precise — rider navigates here
       delivery_lon=13.4547,
       street_address_1="Markgrafendamm",
       house_number="4",
       ...
   )

5. place_order(cart_id, stored_payment_id="M6ZWC62H3QZKNCQ9", payment_type="paypal")
   → returns confirmation_needed: true + PayPal redirect URL

6. Open the URL in a browser, approve in PayPal (~5s)

7. place_order(cart_id, stored_payment_id="M6ZWC62H3QZKNCQ9", payment_type="paypal")
   → returns order id + number, confirmation_needed: false
```

## Environment variables

| Variable | Description |
|---|---|
| `FLINK_FIREBASE_REFRESH_TOKEN` | Firebase refresh token (persisted automatically after login) |
| `FLINK_HUB_ID` | Active hub ID (persisted by `set_active_hub`) |
| `FLINK_HUB_SLUG` | Active hub slug (persisted by `set_active_hub`) |
| `FLINK_BASE_URL` | API base URL (default: `https://api.goflink.com`) |
| `FLINK_DATADOME_COOKIE` | DataDome bot-protection cookie (optional, helps if requests are blocked) |

## API documentation

See `openapi.yaml` — a reverse-engineered OpenAPI 3.0 spec covering all discovered endpoints across auth, hub locator, product discovery, cart, payment methods and checkout. Includes confirmed request/response shapes, field names from APK `@Json` annotations, and notes on the working PayPal checkout flow.
