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

    # Plano e controle de uso mensal
    plano: str = Field(default="gratuito")              # "gratuito" | "familia" | "professor" | "escola"
    atividades_mes_count: int = Field(default=0)        # atividades geradas no mês corrente
    atividades_mes_reset: Optional[datetime] = None     # data do último reset do contador

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
    estilo_aprendizagem: Optional[str] = None            # "Visual", "Auditivo", "Cinestésico", "Visual-Cinestésico", "Misto"
    grau_necessidade: Optional[str] = None               # "Leve", "Moderado", "Severo"


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
    concluida: bool = Field(default=False)
    concluida_em: Optional[datetime] = None
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
# ✅ Conclusão de Atividade com avaliação por competências
# =========================================================
class ConclusaoAtividade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    atividade_id: int = Field(foreign_key="atividadegerada.id", index=True)
    aluno_id: int = Field(foreign_key="aluno.id", index=True)
    professor_id: int = Field(foreign_key="usuario.id", index=True)

    # Observação geral
    observacoes: Optional[str] = None

    # Notas por competência (0.0 a 10.0)
    nota_comunicacao: Optional[float] = None
    nota_coordenacao_motora: Optional[float] = None
    nota_cognicao: Optional[float] = None
    nota_socializacao: Optional[float] = None
    nota_autonomia: Optional[float] = None
    nota_linguagem: Optional[float] = None

    # Nota geral calculada (média das competências preenchidas)
    nota_geral: Optional[float] = None

    # Quais competências foram trabalhadas nesta atividade
    competencias_trabalhadas: Optional[str] = None  # JSON list

    concluido_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 👨‍👩‍👦 Filho Público (portal da família)
# =========================================================
class FilhoPublico(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    responsavel_id: int = Field(foreign_key="usuario.id", index=True)
    aluno_id: Optional[int] = Field(default=None, foreign_key="aluno.id", index=True)
    nome: str
    idade: Optional[int] = None
    condicao: Optional[str] = None              # diagnóstico/condição descrita pela família
    estilo_aprendizagem: Optional[str] = None   # detectado pelo questionário IA
    grau_necessidade: Optional[str] = None      # "Leve", "Moderado", "Severo"
    relatorio_estilo: Optional[str] = None      # relatório gerado pelo Groq (texto livre)
    progresso_geral: Optional[int] = Field(default=0)  # 0 a 100
    criado_em: datetime = Field(default_factory=datetime.utcnow)



# =========================================================
# 📝 Registro de Percepção (portal da família)
# =========================================================
class RegistroPercepcao(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filho_id: int = Field(foreign_key="filhopublico.id", index=True)
    atividade_id: int = Field(foreign_key="atividadegerada.id", index=True)
    responsavel_id: int = Field(foreign_key="usuario.id", index=True)

    # 3 perguntas simples
    humor: str                      # "otimo", "bem", "regular", "dificil"
    observacao: Optional[str] = None  # texto livre do pai
    proxima_acao: str               # "repetir", "adaptar", "proxima"

    # Campos calculados pela IA
    analise_ia: Optional[str] = None  # JSON com {"ponto_positivo": ..., "sugestao": ...}
    area: Optional[str] = None        # área da atividade (copiada no momento do registro)

    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🏥 Módulo Clínico — Paciente
# =========================================================
class PacienteClinico(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    especialista_id: int = Field(foreign_key="usuario.id", index=True)
    filho_publico_id: Optional[int] = Field(default=None, foreign_key="filhopublico.id", index=True)

    nome: str
    data_nascimento: Optional[date] = None
    idade: Optional[int] = None
    condicao: Optional[str] = None
    grau: Optional[str] = None
    estilo_aprendizagem: Optional[str] = None
    e_verbal: Optional[bool] = None
    usa_comunicacao_alternativa: Optional[bool] = None
    observacoes: Optional[str] = None
    escola: Optional[str] = None
    serie: Optional[str] = None
    responsavel_nome: Optional[str] = None
    responsavel_telefone: Optional[str] = None
    responsavel_email: Optional[str] = None
    terapias_em_andamento: Optional[str] = None     # JSON list
    usa_aba: Optional[bool] = Field(default=False)
    medicamentos: Optional[str] = None
    ativo: bool = Field(default=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🏥 Módulo Clínico — Sessão
# =========================================================
class SessaoClinica(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="pacienteclinico.id", index=True)
    especialista_id: int = Field(foreign_key="usuario.id", index=True)
    especialidade: str                              # "psicopedagogia", "psicomotricidade", "fono", "to", "psicologia", "aba", "outro"
    data_sessao: date
    duracao_minutos: Optional[int] = None
    humor_inicio: Optional[str] = None             # "otimo", "bem", "regular", "dificil"
    atividades_realizadas: Optional[str] = None
    resposta_crianca: Optional[str] = None
    o_que_funcionou: Optional[str] = None
    o_que_nao_funcionou: Optional[str] = None
    observacoes_clinicas: Optional[str] = None
    proxima_sessao_foco: Optional[str] = None

    # Psicopedagogia+
    habilidades_trabalhadas: Optional[str] = None  # JSON list
    nivel_leitura: Optional[str] = None
    nivel_escrita: Optional[str] = None
    nivel_matematica: Optional[str] = None

    # Psicomotricidade+
    coordenacao_fina: Optional[str] = None         # "emergente", "em_desenvolvimento", "consolidado"
    coordenacao_grossa: Optional[str] = None
    equilibrio: Optional[str] = None
    lateralidade: Optional[str] = None
    esquema_corporal: Optional[str] = None

    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🏥 Módulo Clínico — Plano Semanal
# =========================================================
class PlanoSemanal(SQLModel, table=True):
    __tablename__ = "planossemanal"
    id: Optional[int] = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="pacienteclinico.id", index=True)
    especialista_id: int = Field(foreign_key="usuario.id", index=True)
    sessao_id: Optional[int] = Field(default=None, foreign_key="sessaoclinica.id")
    semana_inicio: date
    semana_fim: date
    tarefas: str                                    # JSON list de tarefas
    orientacoes_gerais: Optional[str] = None
    atividade_ia_id: Optional[int] = Field(default=None, foreign_key="atividadegerada.id")
    enviado_familia: bool = Field(default=False)
    enviado_em: Optional[datetime] = None
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🏥 Módulo Clínico — Registro de Plano pela Família
# =========================================================
class RegistroPlanoFamilia(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plano_id: int = Field(foreign_key="planossemanal.id", index=True)
    paciente_id: int = Field(foreign_key="pacienteclinico.id", index=True)
    responsavel_id: int = Field(foreign_key="usuario.id", index=True)
    tarefa_index: int
    concluiu: bool = Field(default=False)
    humor: Optional[str] = None
    observacao: Optional[str] = None
    criado_em: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# 🔗 Vínculo Especialista ↔ Família
# =========================================================
class VinculoEspecialistaFamilia(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    especialista_id: int = Field(foreign_key="usuario.id", index=True)
    paciente_id: int = Field(foreign_key="pacienteclinico.id", index=True)
    filho_publico_id: Optional[int] = Field(default=None, foreign_key="filhopublico.id", index=True)
    responsavel_id: Optional[int] = Field(default=None, foreign_key="usuario.id", index=True)
    codigo_convite: str = Field(index=True)         # código único gerado pelo especialista
    status: str = Field(default="pendente")         # "pendente" | "ativo" | "inativo"
    criado_em: datetime = Field(default_factory=datetime.utcnow)
    aceito_em: Optional[datetime] = None


# =========================================================
# 🧠 Utilidades
# =========================================================
def parse_json_field(data: str):
    try:
        return json.loads(data)
    except Exception:
        return data or {}