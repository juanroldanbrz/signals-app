from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import settings
from src.models.user import User

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(request: Request) -> User:
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse("/auth/login", status_code=302)

    user_id = decode_access_token(token)
    if not user_id:
        return RedirectResponse("/auth/login", status_code=302)

    user = await User.get(user_id)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    if settings.email_verification and not user.is_verified:
        return RedirectResponse("/auth/verify-pending", status_code=302)

    return user
