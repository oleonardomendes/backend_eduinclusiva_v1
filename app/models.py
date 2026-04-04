# app/models.py
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime, date
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

    # Perfil completo
    foto: Optional[str] = None                          # URL da foto
    matricula: Optional[str] = None                     # número de matrícula
    data_nascimento: Optional[date] = None
    genero: Optional[str] = None                        # "Masculino", "Feminino", "Outro"
    telefone_contato: Optional[str] = None
    contato_emergencia_nome: Optional[str] = None
    contato_emergencia_telefone: Optional[str] = None
    contato_emergencia_parentesco: Optional[str] = None  # "Mãe", "Pai", "Avó", etc
    informacoes_medicas: Optional[str] = None            # JSON string: diagnóstico, alergias, medicamentos

    # Perfil pedagógico e saúde
    nivel_aprendizado: Optional[str] = None              # "Básico", "Intermediário", "Avançado"
    objetivos_aprendizado: Optional[str] = None
    alergias: Optional[str] = None
    medicamentos: Optional[str] = None
    endereco: Optional[str] = None
    horario_aulas: Optional[str] = None                  # ex: "Manhã (7h-12h)"
    progresso_geral: Optional[int] = None                # 0 a 100


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
# 🎯 Meta Bimestral
# =========================================================
class Meta(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    professor_id: int = Field(foreign_key="usuario.id", index=True)
    sala: Optional[str] = None          # nome da sala/turma
    bimestre: int                        # 1, 2, 3 ou 4
    ano: int                             # ex: 2026
    meta_progresso: int                  # 0 a 100 (% esperado ao final do bimestre)
    descricao: Optional[str] = None      # observações sobre a meta
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 📝 Avaliação de Aluno
# =========================================================
class Avaliacao(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    aluno_id: int = Field(foreign_key="aluno.id", index=True)
    professor_id: int = Field(foreign_key="usuario.id", index=True)
    bimestre: int                        # 1, 2, 3 ou 4
    ano: int                             # ex: 2026
    nota: float                          # 0.0 a 10.0
    progresso: Optional[int] = None      # 0 a 100 (% de desenvolvimento)
    observacoes: Optional[str] = None
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🤖 Atividade Gerada por IA (Gemini)
# =========================================================
class AtividadeGerada(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    aluno_id: int = Field(foreign_key="aluno.id", index=True)
    professor_id: int = Field(foreign_key="usuario.id", index=True)
    titulo: str
    objetivo: Optional[str] = None
    duracao_minutos: Optional[int] = None
    dificuldade: Optional[str] = None
    materiais: Optional[str] = None          # JSON string (lista)
    passo_a_passo: Optional[str] = None      # JSON string (lista)
    adaptacoes: Optional[str] = None         # JSON string (lista)
    criterios_avaliacao: Optional[str] = None  # JSON string (lista)
    justificativa: Optional[str] = None
    bimestre: Optional[int] = None
    ano: Optional[int] = None
    disciplina: Optional[str] = None
    tipo_atividade: Optional[str] = None
    instrucao_professor: Optional[str] = None
    instrucao_familia: Optional[str] = None
    conteudo_atividade: Optional[str] = None
    tags: Optional[str] = None                  # JSON string (lista)
    parametros_professor: Optional[str] = None  # JSON string com parâmetros extras
    reutilizavel: bool = Field(default=True)
    necessidade_atendida: Optional[str] = None
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 📚 Template de Atividade
# =========================================================
class AtividadeTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: str
    descricao: Optional[str] = None
    disciplina: Optional[str] = None
    tipo_atividade: Optional[str] = None
    nivel_dificuldade: Optional[str] = None
    nivel_aprendizado: Optional[str] = None
    duracao_minutos: Optional[int] = None
    necessidades_alvo: Optional[str] = None    # JSON list de NEE compatíveis
    objetivo: Optional[str] = None
    instrucao_professor: Optional[str] = None
    instrucao_familia: Optional[str] = None
    conteudo_atividade: Optional[str] = None
    materiais: Optional[str] = None            # JSON list
    passo_a_passo: Optional[str] = None        # JSON list
    adaptacoes: Optional[str] = None           # JSON list
    criterios_avaliacao: Optional[str] = None  # JSON list
    tags: Optional[str] = None                 # JSON list
    ativo: bool = Field(default=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🧠 Utilidades
# =========================================================
def parse_json_field(data: str):
    try:
        return json.loads(data)
    except Exception:
        return data or {}