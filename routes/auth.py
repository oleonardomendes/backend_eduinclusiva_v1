# app/routes/auth.py
import os
import jwt
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select
from passlib.context import CryptContext

from app.database import get_session
from app.models import Usuario

router = APIRouter()

# ========================
# Segurança / Config
# ========================
SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET") or "supersecretkey123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24)))

# Modo demo (fallback) enquanto migra todos os usuários para hash
DEFAULT_TEST_PASSWORD = os.getenv("DEFAULT_TEST_PASSWORD", "123456")
ALLOW_PLAIN_DEMO_LOGIN = os.getenv("ALLOW_PLAIN_DEMO_LOGIN", "true").lower() == "true"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

# ========================
# Schemas
# ========================
class LoginRequest(BaseModel):
    email: EmailStr
    senha: str

class RegisterRequest(BaseModel):
    nome: str
    email: EmailStr
    senha: str
    papel: str = "professor"

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class UsuarioMeOut(BaseModel):
    id: int
    nome: str
    email: EmailStr
    papel: Optional[str] = None

# ========================
# Helpers
# ========================
ALLOWED_ROLES = {
    "admin", "gestor", "professor", "familia",
    "secretaria", "coordenadora", "responsavel", "especialista",
}

def normalize_role(papel: str) -> str:
    if not papel:
        return "professor"
    m = papel.strip().lower()
    aliases = {
        "professora": "professor",  # se padroniza no DB como 'professor'
    }
    return aliases.get(m, m)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def usuario_has_attr(attr: str) -> bool:
    return hasattr(Usuario, attr)

# ========================
# Dependências
# ========================
def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    session: Session = Depends(get_session),
) -> Usuario:
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub") or payload.get("email") or payload.get("user_id")
        if not sub:
            raise HTTPException(status_code=401, detail="Token inválido (sem subject)")

        user: Optional[Usuario] = None
        # tentar por id; se não numérico, tentar por e-mail
        if isinstance(sub, int) or (isinstance(sub, str) and sub.isdigit()):
            user = session.get(Usuario, int(sub))
        if user is None:
            user = session.exec(select(Usuario).where(Usuario.email == str(sub))).first()

        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

# ========================
# Endpoints
# ========================

# 🔹 Registro de novo usuário
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, session: Session = Depends(get_session)):
    # e-mail único
    existing_user = session.exec(select(Usuario).where(Usuario.email == payload.email)).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")

    role = normalize_role(payload.papel)
    # Se quiser restringir, valide; se preferir livre, comente o bloco abaixo.
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail=f"papel inválido: {payload.papel}")

    # Segurança: limite do bcrypt (≈72 bytes)
    raw = payload.senha.encode("utf-8")
    if len(raw) > 72:
        raise HTTPException(
            status_code=422,
            detail="Senha muito longa para bcrypt (limite ~72 bytes)."
        )

    # Prepara novo usuário; grava hash se a coluna existir (compatível com seu modelo)
    kwargs = dict(
        nome=payload.nome,
        email=payload.email,
        papel=role,
    )
    if usuario_has_attr("senha_hash"):
        kwargs["senha_hash"] = pwd_context.hash(payload.senha)

    novo_usuario = Usuario(**kwargs)
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)

    # Gera token pós-registro (login automático)
    token = create_access_token(
        {"sub": str(novo_usuario.id), "email": novo_usuario.email, "role": novo_usuario.papel}
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

# 🔹 Login
@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(Usuario).where(Usuario.email == payload.email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    # Se existir hash, verifique
    if usuario_has_attr("senha_hash") and getattr(user, "senha_hash", None):
        if not pwd_context.verify(payload.senha, user.senha_hash):
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    else:
        # Sem hash persistido → permite fallback APENAS se liberado e senha igual à de demo
        if not (ALLOW_PLAIN_DEMO_LOGIN and payload.senha == DEFAULT_TEST_PASSWORD):
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.papel})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

# 🔹 Quem sou eu
@router.get("/me", response_model=UsuarioMeOut, status_code=status.HTTP_200_OK)
def me(current_user: Usuario = Depends(get_current_user)):
    return UsuarioMeOut(
        id=current_user.id,
        nome=current_user.nome,
        email=current_user.email,
        papel=getattr(current_user, "papel", None),
    )