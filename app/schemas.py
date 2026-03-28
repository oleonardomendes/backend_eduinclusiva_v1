# app/schemas.py
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# =========================================================
# 👤 Usuário
# =========================================================
class UsuarioBase(BaseModel):
    nome: str
    email: EmailStr
    papel: Optional[str] = Field(default="professor", description="admin, gestor, professor, familia")


class UsuarioCreate(UsuarioBase):
    senha: str


class UsuarioRead(UsuarioBase):
    id: int
    criado_em: datetime

    class Config:
        orm_mode = True


# =========================================================
# 👦 Aluno
# =========================================================
class AlunoBase(BaseModel):
    nome: str
    idade: Optional[int] = None
    necessidade: Optional[str] = None
    observacoes: Optional[str] = None


class AlunoCreate(AlunoBase):
    pass


class AlunoUpdate(BaseModel):
    nome: Optional[str] = None
    idade: Optional[int] = None
    necessidade: Optional[str] = None
    observacoes: Optional[str] = None


class AlunoRead(AlunoBase):
    id: int
    criado_em: datetime

    class Config:
        orm_mode = True


# =========================================================
# 📘 Plano de Ensino Individualizado
# =========================================================
class PlanoAtividade(BaseModel):
    tipo: str
    descricao: str
    duracao: Optional[int] = Field(default=15, description="Duração estimada em minutos")


class PlanoBase(BaseModel):
    titulo: str
    atividades: Any  # pode ser lista de objetos ou JSON serializado
    recomendacoes: Optional[Any] = None


class PlanoCreate(PlanoBase):
    aluno_id: int


class PlanoUpdate(BaseModel):
    titulo: Optional[str] = None
    atividades: Optional[Any] = None
    recomendacoes: Optional[Any] = None


class PlanoRead(PlanoBase):
    id: int
    aluno_id: int
    criado_em: datetime

    class Config:
        orm_mode = True


# =========================================================
# 📦 Retornos Compostos (para dashboards e IA)
# =========================================================
class PlanoComAluno(BaseModel):
    """
    Modelo de retorno que junta informações do aluno com o plano.
    Ideal para dashboards e IA RAG.
    """
    aluno: AlunoRead
    plano: PlanoRead


class PlanoGeradoIA(BaseModel):
    """
    Modelo de resposta da IA para geração de plano adaptado.
    """
    titulo: str
    atividades: List[PlanoAtividade]
    recomendacoes: List[str]
