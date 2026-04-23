# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from routes import alunos, planos, ai, auth, ingest, metas, avaliacoes, familia, publico, especialista
import logging
import os

# 🧠 Logs básicos
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

API_TITLE = "EduInclusiva API"
API_VERSION = "1.0.0"
API_DESC = (
    "API backend da plataforma **EduInclusiva** — "
    "voltada à geração de planos pedagógicos personalizados com IA, "
    "para alunos com necessidades educacionais especiais."
)

# 🚀 App FastAPI
app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESC,
    contact={
        "name": "Equipe EduInclusiva",
        "url": "https://eduinclusiva.vercel.app",
        "email": "contato@eduinclusiva.com",
    },
)

# 🌐 CORS (configurável por env)
# Preferência 1 (recomendada): ALLOWED_ORIGINS (lista separada por vírgula)
# Ex.: ALLOWED_ORIGINS="https://seu-projeto.vercel.app,https://www.seudominio.com"
#
# Preferência 2: ALLOW_ORIGIN_REGEX para padrões (ex.: vercel)
# Ex.: ALLOW_ORIGIN_REGEX="https://.*\\.vercel\\.app$"
#
# Preferência 3 (somente debug): ALLOW_ALL_ORIGINS="true"
default_origins = [
    "http://localhost:5173",  # Vite (dev)
    "http://localhost:3000",  # fallback local
]

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
allow_origin_regex_env = os.getenv("ALLOW_ORIGIN_REGEX", "").strip()
allow_all = os.getenv("ALLOW_ALL_ORIGINS", "false").lower() == "true"

cors_kwargs = dict(
    allow_credentials=False,  # coloque True apenas se usar cookies httpOnly
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if allow_all:
    logging.warning("CORS: ALLOW_ALL_ORIGINS=true (use apenas em depuração)")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], **cors_kwargs)
elif allow_origin_regex_env:
    logging.info(f"CORS: usando allow_origin_regex={allow_origin_regex_env}")
    app.add_middleware(CORSMiddleware, allow_origin_regex=allow_origin_regex_env, **cors_kwargs)
else:
    allowed_origins = (
        [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
        if allowed_origins_env
        else default_origins
    )
    logging.info(f"CORS: allow_origins={allowed_origins}")
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, **cors_kwargs)

# 🔄 Inicialização do DB
@app.on_event("startup")
def on_startup():
    try:
        init_db()
        logging.info("✅ Banco de dados inicializado com sucesso.")
    except Exception as e:
        logging.error(f"❌ Erro ao inicializar o banco de dados: {e}")

# 📦 Rotas (padronizadas em /v1)
# ⚠️ Ajuste importante: auth agora em /v1/auth
app.include_router(auth.router,   prefix="/v1/auth", tags=["Autenticação"])
app.include_router(alunos.router, prefix="/v1/alunos", tags=["Alunos"])
app.include_router(planos.router, prefix="/v1/planos", tags=["Planos Adaptados"])
app.include_router(ai.router,     prefix="/v1/ai", tags=["Inteligência Artificial"])
# Para o ingest, mantemos prefix="/v1" para resultar, por ex., em /v1/pdf/ingest (conforme sua rota)
app.include_router(ingest.router,     prefix="/v1",             tags=["Documentos e Ingestão"])
app.include_router(metas.router,      prefix="/v1/metas",       tags=["Metas"])
app.include_router(avaliacoes.router, prefix="/v1/avaliacoes",  tags=["Avaliações"])
app.include_router(familia.router,      prefix="/v1/familia",      tags=["Portal Família"])
app.include_router(publico.router,      prefix="/v1/publico",      tags=["Público"])
app.include_router(especialista.router, prefix="/v1/especialista", tags=["Módulo Clínico"])

# 🏥 Healthcheck (útil para Render)
@app.get("/healthz", tags=["Status"])
def healthz():
    return {"status": "ok"}

# 🏠 Rota base — status da API
@app.get("/", tags=["Status"])
def root():
    return {
        "status": "online ✅",
        "name": API_TITLE,
        "version": API_VERSION,
        "description": "Backend de IA para planos pedagógicos personalizados",
        "docs": "/docs",
        "redoc": "/redoc",
    }