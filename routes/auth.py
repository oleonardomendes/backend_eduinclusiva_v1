# app/routes/auth.py
import os
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from passlib.context import CryptContext
from app.database import get_session
from app.models import Usuario

router = APIRouter()

# Segurança
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 dia
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Schemas
class LoginRequest(BaseModel):
    email: str
    senha: str

class RegisterRequest(BaseModel):
    nome: str
    email: str
    senha: str
    papel: str = "professor"

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

# Helper
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# 🔹 Registro de novo usuário
@router.post("/register", response_model=TokenResponse)
def register_user(payload: RegisterRequest, session: Session = Depends(get_session)):
    # Verifica se já existe usuário com o mesmo e-mail
    existing_user = session.exec(select(Usuario).where(Usuario.email == payload.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    # Cria hash da senha
    hashed_pw = pwd_context.hash(payload.senha)

    novo_usuario = Usuario(
        nome=payload.nome,
        email=payload.email,
        papel=payload.papel,
    )
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)

    # Gera token
    token = create_access_token({"sub": str(novo_usuario.id), "email": novo_usuario.email, "role": novo_usuario.papel})
    return TokenResponse(access_token=token, token_type="bearer", expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60)

# 🔹 Login de usuário existente
@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(Usuario).where(Usuario.email == payload.email)).first()

    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    # OBS: Como a senha ainda não está salva com hash no DB, 
    # neste MVP a autenticação é simplificada.
    # (Em produção, use pwd_context.verify(payload.senha, user.senha_hash))
    if payload.senha != "123456":  # senha padrão apenas para teste
        raise HTTPException(status_code=401, detail="Senha incorreta")

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.papel})
    return TokenResponse(access_token=token, token_type="bearer", expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
