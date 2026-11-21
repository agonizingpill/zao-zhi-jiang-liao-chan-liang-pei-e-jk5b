from datetime import datetime, timedelta, timezone
import hashlib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from .config import JWT_SECRET
from .db import query

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)

def password_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def issue_token(user):
    payload = {"sub": str(user["id"]), "role": user["role"], "name": user["display_name"], "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        user = query("SELECT id, email, role, display_name FROM users WHERE id=%s", (int(payload["sub"]),), one=True)
    except (JWTError, ValueError, TypeError):
        user = None
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user

def require_roles(*roles):
    def dependency(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"角色 {user['role']} 无权执行此操作")
        return user
    return dependency
