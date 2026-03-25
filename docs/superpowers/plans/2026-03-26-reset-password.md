# Reset Password Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a forgot/reset password flow — users click "Forgot password?" on login, receive a one-time-use email link, and set a new password.

**Architecture:** Add `reset_token` field to the User model, four new routes in `auth.py`, a new email helper in `email.py`, and two new templates. Token is generated with `secrets.token_urlsafe(32)`, stored on the User document, and cleared to `None` after use — no expiry.

**Tech Stack:** FastAPI, Beanie/MongoDB, Jinja2 + TailwindCSS, Resend (email), BCrypt (password hashing)

---

## File Map

| File | Change |
|------|--------|
| `src/models/user.py` | Add `reset_token: str \| None = None` |
| `src/routes/auth.py` | Add 4 routes: GET/POST forgot-password, GET/POST reset-password/{token} |
| `src/services/email.py` | Add `send_password_reset_email(to_email, reset_url)` |
| `src/templates/login.html` | Add "Forgot password?" link below the form |
| `src/templates/forgot_password.html` | New — email input form |
| `src/templates/reset_password.html` | New — new password + confirm form |

---

## Task 1: Add `reset_token` to User model

**Files:**
- Modify: `src/models/user.py`

- [ ] **Step 1: Add the field**

In `src/models/user.py`, add after `verify_token`:

```python
reset_token: str | None = None
```

Full file after change:

```python
from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class User(Document):
    email: str
    hashed_password: str
    is_verified: bool = False
    verify_token: str | None = None
    reset_token: str | None = None
    subscription_type: Literal["FREE", "UNLIMITED"] = "FREE"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
        indexes = [IndexModel([("email", 1)], unique=True)]
```

- [ ] **Step 2: Commit**

```bash
git add src/models/user.py
git commit -m "feat: add reset_token field to User model"
```

---

## Task 2: Add `send_password_reset_email` to email service

**Files:**
- Modify: `src/services/email.py`

- [ ] **Step 1: Add the function**

Append to `src/services/email.py`:

```python
async def send_password_reset_email(to_email: str, reset_url: str) -> None:
    resend.api_key = settings.resend_api_key
    resend.Emails.send({
        "from": "Signals <noreply@watchsignal.app>",
        "to": [to_email],
        "subject": "Reset your Signals password",
        "html": f"""
            <p>You requested a password reset for your Signals account.</p>
            <p>Click the link below to set a new password:</p>
            <p><a href="{reset_url}">{reset_url}</a></p>
            <p>If you didn't request this, you can ignore this email.</p>
        """,
    })
```

- [ ] **Step 2: Commit**

```bash
git add src/services/email.py
git commit -m "feat: add send_password_reset_email to email service"
```

---

## Task 3: Add forgot/reset password routes

**Files:**
- Modify: `src/routes/auth.py`

- [ ] **Step 1: Add imports**

Update the email import line and add logging in `src/routes/auth.py`:

```python
import logging

from src.services.email import send_verification_email, send_password_reset_email
```

- [ ] **Step 2: Add GET /auth/forgot-password**

Append to `src/routes/auth.py`:

```python
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})
```

- [ ] **Step 3: Add POST /auth/forgot-password**

```python
@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request, email: str = Form(...)):
    user = await User.find_one(User.email == email)
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        await user.save()
        reset_url = f"{request.base_url}auth/reset-password/{token}"
        try:
            await send_password_reset_email(email, reset_url)
        except Exception:
            logging.exception("Failed to send password reset email to %s", email)
            return templates.TemplateResponse(
                "forgot_password.html",
                {"request": request, "error": "Something went wrong. Please try again later."},
            )
    # Always show success to prevent email enumeration
    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "success": "If that email is registered, you'll receive a reset link shortly."},
    )
```

- [ ] **Step 4: Add GET /auth/reset-password/{token}**

```python
@router.get("/reset-password/{token}", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str):
    user = await User.find_one(User.reset_token == token)
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "token_valid": False, "error": "Invalid or already used link."},
        )
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "token_valid": True})
```

- [ ] **Step 5: Add POST /auth/reset-password/{token}**

```python
@router.post("/reset-password/{token}", response_class=HTMLResponse)
async def reset_password(
    request: Request,
    token: str,
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    user = await User.find_one(User.reset_token == token)
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "token_valid": False, "error": "Invalid or already used link."},
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "token_valid": True, "error": "Passwords do not match."},
        )

    user.hashed_password = hash_password(password)
    user.reset_token = None
    await user.save()
    return RedirectResponse("/auth/login?reset=1", status_code=302)
```

- [ ] **Step 6: Commit**

```bash
git add src/routes/auth.py
git commit -m "feat: add forgot/reset password routes"
```

---

## Task 4: Create `forgot_password.html` template

**Files:**
- Create: `src/templates/forgot_password.html`

- [ ] **Step 1: Create the template**

```html
{% extends "base.html" %}
{% block title %}Forgot Password — Signals{% endblock %}

{% block content %}
<div class="min-h-[80vh] flex items-center justify-center">
  <div class="w-full max-w-md">
    <div class="bg-dark-card border border-dark-border rounded-lg p-8 glow-green">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-bold text-neon-green tracking-wider">RESET PASSWORD</h1>
        <p class="text-gray-500 text-sm mt-1">Enter your email to receive a reset link</p>
      </div>

      {% if success %}
      <div class="mb-4 px-4 py-3 bg-green-900/30 border border-green-700 rounded text-green-400 text-sm">
        {{ success }}
      </div>
      {% endif %}

      {% if error %}
      <div class="mb-4 px-4 py-3 bg-red-900/30 border border-red-700 rounded text-red-400 text-sm">
        {{ error }}
      </div>
      {% endif %}

      <form method="post" action="/auth/forgot-password" class="space-y-5">
        <div>
          <label class="block text-xs text-gray-500 uppercase tracking-wider mb-1">Email</label>
          <input
            type="email"
            name="email"
            required
            autofocus
            class="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-neon-green focus:ring-1 focus:ring-neon-green/30 transition-colors"
            placeholder="you@example.com"
          />
        </div>
        <button
          type="submit"
          class="w-full bg-neon-green/10 border border-neon-green text-neon-green font-bold py-2 rounded hover:bg-neon-green/20 transition-colors tracking-wider text-sm"
        >
          SEND RESET LINK
        </button>
      </form>

      <p class="text-center text-gray-600 text-sm mt-6">
        <a href="/auth/login" class="text-neon-blue hover:text-neon-green transition-colors">Back to login</a>
      </p>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add src/templates/forgot_password.html
git commit -m "feat: add forgot_password template"
```

---

## Task 5: Create `reset_password.html` template

**Files:**
- Create: `src/templates/reset_password.html`

- [ ] **Step 1: Create the template**

```html
{% extends "base.html" %}
{% block title %}Reset Password — Signals{% endblock %}

{% block content %}
<div class="min-h-[80vh] flex items-center justify-center">
  <div class="w-full max-w-md">
    <div class="bg-dark-card border border-dark-border rounded-lg p-8 glow-green">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-bold text-neon-green tracking-wider">NEW PASSWORD</h1>
        <p class="text-gray-500 text-sm mt-1">Choose a new password for your account</p>
      </div>

      {% if error %}
      <div class="mb-4 px-4 py-3 bg-red-900/30 border border-red-700 rounded text-red-400 text-sm">
        {{ error }}
      </div>
      {% endif %}

      {% if token_valid %}
      <form method="post" action="/auth/reset-password/{{ token }}" class="space-y-5" id="reset-form">
        <div>
          <label class="block text-xs text-gray-500 uppercase tracking-wider mb-1">New Password</label>
          <input
            type="password"
            name="password"
            id="password"
            required
            autofocus
            class="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-neon-green focus:ring-1 focus:ring-neon-green/30 transition-colors"
            placeholder="••••••••"
          />
        </div>
        <div>
          <label class="block text-xs text-gray-500 uppercase tracking-wider mb-1">Confirm Password</label>
          <input
            type="password"
            name="confirm_password"
            id="confirm_password"
            required
            class="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-neon-green focus:ring-1 focus:ring-neon-green/30 transition-colors"
            placeholder="••••••••"
          />
          <p id="match-error" class="text-red-400 text-xs mt-1 hidden">Passwords do not match.</p>
        </div>
        <button
          type="submit"
          class="w-full bg-neon-green/10 border border-neon-green text-neon-green font-bold py-2 rounded hover:bg-neon-green/20 transition-colors tracking-wider text-sm"
        >
          SET NEW PASSWORD
        </button>
      </form>
      <script>
        document.getElementById('reset-form').addEventListener('submit', function(e) {
          const pw = document.getElementById('password').value;
          const cpw = document.getElementById('confirm_password').value;
          const msg = document.getElementById('match-error');
          if (pw !== cpw) {
            e.preventDefault();
            msg.classList.remove('hidden');
          }
        });
      </script>
      {% endif %}

      <p class="text-center text-gray-600 text-sm mt-6">
        <a href="/auth/login" class="text-neon-blue hover:text-neon-green transition-colors">Back to login</a>
      </p>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add src/templates/reset_password.html
git commit -m "feat: add reset_password template"
```

---

## Task 6: Update login.html with "Forgot password?" link

**Files:**
- Modify: `src/templates/login.html`

- [ ] **Step 1: Add the link**

In `src/templates/login.html`, find the paragraph at the bottom:

```html
      <p class="text-center text-gray-600 text-sm mt-6">
        No account?
        <a href="/auth/register" class="text-neon-blue hover:text-neon-green transition-colors">Register</a>
      </p>
```

Replace with:

```html
      {% if success %}
      <div class="mb-4 px-4 py-3 bg-green-900/30 border border-green-700 rounded text-green-400 text-sm">
        {{ success }}
      </div>
      {% endif %}

      <div class="flex justify-between items-center mt-6">
        <a href="/auth/forgot-password" class="text-gray-600 hover:text-neon-green text-sm transition-colors">Forgot password?</a>
        <p class="text-gray-600 text-sm">
          No account?
          <a href="/auth/register" class="text-neon-blue hover:text-neon-green transition-colors">Register</a>
        </p>
      </div>
```

Note: The `success` block handles the `?reset=1` redirect message. Update the GET `/auth/login` route to pass `success` when `request.query_params.get("reset")` is set:

In `src/routes/auth.py`, update the login GET route:

```python
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    success = "Password reset successfully. You can now sign in." if request.query_params.get("reset") else None
    return templates.TemplateResponse("login.html", {"request": request, "success": success})
```

- [ ] **Step 2: Commit**

```bash
git add src/templates/login.html src/routes/auth.py
git commit -m "feat: add forgot password link and reset success message to login page"
```

---

## Task 7: Final verification

- [ ] **Step 1: Start the dev server**

```bash
uv run uvicorn src.main:app --reload
```

- [ ] **Step 2: Manual smoke test**

1. Go to `/auth/login` — confirm "Forgot password?" link is visible
2. Click it — confirm `/auth/forgot-password` loads
3. Submit a non-existent email — confirm success message appears (no error leak)
4. Submit a real user email — confirm token is saved in MongoDB (`db.users.find({reset_token: {$ne: null}})`)
5. Visit `/auth/reset-password/<token>` — confirm form loads
6. Submit mismatched passwords — confirm error "Passwords do not match."
7. Submit valid matching passwords — confirm redirect to `/auth/login?reset=1` with success message
8. Try reusing the same token URL — confirm "Invalid or already used link." error

- [ ] **Step 3: Final commit (if any cleanup needed)**

```bash
git add -p
git commit -m "fix: <description of any cleanup>"
```

- [ ] **Step 4: Push to main**

```bash
git push origin main
```
