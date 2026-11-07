from types import SimpleNamespace
import time
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me-0123456789abcdef")
if os.getenv("APP_ENV") == "production" and (len(JWT_SECRET) < 32 or JWT_SECRET.startswith("dev-only")):
    raise RuntimeError("Set JWT_SECRET to a random string of 32+ characters in production")
JWT_HOURS = int(os.getenv("JWT_HOURS", "10"))
_bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 310_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(s), 310_000)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


def make_token(user: User) -> str:
    payload = {"sub": user.username, "role": user.role,
               "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# the signed-in user is looked up at most once every USER_TTL seconds; the page checks progress often,
# and each check would otherwise be a database round trip. Role or active changes made on the Users
# page clear the entry straight away (see forget_user).
USER_TTL = 30
_USER_CACHE: dict[str, tuple[float, SimpleNamespace]] = {}


def forget_user(username: str) -> None:
    _USER_CACHE.pop(username, None)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)):
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        data = jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
    now = time.monotonic()
    hit = _USER_CACHE.get(data["sub"])
    if hit and hit[0] > now:
        return hit[1]
    user = db.query(User).filter(User.username == data["sub"], User.active.is_(True)).first()
    if not user:
        _USER_CACHE.pop(data["sub"], None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    view = SimpleNamespace(id=user.id, username=user.username, full_name=user.full_name,
                           role=user.role, active=user.active)
    _USER_CACHE[data["sub"]] = (now + USER_TTL, view)
    return view


def require(*roles):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission for this")
        return user
    return dep


can_write = require("ADMIN", "OPS")
admin_only = require("ADMIN")
# reports and bulk exports: admins, operators and reporters (viewers see single loans only)
reports_access = require("ADMIN", "OPS", "REPORTER")
