# app/models.py
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
import json


# =========================================================
# 👤 Usuário
# =========================================================
class Usuario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    email: str = Field(unique=True, index=True)
    senha_hash: Optional[str] = None
    papel: str = Field(default="professor", description="admin, gestor, professor, familia")
    criado_em: datetime = Field(default_factory=datetime.utcnow)

    # Relacionamento: professor tem vários alunos
    alunos: List["Aluno"] = Relationship(back_populates="professor")


# =========================================================
# 👦 Aluno
# =========================================================
class AlunoBase(SQLModel):
    nome: str
    idade: Optional[int] = None
    necessidade: Optional[str] = None
    observacoes: Optional[str] = None
    escola: Optional[str] = None   # nome da escola
    sala: Optional[str] = None     # ex: "Sala A - 1º ano"


class Aluno(AlunoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)

    # Vínculo com o professor responsável
    professor_id: Optional[int] = Field(default=None, foreign_key="usuario.id", index=True)
    professor: Optional[Usuario] = Relationship(back_populates="alunos")

    # Planos do aluno
    planos: List["Plano"] = Relationship(
        back_populates="aluno",
        sa_relationship_kwargs={"cascade": "all, delete"}
    )


# =========================================================
# 📘 Plano de Ensino Individualizado
# =========================================================
class PlanoBase(SQLModel):
    titulo: str
    atividades: str       # JSON string
    recomendacoes: Optional[str] = None


class Plano(PlanoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    aluno_id: int = Field(foreign_key="aluno.id", index=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    aluno: Optional[Aluno] = Relationship(back_populates="planos")


# =========================================================
# 🧠 Utilidades
# =========================================================
def parse_json_field(data: str):
    try:
        return json.loads(data)
    except Exception:
        return data or {}