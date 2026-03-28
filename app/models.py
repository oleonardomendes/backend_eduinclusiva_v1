# app/models.py
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
import json


# =========================================================
# 👤 Usuário
# =========================================================
class Usuario(SQLModel, table=True):
    """
    Representa qualquer usuário do sistema (professor, gestor, família, etc.)
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    email: str = Field(unique=True, index=True)
    senha_hash: Optional[str] = None
    papel: str = Field(default="professor", description="admin, gestor, professor, familia")
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 👦 Aluno
# =========================================================
class AlunoBase(SQLModel):
    nome: str
    idade: Optional[int] = None
    necessidade: Optional[str] = None
    observacoes: Optional[str] = None


class Aluno(AlunoBase, table=True):
    """
    Representa um aluno no sistema.
    Pode ter um ou mais planos de ensino individualizados (PEI).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    planos: List["Plano"] = Relationship(back_populates="aluno", sa_relationship_kwargs={"cascade": "all, delete"})


# =========================================================
# 📘 Plano de Ensino Individualizado
# =========================================================
class PlanoBase(SQLModel):
    titulo: str
    atividades: str  # JSON string para simplicidade (serializado/desserializado pela API)
    recomendacoes: Optional[str] = None


class Plano(PlanoBase, table=True):
    """
    Plano de ensino individualizado (gerado manualmente ou via IA).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    aluno_id: int = Field(foreign_key="aluno.id", index=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    aluno: Optional[Aluno] = Relationship(back_populates="planos")


# =========================================================
# 🧠 Utilidades
# =========================================================
def parse_json_field(data: str):
    """
    Helper para converter campos JSON armazenados como string.
    """
    try:
        return json.loads(data)
    except Exception:
        return data or {}
