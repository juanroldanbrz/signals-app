import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config import settings
from src.models.user import User
from src.services.auth import create_access_token, hash_password, verify_password
from src.services.email import send_verification_email
from src.templates_config import templates

router = APIRouter(prefix="/auth")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    user = await User.find_one(User.email == email)
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"},
            status_code=401,
        )

    if settings.mandatory_email_verification and not user.is_verified:
        return RedirectResponse("/auth/verify-pending", status_code=302)

    token = create_access_token(str(user.id))
    response = RedirectResponse("/app", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(request: Request, email: str = Form(...), password: str = Form(...)):
    existing = await User.find_one(User.email == email)
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email already registered"},
            status_code=400,
        )

    verify_token = secrets.token_urlsafe(32)
    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_verified=not settings.mandatory_email_verification,
        verify_token=verify_token if settings.mandatory_email_verification else None,
    )
    await user.insert()

    if settings.mandatory_email_verification:
        verify_url = f"{request.base_url}auth/verify/{verify_token}"
        await send_verification_email(email, verify_url)
        return RedirectResponse("/auth/verify-pending", status_code=302)

    return RedirectResponse("/auth/login", status_code=302)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/verify/{token}")
async def verify_email(token: str):
    user = await User.find_one(User.verify_token == token)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    user.is_verified = True
    user.verify_token = None
    await user.save()
    return RedirectResponse("/auth/login", status_code=302)


@router.get("/verify-pending", response_class=HTMLResponse)
async def verify_pending(request: Request):
    return templates.TemplateResponse("verify_pending.html", {"request": request})
