# services/gemini_service.py
import os
import json
import re
import logging
from datetime import datetime

import google.generativeai as genai
from sqlmodel import Session, select

from app.models import Aluno, Avaliacao, Meta, Plano

logger = logging.getLogger("uvicorn")


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


def _limpar_json_gemini(texto: str) -> str:
    """Remove blocos ```json``` que o Gemini às vezes retorna."""
    return re.sub(r"```(?:json)?", "", texto).strip().rstrip("`").strip()


def gerar_atividade_adaptada(aluno_id: int, professor_id: int, session: Session) -> dict:
    """
    Gera uma atividade pedagógica adaptada via Gemini 1.5 Flash com
    contexto completo do aluno (perfil, avaliações, metas e planos recentes).

    Retorna um dict com os campos da atividade.
    """
    # ── 1. Perfil do aluno ─────────────────────────────────────────────────
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        raise ValueError(f"Aluno {aluno_id} não encontrado.")

    # ── 2. Bimestre atual ──────────────────────────────────────────────────
    bimestre, ano = _bimestre_atual()

    # ── 3. Progresso real (média das avaliações do ano) ────────────────────
    progresso_real = round(_progresso_real(session, aluno_id, ano), 1)

    # ── 4. Meta do bimestre ────────────────────────────────────────────────
    meta_progresso = _meta_bimestre(session, professor_id, bimestre, ano)

    # ── 5. Histórico de atividades recentes ───────────────────────────────
    titulos_recentes = _titulos_planos_recentes(session, aluno_id)
    historico = "\n".join(f"- {t}" for t in titulos_recentes) if titulos_recentes else "Nenhuma atividade anterior"

    # ── 6. Cálculo da situação em relação à meta ──────────────────────────
    gap = meta_progresso - progresso_real
    if gap > 5:
        situacao = "abaixo"
    elif gap < -5:
        situacao = "acima"
    else:
        situacao = "dentro"

    # ── 7. Montagem do prompt ──────────────────────────────────────────────
    prompt = f"""Você é um especialista em educação inclusiva e pedagogia adaptada.

PERFIL DO ALUNO:
- Nome: {aluno.nome}
- Idade: {aluno.idade} anos
- Necessidade especial: {aluno.necessidade}
- Observações pedagógicas: {aluno.observacoes}
- Nível atual: {aluno.nivel_aprendizado}
- Progresso geral: {aluno.progresso_geral}%

SITUAÇÃO PEDAGÓGICA:
- {bimestre}º bimestre de {ano}
- Meta: {meta_progresso}%
- Progresso real: {progresso_real}%
- Situação: {situacao} da meta em {abs(gap):.1f}%

ATIVIDADES RECENTES (não repita):
{historico}

TAREFA:
Gere UMA atividade pedagógica adaptada e detalhada.
- Abaixo da meta: foque em recuperação e reforço
- Dentro da meta: foque em consolidação
- Acima da meta: foque em avanço e enriquecimento
Considere sempre a necessidade especial do aluno.

Responda APENAS com JSON válido, sem markdown, sem texto extra:
{{
  "titulo": "string",
  "objetivo": "string",
  "duracao_minutos": number,
  "dificuldade": "Fácil|Médio|Difícil",
  "materiais": ["string"],
  "passo_a_passo": ["string"],
  "adaptacoes": ["string"],
  "criterios_avaliacao": ["string"],
  "justificativa": "string"
}}"""

    # ── 8. Chamada ao Gemini ───────────────────────────────────────────────
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurada nas variáveis de ambiente.")

    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel("gemini-2.0-flash")

    logger.info(f"Gerando atividade via Gemini para aluno {aluno_id} ({aluno.nome})")
    response = gemini_model.generate_content(prompt)

    # ── 9. Parse do JSON ───────────────────────────────────────────────────
    raw = _limpar_json_gemini(response.text)
    try:
        resultado = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Falha ao parsear JSON do Gemini: {e}\nResposta bruta:\n{raw}")
        raise ValueError(f"Gemini retornou resposta inválida (não é JSON): {e}") from e

    logger.info(f"Atividade gerada com sucesso: '{resultado.get('titulo')}'")
    return resultado
