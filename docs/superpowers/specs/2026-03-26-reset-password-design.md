# Reset Password Feature — Design Spec

**Date:** 2026-03-26
**Status:** Approved

---

## Overview

Add a forgot/reset password flow to the login page. Users can request a password reset via email, receive a one-time-use link, and set a new password.

---

## Data Model

Add one field to `src/models/user.py`:

```python
reset_token: str | None = None
```

- Populated on reset request with `secrets.token_urlsafe(32)`
- Cleared to `None` immediately after the password is updated
- No expiry — token is invalidated by use only

---

## Routes

All added to `src/routes/auth.py`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/forgot-password` | Render email input form |
| POST | `/auth/forgot-password` | Generate token, save to user, send email |
| GET | `/auth/reset-password/{token}` | Render new password form |
| POST | `/auth/reset-password/{token}` | Validate token, update password, clear token |

### POST `/auth/forgot-password`
1. Look up user by email
2. If not found: return same success response (avoids email enumeration)
3. Generate `secrets.token_urlsafe(32)`, save to `user.reset_token`
4. Send reset email via Resend

### POST `/auth/reset-password/{token}`
1. Find user where `reset_token == token`
2. If not found: render form with error "Invalid or already used link"
3. Hash new password, save to `user.hashed_password`
4. Set `user.reset_token = None`
5. Redirect to `/auth/login` with success flash message

---

## Templates

- **`src/templates/forgot_password.html`** — email input, submit button, link back to login. Shows neutral success message after submission.
- **`src/templates/reset_password.html`** — new password + confirm password fields, client-side match validation, error display for invalid token.
- **`src/templates/login.html`** — add "Forgot password?" link below the form.

All templates follow existing dark/neon theme (TailwindCSS).

---

## Email Service

New function in `src/services/email.py`:

```python
send_password_reset_email(to_email: str, reset_url: str) -> None
```

- Sender: `Signals <noreply@watchsignal.app>`
- Subject: `Reset your Signals password`
- Body: HTML with reset link button, mirrors `send_verification_email` structure

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Email not found | Same success message as found (enumeration protection) |
| Invalid/used token | Render reset form with error, no redirect |
| Passwords don't match | Client-side check + server-side fallback error |
| Resend API failure | Log error, show generic "something went wrong" message |

---

## Files Changed

| File | Change |
|------|--------|
| `src/models/user.py` | Add `reset_token: str \| None = None` |
| `src/routes/auth.py` | Add 4 new routes |
| `src/services/email.py` | Add `send_password_reset_email` |
| `src/templates/login.html` | Add "Forgot password?" link |
| `src/templates/forgot_password.html` | New template |
| `src/templates/reset_password.html` | New template |
