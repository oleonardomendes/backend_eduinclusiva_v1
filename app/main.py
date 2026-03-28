# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from routes import alunos, planos, ai, auth, ingest
import logging
import os

# 🧠 Configuração de logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 🚀 Inicialização da aplicação FastAPI
app = FastAPI(
    title="EduInclusiva API",
    version="1.0.0",
    description=(
        "API backend da plataforma **EduInclusiva** — "
        "voltada à geração de planos pedagógicos personalizados com IA, "
        "para alunos com necessidades educacionais especiais."
    ),
    contact={
        "name": "Equipe EduInclusiva",
        "url": "https://eduinclusiva.vercel.app",
        "email": "contato@eduinclusiva.com",
    },
)

# 🌐 Configuração CORS — (React local + Vercel)
allowed_origins = [
    "http://localhost:5173",  # ambiente local
    "http://localhost:3000",  # fallback local
    "https://eduinclusiva.vercel.app",  # produção
]

# Permitir tudo se variável de ambiente permitir (modo dev)
if os.getenv("ALLOW_ALL_ORIGINS", "false").lower() == "true":
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔄 Evento de inicialização
@app.on_event("startup")
def on_startup():
    try:
        init_db()
        logging.info("✅ Banco de dados inicializado com sucesso.")
    except Exception as e:
        logging.error(f"❌ Erro ao inicializar o banco de dados: {e}")

# 📦 Registro das rotas principais
app.include_router(auth.router, prefix="/auth", tags=["Autenticação"])
app.include_router(alunos.router, prefix="/v1/alunos", tags=["Alunos"])
app.include_router(planos.router, prefix="/v1/planos", tags=["Planos Adaptados"])
app.include_router(ai.router, prefix="/v1/ai", tags=["Inteligência Artificial"])
app.include_router(ingest.router, prefix="/v1/ingest", tags=["Documentos e Ingestão"])

# 🏠 Rota base — status da API
@app.get("/", tags=["Status"])
def root():
    """
    Retorna o status atual da API e informações básicas do sistema.
    """
    return {
        "status": "online ✅",
        "name": "EduInclusiva API",
        "version": "1.0.0",
        "description": "Backend de IA para planos pedagógicos personalizados",
        "docs": "/docs",
        "redoc": "/redoc",
    }
