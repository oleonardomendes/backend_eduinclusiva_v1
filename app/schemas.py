# app/schemas.py
from typing import Optional, List, Any
from datetime import datetime, date
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
    escola: Optional[str] = None
    sala: Optional[str] = None
    foto: Optional[str] = None
    matricula: Optional[str] = None
    data_nascimento: Optional[date] = None
    genero: Optional[str] = None
    telefone_contato: Optional[str] = None
    contato_emergencia_nome: Optional[str] = None
    contato_emergencia_telefone: Optional[str] = None
    contato_emergencia_parentesco: Optional[str] = None
    informacoes_medicas: Optional[str] = None
    nivel_aprendizado: Optional[str] = None
    objetivos_aprendizado: Optional[str] = None
    alergias: Optional[str] = None
    medicamentos: Optional[str] = None
    endereco: Optional[str] = None
    horario_aulas: Optional[str] = None
    progresso_geral: Optional[int] = None


class AlunoCreate(AlunoBase):
    pass


class AlunoUpdate(BaseModel):
    nome: Optional[str] = None
    idade: Optional[int] = None
    necessidade: Optional[str] = None
    observacoes: Optional[str] = None
    escola: Optional[str] = None
    sala: Optional[str] = None
    foto: Optional[str] = None
    matricula: Optional[str] = None
    data_nascimento: Optional[date] = None
    genero: Optional[str] = None
    telefone_contato: Optional[str] = None
    contato_emergencia_nome: Optional[str] = None
    contato_emergencia_telefone: Optional[str] = None
    contato_emergencia_parentesco: Optional[str] = None
    informacoes_medicas: Optional[str] = None
    nivel_aprendizado: Optional[str] = None
    objetivos_aprendizado: Optional[str] = None
    alergias: Optional[str] = None
    medicamentos: Optional[str] = None
    endereco: Optional[str] = None
    horario_aulas: Optional[str] = None
    progresso_geral: Optional[int] = None


class AlunoRead(AlunoBase):
    id: int
    professor_id: Optional[int] = None
    criado_em: datetime

    class Config:
        orm_mode = True


class AlunoComProfessor(AlunoRead):
    professor_nome: Optional[str] = None


class AlunoMetricas(BaseModel):
    progresso_geral: Optional[int]
    nivel_aprendizado: Optional[str]
    ultima_avaliacao: Optional[date]
    total_planos: int


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
