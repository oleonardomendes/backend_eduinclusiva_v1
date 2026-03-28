# app/database.py
import os
import logging
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.exc import OperationalError

# 🎯 Configuração da URL do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eduinclusiva.db")

# 🧱 Detecta tipo de banco e configura engine
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

# 🚀 Criação do engine SQLModel
engine = create_engine(
    DATABASE_URL,
    echo=False,  # pode mudar para True se quiser ver os logs SQL
    pool_pre_ping=True,  # detecta conexões inativas
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args
)

# 🧠 Logger configurado
logger = logging.getLogger("uvicorn")

def init_db():
    """
    Inicializa as tabelas do banco de dados com base nos modelos SQLModel.
    Executa automaticamente na inicialização do FastAPI (ver main.py).
    """
    try:
        logger.info(f"🔌 Conectando ao banco de dados: {DATABASE_URL}")
        SQLModel.metadata.create_all(engine)
        logger.info("✅ Banco de dados inicializado com sucesso.")
    except OperationalError as e:
        logger.error(f"❌ Falha na conexão com o banco: {e}")
        raise RuntimeError("Falha ao inicializar o banco de dados.") from e
    except Exception as e:
        logger.error(f"❌ Erro inesperado ao inicializar o banco: {e}")
        raise

def get_session():
    """
    Retorna uma sessão de banco de dados (usada via Depends no FastAPI).
    """
    with Session(engine) as session:
        yield session
