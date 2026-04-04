# services/ai_service.py
import os
import json
import re
import logging
from datetime import datetime

from groq import Groq
from sqlmodel import Session, select

from app.models import Aluno, Avaliacao, AtividadeGerada, AtividadeTemplate, Meta, Plano

logger = logging.getLogger("uvicorn")


# =========================================================
# Helpers internos
# =========================================================

def _bimestre_atual() -> tuple[int, int]:
    """Retorna (bimestre, ano) com base no mês atual."""
    now = datetime.now()
    bimestre = (now.month - 1) // 3 + 1  # Jan-Mar=1, Abr-Jun=2, Jul-Set=3, Out-Dez=4
    return bimestre, now.year


def _progresso_real(session: Session, aluno_id: int, ano: int) -> float:
    """Média dos campos progresso das avaliações do aluno no ano (ignora None)."""
    avaliacoes = session.exec(
        select(Avaliacao).where(
            Avaliacao.aluno_id == aluno_id,
            Avaliacao.ano == ano,
            Avaliacao.progresso.is_not(None),  # type: ignore[attr-defined]
        )
    ).all()
    if not avaliacoes:
        return 0.0
    return sum(a.progresso for a in avaliacoes) / len(avaliacoes)  # type: ignore[arg-type]


def _meta_bimestre(session: Session, professor_id: int, bimestre: int, ano: int) -> int:
    """Retorna meta_progresso do bimestre ou 70 como padrão."""
    meta = session.exec(
        select(Meta).where(
            Meta.professor_id == professor_id,
            Meta.bimestre == bimestre,
            Meta.ano == ano,
        )
    ).first()
    return meta.meta_progresso if meta else 70


def _titulos_planos_recentes(session: Session, aluno_id: int) -> list[str]:
    """Últimos 3 títulos de planos do aluno."""
    planos = session.exec(
        select(Plano)
        .where(Plano.aluno_id == aluno_id)
        .order_by(Plano.criado_em.desc())  # type: ignore[attr-defined]
        .limit(3)
    ).all()
    return [p.titulo for p in planos]


def _limpar_json_resposta(texto: str) -> str:
    """Remove blocos ```json``` que o modelo às vezes retorna."""
    return re.sub(r"```(?:json)?", "", texto).strip().rstrip("`").strip()


def _serializar_lista(valor) -> str | None:
    """Serializa lista para JSON string; retorna None se valor for None."""
    if valor is None:
        return None
    if isinstance(valor, list):
        return json.dumps(valor, ensure_ascii=False)
    return valor  # já é string


# =========================================================
# Camada 1 — Template pré-cadastrado
# =========================================================

def _buscar_template(
    session: Session,
    necessidade: str | None,
    nivel_dificuldade: str | None,
) -> dict | None:
    templates = session.exec(
        select(AtividadeTemplate).where(AtividadeTemplate.ativo == True)  # noqa: E712
    ).all()

    for t in templates:
        # Verifica compatibilidade de necessidade
        if t.necessidades_alvo:
            try:
                nees = json.loads(t.necessidades_alvo)
            except (json.JSONDecodeError, TypeError):
                nees = []
            if necessidade and necessidade not in nees:
                continue
        # Filtra por nível de dificuldade se informado
        if nivel_dificuldade and t.nivel_dificuldade and t.nivel_dificuldade != nivel_dificuldade:
            continue
        return t.model_dump()

    return None


# =========================================================
# Camada 2 — IA reutilizável
# =========================================================

def _buscar_ia_reutilizavel(
    session: Session,
    aluno_id: int,
    necessidade: str | None,
    nivel_dificuldade: str | None,
) -> dict | None:
    query = (
        select(AtividadeGerada)
        .where(
            AtividadeGerada.reutilizavel == True,  # noqa: E712
            AtividadeGerada.necessidade_atendida == necessidade,
            AtividadeGerada.aluno_id != aluno_id,
        )
    )
    candidatas = session.exec(query).all()

    for a in candidatas:
        if nivel_dificuldade and a.dificuldade and a.dificuldade != nivel_dificuldade:
            continue
        return a.model_dump()

    return None


# =========================================================
# Camada 3 — Geração nova via Groq
# =========================================================

def _gerar_via_groq(
    session: Session,
    aluno: Aluno,
    professor_id: int,
    parametros: dict,
) -> dict:
    bimestre, ano = _bimestre_atual()
    progresso_real = round(_progresso_real(session, aluno.id, ano), 1)
    meta_progresso = _meta_bimestre(session, professor_id, bimestre, ano)

    titulos_recentes = _titulos_planos_recentes(session, aluno.id)
    historico = (
        "\n".join(f"- {t}" for t in titulos_recentes)
        if titulos_recentes
        else "Nenhuma atividade anterior"
    )

    gap = meta_progresso - progresso_real
    if gap > 5:
        situacao = "abaixo"
    elif gap < -5:
        situacao = "acima"
    else:
        situacao = "dentro"

    titulo = parametros.get("titulo") or "Atividade adaptada"
    disciplina = parametros.get("disciplina") or "Geral"
    tipo_atividade = parametros.get("tipo_atividade") or "Não especificado"
    nivel_dificuldade = parametros.get("nivel_dificuldade") or "Médio"
    duracao_minutos = parametros.get("duracao_minutos") or 30
    descricao = parametros.get("descricao") or "Não especificada"
    objetivos = parametros.get("objetivos") or "Não especificados"

    prompt = f"""Você é um especialista em educação inclusiva e pedagogia adaptada.

PERFIL DO ALUNO:
- Nome: {aluno.nome}
- Idade: {aluno.idade} anos
- Necessidade especial: {aluno.necessidade}
- Observações pedagógicas: {aluno.observacoes}
- Nível atual de aprendizado: {aluno.nivel_aprendizado}
- Objetivos de aprendizado: {aluno.objetivos_aprendizado}
- Progresso geral: {aluno.progresso_geral}%

SITUAÇÃO PEDAGÓGICA ATUAL:
- {bimestre}º bimestre de {ano}
- Meta de progresso: {meta_progresso}%
- Progresso real alcançado: {progresso_real}%
- Situação: {situacao} da meta em {abs(gap):.1f}%

PARÂMETROS DEFINIDOS PELO PROFESSOR PARA HOJE:
- Título desejado: {titulo}
- Disciplina: {disciplina}
- Tipo de atividade: {tipo_atividade}
- Nível de dificuldade: {nivel_dificuldade}
- Duração: {duracao_minutos} minutos
- Tema/descrição: {descricao}
- Objetivos específicos: {objetivos}

ATIVIDADES RECENTES (não repita):
{historico}

TAREFA:
Gere UMA atividade pedagógica adaptada respeitando os parâmetros do professor E o perfil do aluno.
- Se abaixo da meta: priorize recuperação e reforço
- Se dentro da meta: priorize consolidação
- Se acima da meta: priorize avanço e enriquecimento
Considere SEMPRE a necessidade especial do aluno em todas as seções.

Para instrucao_professor: explique como conduzir a atividade em sala usando materiais simples disponíveis na escola (lápis, borracha, caderno, tampinhas, palitos, etc). Seja prático com exemplos concretos.

Para instrucao_familia: explique como os pais podem fazer esta mesma atividade em casa usando objetos do dia a dia (colheres, botões, frutas, brinquedos, etc). Use linguagem simples e acessível.

Para conteudo_atividade: descreva o exercício detalhadamente como se fosse uma folha de atividade. Inclua exemplos práticos e espaços para resposta descritos em texto (ex: "Escreva o resultado aqui: ___").

Responda APENAS com JSON válido, sem markdown, sem texto extra:
{{
  "titulo": "string",
  "objetivo": "string",
  "duracao_minutos": number,
  "dificuldade": "Fácil|Médio|Difícil",
  "instrucao_professor": "string",
  "instrucao_familia": "string",
  "conteudo_atividade": "string",
  "materiais": ["string"],
  "passo_a_passo": ["string"],
  "adaptacoes": ["string"],
  "criterios_avaliacao": ["string"],
  "justificativa": "string",
  "tags": ["string"]
}}"""

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nas variáveis de ambiente.")

    client = Groq(api_key=api_key)
    logger.info(f"Gerando atividade via Groq para aluno {aluno.id} ({aluno.nome})")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    texto = response.choices[0].message.content

    raw = _limpar_json_resposta(texto)
    try:
        resultado = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Falha ao parsear JSON do Groq: {e}\nResposta bruta:\n{raw}")
        raise ValueError(f"Groq retornou resposta inválida (não é JSON): {e}") from e

    now = datetime.now()
    atividade = AtividadeGerada(
        aluno_id=aluno.id,
        professor_id=professor_id,
        titulo=resultado["titulo"],
        objetivo=resultado.get("objetivo"),
        duracao_minutos=resultado.get("duracao_minutos"),
        dificuldade=resultado.get("dificuldade"),
        instrucao_professor=resultado.get("instrucao_professor"),
        instrucao_familia=resultado.get("instrucao_familia"),
        conteudo_atividade=resultado.get("conteudo_atividade"),
        materiais=_serializar_lista(resultado.get("materiais")),
        passo_a_passo=_serializar_lista(resultado.get("passo_a_passo")),
        adaptacoes=_serializar_lista(resultado.get("adaptacoes")),
        criterios_avaliacao=_serializar_lista(resultado.get("criterios_avaliacao")),
        tags=_serializar_lista(resultado.get("tags")),
        justificativa=resultado.get("justificativa"),
        bimestre=(now.month - 1) // 3 + 1,
        ano=now.year,
        disciplina=parametros.get("disciplina"),
        tipo_atividade=parametros.get("tipo_atividade"),
        reutilizavel=True,
        necessidade_atendida=aluno.necessidade,
        parametros_professor=json.dumps(parametros, ensure_ascii=False),
    )
    session.add(atividade)
    session.commit()
    session.refresh(atividade)

    logger.info(f"Atividade gerada e salva com sucesso: '{atividade.titulo}' (id={atividade.id})")
    return atividade.model_dump()


# =========================================================
# Função principal — busca em 3 camadas
# =========================================================

def buscar_ou_gerar_atividade(
    aluno_id: int,
    professor_id: int,
    parametros: dict,
    session: Session,
) -> dict:
    """
    Busca ou gera uma atividade pedagógica adaptada em 3 camadas:
      1. Template pré-cadastrado (AtividadeTemplate)
      2. Atividade IA reutilizável (AtividadeGerada de outro aluno)
      3. Geração nova via Groq

    Retorna {"fonte": "template"|"ia_reutilizada"|"ia_nova", "atividade": dict}
    """
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        raise ValueError(f"Aluno {aluno_id} não encontrado.")

    nivel_dificuldade = parametros.get("nivel_dificuldade")

    # ── Camada 1: template ────────────────────────────────────────────────
    template = _buscar_template(session, aluno.necessidade, nivel_dificuldade)
    if template:
        logger.info(f"Atividade encontrada via template para aluno {aluno_id}")
        return {"fonte": "template", "atividade": template}

    # ── Camada 2: IA reutilizável ─────────────────────────────────────────
    reutilizavel = _buscar_ia_reutilizavel(session, aluno_id, aluno.necessidade, nivel_dificuldade)
    if reutilizavel:
        logger.info(f"Atividade IA reutilizada para aluno {aluno_id}")
        return {"fonte": "ia_reutilizada", "atividade": reutilizavel}

    # ── Camada 3: geração nova ────────────────────────────────────────────
    atividade_dict = _gerar_via_groq(session, aluno, professor_id, parametros)
    return {"fonte": "ia_nova", "atividade": atividade_dict}


# =========================================================
# Alias para compatibilidade com routes/ai.py atual
# =========================================================

def gerar_atividade_adaptada(aluno_id: int, professor_id: int, session: Session) -> dict:
    """
    Alias de compatibilidade — chama buscar_ou_gerar_atividade com parâmetros vazios
    e retorna apenas o dict da atividade (sem o campo "fonte").
    Será substituído quando routes/ai.py for atualizado.
    """
    resultado = buscar_ou_gerar_atividade(aluno_id, professor_id, {}, session)
    return resultado["atividade"]
