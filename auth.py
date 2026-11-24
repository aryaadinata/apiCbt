import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx

SECRET_KEY = "nextsiak-secret-key-oauth2-jwt-token-auth"
ALGORITHM = "HS256"
SIAK_API_URL = "http://127.0.0.1:5000"

security = HTTPBearer(auto_error=False)

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=12))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token autentikasi tidak ditemukan.")
    
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Sesi telah kedaluwarsa atau token tidak valid.")
    
    return payload

async def verify_credentials_with_siak(identifier: str, password: str):
    """
    Memverifikasi password langsung ke server SIAK (Port 5000 / URL dari pengaturan sistem)
    sehingga CBT tidak perlu menyimpan password siswa atau guru sama sekali.
    """
    from database import get_system_settings
    settings = get_system_settings(include_secrets=False)
    siak_url = (settings.get("siak_api_url") or SIAK_API_URL).rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.post(
                f"{siak_url}/api/auth/login",
                json={
                    "identifier": identifier,
                    "password": password,
                    "user_type": "all"
                }
            )
            if res.status_code == 200:
                return res.json()
            return None
    except Exception as e:
        print(f"Gagal menghubungi server SIAK ({siak_url}): {e}")
        return None
