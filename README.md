# flink-mcp

A [FastMCP](https://github.com/jlowin/fastmcp) server that wraps the unofficial Flink grocery delivery API, enabling Claude (or any MCP client) to browse products, build a cart, and place real orders — fully headless.

> **Unofficial.** This uses the reverse-engineered Flink consumer API (`api.goflink.com`). Field names, endpoint paths and auth flows were derived by decompiling the Android APK (v2026.13.0) using jadx. It may break if Flink changes their API.

> **Disclaimer.** This project is for educational and personal use only. It automates access to Flink's private, undocumented API, which likely violates their Terms of Service. Use at your own risk. The author is not affiliated with Flink and takes no responsibility for account suspension, order issues, or any other consequences of use.

## Legal & ToS notice

This project reverse-engineers a private, undocumented API by decompiling the Flink Android APK. Before using it, be aware:

- **Likely against Flink's Terms of Service.** Automated API access, APK decompilation, and scripted ordering are almost certainly prohibited by Flink's ToS. Your account could be suspended if detected.
- **For personal and research use only.** Do not use this to scrape prices at scale, automate bulk orders, resell access, or do anything commercial. The intended use case is: you, your groceries, your account.
- **No warranty.** Orders placed via this tool are real orders charged to your real payment method. Always review your cart before calling `place_order()`. The author takes no responsibility for duplicate orders, wrong deliveries, or payment issues.
- **The embedded credentials belong to Flink.** The Firebase API key and Google OAuth client ID in the source code were extracted from Flink's own APK. They are not personal credentials, but they are Flink's property. Flink may rotate them at any time, which would break authentication.
- **Reverse engineering legality varies by jurisdiction.** In the EU, decompilation for interoperability purposes is generally permitted under the Software Directive (2009/24/EC). In other regions, check your local laws before proceeding.

TL;DR: this is a personal hobby project. Use it for your own groceries, don't be a jerk about it, and don't blame anyone but yourself if something goes wrong.

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

## Tokens you need

Three tokens are required before placing orders. All are one-time setup steps.

---

### 1. Firebase token (authentication)

This authenticates you as your Flink account. The easiest path is email + password — no interception needed.

**Recommended: email + password**

1. Go to `goflink.com`, log in with your phone number, then set a password via account settings or the password reset flow
2. Call `email_login(email="...", password="...")` — done. The refresh token is persisted to `.env` automatically.

**Alternative: intercept a Firebase ID token directly**

If you can't set a password, you can grab a Firebase ID token from an active session and inject it with `set_firebase_token(token)`. The token appears as the `Authorization: Bearer <token>` header in any request to `api.goflink.com`.

How to intercept it, by platform:

**Firefox (desktop)**
1. Open `goflink.com` and log in
2. Open DevTools → Network tab
3. Filter for `api.goflink.com` requests
4. Click any request → Headers → copy the `Authorization` value (everything after `Bearer `)

Alternatively, DevTools → Application → Local Storage → `flink-core-prod.firebaseapp.com` → find the key starting with `firebase:authUser:` → copy `idToken`.

**Android (HTTP Toolkit)**
1. Install [HTTP Toolkit](https://httptoolkit.com) on your Mac and the HTTP Toolkit app on your Android device
2. In HTTP Toolkit on Mac, choose "Android device via ADB" and follow the setup
3. Open the Flink app on Android — any screen that loads products or the home screen
4. In HTTP Toolkit on Mac, filter requests for `api.goflink.com`
5. Click any request → copy the `Authorization: Bearer <token>` header value

HTTP Toolkit intercepts HTTPS traffic by installing a temporary system CA certificate on the device. It is removed when you stop the session.

**iOS (HTTP Toolkit or Stream)**
1. Install [HTTP Toolkit](https://httptoolkit.com) and follow the iOS setup (requires installing a profile via Safari)
2. Or use [Stream](https://apps.apple.com/app/stream-network-debug-tool/id1245190994) — a free iOS proxy app, no Mac needed
   - In Stream: tap Start Capture → open the Flink app → stop capture → find a request to `api.goflink.com` → Headers → `Authorization`
3. Copy the Bearer token and call `set_firebase_token(token)`

> Firebase ID tokens expire after ~1 hour. Once you have the token, call `login(phone_number)` + `verify_otp_code(phone_number, code)` to get a permanent refresh token that survives server restarts — then `set_firebase_token` is only needed once.

---

### 2. DataDome cookie (anti-bot, optional)

Flink uses [DataDome](https://datadome.co) for bot detection. Most requests work without it, but if you get 403 responses or see a CAPTCHA, you need to pass a valid DataDome cookie.

**How to get it:**

**Firefox (desktop)**
1. Open `goflink.com` in Firefox and complete any interaction (scroll, search)
2. DevTools → Storage → Cookies → `goflink.com`
3. Find the cookie named `datadome` → copy its value
4. Set `FLINK_DATADOME_COOKIE=<value>` in your `.env`

**Android (HTTP Toolkit)**
1. Intercept traffic as described above
2. Find a request to `api.goflink.com` → Headers → copy the `Cookie` header
3. Extract the `datadome=<value>` portion

**iOS (Stream or HTTP Toolkit)**
Same as Firebase token interception above — look for the `Cookie` header in any Flink API request and extract the `datadome=` value.

DataDome cookies are tied to a browser/device fingerprint and expire. If requests start failing again, refresh the cookie.

---

### 3. Adyen stored payment token (PayPal / card)

This is not a credential you extract — it's created when you complete one order via PayPal (or another stored method) in the official Flink app. Adyen saves your PayPal billing agreement on their side and returns a reusable token.

**One-time setup:**
1. Open the Flink app on your phone, add items, and complete checkout using PayPal
2. After the order is placed, call `get_payment_methods()` from the MCP server
3. In the response, look at `paymentMethods.tokens[]` — find the entry with `"type": "paypal"`
4. The `token` field (e.g. `"M6ZWC62H3QZKNCQ9"`) is reusable for all future orders via `place_order()`

If you want to confirm the token before your first API order, intercept the `GET /consumer-backend/payment-bff/v1/payment-methods/orders` response using the same tools described above.

---

## Delivery coordinates — important

> **Wrong coordinates will get your order cancelled.**

The Flink rider navigates to the GPS coordinates you provide in `create_cart()`, not the street address. The address is also required and must be correct, but it is only used for display — the rider's app routes to the coordinates.

**How to get precise coordinates:**
1. Open [Google Maps](https://maps.google.com) in a browser
2. Find your exact front door or building entrance
3. Right-click on the spot → click the coordinates shown at the top of the context menu (e.g. `52.5011, 13.4547`)
4. This copies them to your clipboard — paste them as `delivery_lat` and `delivery_lon` in `create_cart()`

Avoid using approximate coordinates from geocoding an address — they may point to the wrong side of a building or to the street rather than the entrance.

---

## Authentication

The recommended flow is email + password — see [Token 1](#1-firebase-token-authentication) above.

For phone-only accounts without a password, use `login(phone_number)` + `verify_otp_code(phone_number, code)`.

## Payment setup (one-time)

See [Token 3](#3-adyen-stored-payment-token-paypal--card) above. Complete one order in the Flink app via PayPal, then use `get_payment_methods()` to retrieve the reusable Adyen token.

## Running

```bash
# Development (with MCP Inspector)
fastmcp dev server.py

# Production / Claude Desktop
fastmcp install server.py --name flink
```

## Debugging with MCP Inspector

`fastmcp dev server.py` starts the server and opens the **MCP Inspector** in your browser — a web UI that lets you call individual tools directly and inspect request/response payloads without going through Claude.

This is the recommended way to debug and explore the API:

1. Call `find_hub(lat=..., lon=...)` → inspect the JSON response → pick a hub
2. Call `set_active_hub(hub_id, hub_slug)` → call `search_products(query="Milch")` → find SKUs
3. Call `create_cart(...)` with your items and address → review the cart response
4. Call `get_payment_methods()` → find your PayPal token
5. Call `place_order(cart_id, stored_payment_id=..., payment_type="paypal")` → follow the PayPal redirect

Each tool call shows the full response immediately. API errors (wrong field names, missing parameters, auth failures) appear in the response body and are easy to iterate on. Most of the payment flow debugging for this project was done through the Inspector rather than through a Claude conversation.

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
       delivery_lat=52.5011,   # precise — right-click in Google Maps
       delivery_lon=13.4547,   # rider navigates here, NOT the address
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
