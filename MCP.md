# MCP Tools Reference

All tools are exposed via the FastMCP server in `server.py`. The server maintains shared state for the Firebase token, refresh token, and active hub across calls.

---

## Authentication

### `google_signin()`
Authenticate via Google OAuth2 → Firebase. Opens a browser window to `http://localhost:8080` for Google sign-in, catches the callback, and exchanges for a Firebase ID + refresh token. Persists the refresh token to `.env`.

Use this if your Flink account was created via Google.

---

### `email_login(email, password)`
Authenticate with email + password. Calls Flink's login endpoint, exchanges the returned custom token for a Firebase ID + refresh token, and persists to `.env`.

**Recommended.** Requires setting a password once via `goflink.com` (account settings or password reset). After this, the server auto-refreshes on restart — no re-login needed.

---

### `set_firebase_token(id_token)`
Manually inject a Firebase ID token. Useful as a one-time bootstrap when intercepting a token from the Flink app (e.g. via HTTP Toolkit).

---

### `login(phone_number, country_code="+49")`
Send an OTP SMS to the given phone number. Bootstraps Firebase auth internally if no token is present — no prior authentication needed. Follow up with `verify_otp_code()`.

---

### `verify_otp_code(phone_number, code, country_code="+49")`
Complete OTP login with the code from the SMS. Persists the Firebase refresh token to `.env`. If the phone is already linked to another account (409), automatically retries with `override: true`.

---

## Profile

### `get_profile()`
Returns the current user's Flink profile. Useful for verifying authentication and checking account state.

---

## Hubs

### `find_hub(lat, lon)`
Find the nearest Flink hubs for the given coordinates. Returns hub IDs, slugs and addresses. No authentication required.

---

### `get_hub(hub_id)`
Get full details for a specific hub by ID.

---

### `set_active_hub(hub_id, hub_slug)`
Set the active hub for all subsequent product and cart calls. Persists `FLINK_HUB_ID` and `FLINK_HUB_SLUG` to `.env` so the hub survives server restarts.

---

## Products

### `list_products()`
Return the home screen / product catalog for the active hub. Requires an active hub.

---

### `search_products(query)`
Search for products by name at the active hub. Returns matching products with SKUs and prices.

---

### `get_product_stock(skus)`
Check stock/availability for a list of product SKUs. Pass a list of SKU strings.

---

## Cart

### `create_cart(items, delivery_lat, delivery_lon, street_address_1, house_number, city, postal_code, first_name, last_name, phone, ...)`
Build a cart with the given items and address. Returns the cart including its ID for subsequent operations.

**Does NOT place the order** — call `place_order()` after reviewing.

> **Important:** `delivery_lat` / `delivery_lon` are the primary delivery destination. The rider navigates to these GPS coordinates, not the street address. Use precise coordinates (right-click in Google Maps → "What's here?"). Wrong coordinates will cause order cancellation. The address fields are also required and must match the coordinates.

`items` format: `[{"sku": "product-sku", "quantity": 2}, ...]`

Optional fields: `country` (default `"DE"`), `floor_number`, `name_on_doorbell`, `building_type`, `building_location`.

---

### `add_to_cart(cart_id, sku, quantity)`
Add or update an item in an existing cart. Fetches the current cart, merges the item into the lines, then PUTs back. Set `quantity=0` to remove an item.

Useful for modifying the app's active cart when you know the cart ID.

---

### `get_cart(cart_id)`
Retrieve current cart details and status by cart ID. Returns lines, addresses, pricing (`totalPrice.centAmount`) and status.

---

### `add_promo_code(cart_id, voucher_code)`
Apply a promo or discount code to an existing cart.

---

## Payment

### `get_payment_methods()`
Fetch saved payment methods for orders. Returns:
- `clientConfig` — Adyen SDK configuration including the `sdkConfig` JSON (available payment types and stored methods with Adyen IDs)
- `paymentMethods.tokens[]` — Flink-side stored methods; each entry's `token` field is the Adyen stored payment method ID to use in `place_order()`

After adding PayPal in the Flink app, the PayPal billing agreement appears here with `type: "paypal"` and a reusable `token`.

---

## Checkout

### `place_order(cart_id, stored_payment_id, payment_type="paypal", amount=None)`
Submit the cart as a real order using a stored payment method.

**Flow:**
1. Call `get_payment_methods()` — find the saved method in `paymentMethods.tokens[]`
2. Pass its `token` field as `stored_payment_id` and its `type` as `payment_type`
3. `amount` is fetched automatically from the cart (`totalPrice.centAmount / 100`)

If the response has `confirmation_needed: true`, open the URL from `confirmation_data` in a browser and approve the PayPal redirect (~5 seconds). Then call `place_order()` again with the same arguments — it returns the order ID on the second call.

**Example:**
```
place_order(
    cart_id="e9564cf6-...",
    stored_payment_id="M6ZWC62H3QZKNCQ9",
    payment_type="paypal"
)
```

---

### `confirm_order(cart_id, redirect_url)`
Finalize an order after a PayPal redirect, if the two-call approach doesn't work. Pass the full `flink://checkout?...` or `http://localhost:9999?...` redirect URL after PayPal authorization. Sends the Adyen redirect result to the checkout details endpoint.

In practice, calling `place_order()` a second time after PayPal approval is simpler and sufficient.

---

## State persistence

The server persists the following to `.env` automatically:

| Written by | Key |
|---|---|
| `email_login`, `verify_otp_code`, `google_signin` | `FLINK_FIREBASE_REFRESH_TOKEN` |
| `set_active_hub` | `FLINK_HUB_ID`, `FLINK_HUB_SLUG` |

On startup, `FlinkClient` loads these values so auth and hub context survive restarts.
