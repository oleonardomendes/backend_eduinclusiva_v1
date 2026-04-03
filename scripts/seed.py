"""
scripts/seed.py
Popula o banco com dados de exemplo para desenvolvimento e demonstração.
Uso: python scripts/seed.py
"""
import sys
import os
from pathlib import Path
from datetime import date

# ── Adiciona a raiz do projeto ao sys.path ─────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Carrega o .env ANTES de importar app.database ──────────────────────────
# app/database.py lê DATABASE_URL no momento do import via os.getenv()
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    print("⚠️  python-dotenv não instalado. Usando variáveis de ambiente do sistema.")

# ── Imports do projeto (após .env estar carregado) ──────────────────────────
from sqlmodel import Session, select
from passlib.context import CryptContext

from app.database import engine, init_db
from app.models import Usuario, Aluno, Avaliacao, Meta

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Contadores globais para o resumo ────────────────────────────────────────
stats = {"criados": 0, "pulados": 0}


def _ok(msg: str):
    print(f"  ✅ {msg}")
    stats["criados"] += 1


def _skip(msg: str):
    print(f"  ⚠️  Já existe, pulando: {msg}")
    stats["pulados"] += 1


# ============================================================
# PROFESSOR
# ============================================================
def seed_professor(session: Session) -> Usuario:
    print("\n👤 Professor")
    existing = session.exec(
        select(Usuario).where(Usuario.email == "leo@eduinclusiva.com")
    ).first()

    if existing:
        _skip("leo@eduinclusiva.com")
        return existing

    professor = Usuario(
        nome="Professor Leo",
        email="leo@eduinclusiva.com",
        senha_hash=pwd_context.hash("Teste123!"),
        papel="professor",
    )
    session.add(professor)
    session.commit()
    session.refresh(professor)
    _ok(f"Professor Leo criado (id={professor.id})")
    return professor


# ============================================================
# ALUNOS
# ============================================================
ALUNOS_DATA = [
    dict(
        nome="João Pedro Silva",
        matricula="2024001234",
        idade=8,
        necessidade="Autismo leve",
        observacoes=(
            "Dificuldade de concentração, responde bem a atividades práticas e visuais. "
            "Evitar ambientes com muito barulho."
        ),
        escola="EMEF Maria Silva",
        sala="Sala A - 2º Ano",
        foto=None,
        data_nascimento=date(2016, 3, 15),
        genero="Masculino",
        telefone_contato="(11) 98765-4321",
        contato_emergencia_nome="Maria Silva",
        contato_emergencia_telefone="(11) 91234-5678",
        contato_emergencia_parentesco="Mãe",
        informacoes_medicas='{"diagnostico": "Transtorno do Espectro Autista leve", "alergias": "Nenhuma", "medicamentos": "Nenhum"}',
        nivel_aprendizado="Básico",
        objetivos_aprendizado=(
            "Desenvolver leitura de palavras simples, melhorar concentração em atividades "
            "de até 20 minutos, ampliar vocabulário"
        ),
        alergias="Nenhuma",
        medicamentos="Nenhum",
        endereco="Rua das Flores, 123 - Jardim Esperança - São Paulo/SP",
        horario_aulas="Manhã (7h-12h)",
        progresso_geral=45,
    ),
    dict(
        nome="Ana Clara Santos",
        matricula="2024001235",
        idade=9,
        necessidade="Dislexia",
        observacoes=(
            "Dificuldade na leitura e escrita, troca letras similares (b/d, p/q). "
            "Boa capacidade matemática e raciocínio lógico."
        ),
        escola="EMEF Maria Silva",
        sala="Sala A - 2º Ano",
        foto=None,
        data_nascimento=date(2015, 7, 22),
        genero="Feminino",
        telefone_contato="(11) 97654-3210",
        contato_emergencia_nome="Carlos Santos",
        contato_emergencia_telefone="(11) 92345-6789",
        contato_emergencia_parentesco="Pai",
        informacoes_medicas='{"diagnostico": "Dislexia moderada", "alergias": "Alergia a amendoim", "medicamentos": "Nenhum"}',
        nivel_aprendizado="Intermediário",
        objetivos_aprendizado=(
            "Melhorar decodificação de palavras, desenvolver estratégias de leitura "
            "compensatórias, fortalecer autoestima"
        ),
        alergias="Amendoim",
        medicamentos="Nenhum",
        endereco="Av. Brasil, 456 - Vila Nova - São Paulo/SP",
        horario_aulas="Manhã (7h-12h)",
        progresso_geral=62,
    ),
    dict(
        nome="Lucas Gabriel Oliveira",
        matricula="2024001236",
        idade=10,
        necessidade="TDAH",
        observacoes=(
            "Dificuldade de atenção sustentada, hiperatividade moderada. "
            "Responde muito bem a atividades curtas com recompensas imediatas."
        ),
        escola="EMEF Maria Silva",
        sala="Sala B - 3º Ano",
        foto=None,
        data_nascimento=date(2014, 11, 8),
        genero="Masculino",
        telefone_contato="(11) 96543-2109",
        contato_emergencia_nome="Fernanda Oliveira",
        contato_emergencia_telefone="(11) 93456-7890",
        contato_emergencia_parentesco="Mãe",
        informacoes_medicas='{"diagnostico": "TDAH tipo combinado", "alergias": "Nenhuma", "medicamentos": "Ritalina 10mg (manhã)"}',
        nivel_aprendizado="Intermediário",
        objetivos_aprendizado=(
            "Aumentar tempo de atenção, desenvolver estratégias de autorregulação, "
            "melhorar organização escolar"
        ),
        alergias="Nenhuma",
        medicamentos="Ritalina 10mg (manhã)",
        endereco="Rua das Palmeiras, 789 - Centro - São Paulo/SP",
        horario_aulas="Tarde (13h-18h)",
        progresso_geral=58,
    ),
]


def seed_alunos(session: Session, professor_id: int) -> list[Aluno]:
    print("\n👦 Alunos")
    alunos_criados = []

    for dados in ALUNOS_DATA:
        existing = session.exec(
            select(Aluno).where(Aluno.matricula == dados["matricula"])
        ).first()

        if existing:
            _skip(dados["nome"])
            alunos_criados.append(existing)
            continue

        aluno = Aluno(**dados, professor_id=professor_id)
        session.add(aluno)
        session.commit()
        session.refresh(aluno)
        _ok(f"Aluno {aluno.nome} criado (id={aluno.id})")
        alunos_criados.append(aluno)

    return alunos_criados


# ============================================================
# AVALIAÇÕES
# ============================================================
AVALIACOES_DATA = [
    # João Pedro Silva (índice 0)
    dict(bimestre=1, ano=2026, nota=5.0, progresso=35, observacoes="Dificuldade inicial de adaptação"),
    dict(bimestre=2, ano=2026, nota=6.0, progresso=45, observacoes="Evolução positiva com atividades visuais"),
    # Ana Clara Santos (índice 1)
    dict(bimestre=1, ano=2026, nota=6.5, progresso=55, observacoes="Boa adaptação às estratégias compensatórias"),
    dict(bimestre=2, ano=2026, nota=7.0, progresso=62, observacoes="Progresso consistente na leitura"),
    # Lucas Gabriel Oliveira (índice 2)
    dict(bimestre=1, ano=2026, nota=6.0, progresso=50, observacoes="Medicação ajudando na concentração"),
    dict(bimestre=2, ano=2026, nota=6.5, progresso=58, observacoes="Melhora na organização das tarefas"),
]

# Mapeamento: índice_aluno → [índice_avaliação, ...]
_ALUNO_AVALS = {0: [0, 1], 1: [2, 3], 2: [4, 5]}


def seed_avaliacoes(session: Session, alunos: list[Aluno], professor_id: int):
    print("\n📝 Avaliações")

    for aluno_idx, aval_indices in _ALUNO_AVALS.items():
        aluno = alunos[aluno_idx]
        for aval_idx in aval_indices:
            dados = AVALIACOES_DATA[aval_idx]
            existing = session.exec(
                select(Avaliacao).where(
                    Avaliacao.aluno_id == aluno.id,
                    Avaliacao.bimestre == dados["bimestre"],
                    Avaliacao.ano == dados["ano"],
                )
            ).first()

            label = f"{aluno.nome} — {dados['ano']} B{dados['bimestre']}"
            if existing:
                _skip(label)
                continue

            avaliacao = Avaliacao(
                aluno_id=aluno.id,
                professor_id=professor_id,
                **dados,
            )
            session.add(avaliacao)
            session.commit()
            _ok(f"Avaliação criada: {label}")


# ============================================================
# METAS
# ============================================================
METAS_DATA = [
    dict(sala="Sala A - 2º Ano", bimestre=1, ano=2026, meta_progresso=40, descricao="Meta inicial de adaptação"),
    dict(sala="Sala A - 2º Ano", bimestre=2, ano=2026, meta_progresso=55, descricao="Meta de progressão do 2º bimestre"),
    dict(sala="Sala A - 2º Ano", bimestre=3, ano=2026, meta_progresso=70, descricao="Meta de consolidação"),
    dict(sala="Sala A - 2º Ano", bimestre=4, ano=2026, meta_progresso=80, descricao="Meta final do ano"),
    dict(sala="Sala B - 3º Ano", bimestre=1, ano=2026, meta_progresso=45, descricao="Meta inicial Sala B"),
    dict(sala="Sala B - 3º Ano", bimestre=2, ano=2026, meta_progresso=60, descricao="Meta 2º bimestre Sala B"),
    dict(sala="Sala B - 3º Ano", bimestre=3, ano=2026, meta_progresso=72, descricao="Meta de consolidação Sala B"),
    dict(sala="Sala B - 3º Ano", bimestre=4, ano=2026, meta_progresso=82, descricao="Meta final Sala B"),
]


def seed_metas(session: Session, professor_id: int):
    print("\n🎯 Metas")

    for dados in METAS_DATA:
        existing = session.exec(
            select(Meta).where(
                Meta.professor_id == professor_id,
                Meta.sala == dados["sala"],
                Meta.bimestre == dados["bimestre"],
                Meta.ano == dados["ano"],
            )
        ).first()

        label = f"{dados['sala']} — {dados['ano']} B{dados['bimestre']}"
        if existing:
            _skip(label)
            continue

        meta = Meta(professor_id=professor_id, **dados)
        session.add(meta)
        session.commit()
        _ok(f"Meta criada: {label} ({dados['meta_progresso']}%)")


# ============================================================
# ENTRY POINT
# ============================================================
def seed():
    print("=" * 55)
    print("  🌱  EduInclusiva — Seed de dados de exemplo")
    print("=" * 55)
    print(f"  DATABASE_URL: {os.getenv('DATABASE_URL', 'não definida')[:60]}...")

    print("\n🔄 Inicializando tabelas...")
    init_db()

    with Session(engine) as session:
        professor = seed_professor(session)
        alunos = seed_alunos(session, professor.id)
        seed_avaliacoes(session, alunos, professor.id)
        seed_metas(session, professor.id)

    print("\n" + "=" * 55)
    print("  📊  Resumo")
    print("=" * 55)
    print(f"  ✅  Criados : {stats['criados']}")
    print(f"  ⚠️   Pulados : {stats['pulados']}")
    print(f"  📦  Total   : {stats['criados'] + stats['pulados']}")
    print("=" * 55)
    print("  ✔️   Seed concluído com sucesso!")
    print("=" * 55)


if __name__ == "__main__":
    seed()
