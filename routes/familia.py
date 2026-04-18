# routes/familia.py
"""
Portal da Família — endpoints para responsáveis acompanharem e estimularem
seus filhos com necessidades especiais em casa.
"""
import os
import json
import traceback
import logging
from typing import Optional
from datetime import datetime, timedelta, date

from fastapi import APIRouter, Depends, HTTPException
from groq import Groq
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import FilhoPublico, AtividadeGerada, RegistroPercepcao
from routes.auth import get_current_user, Usuario
from services.ai_service import (
    analisar_estilo_aprendizagem,
    gerar_atividade_familia,
    _limpar_json_resposta,
)

logger = logging.getLogger("uvicorn")

router = APIRouter()

PAPEL_FAMILIA = {"familia", "family"}


# =========================================================
# Schemas inline
# =========================================================

class FilhoCreate(BaseModel):
    nome: str
    idade: Optional[int] = None
    condicao: Optional[str] = None
    grau_necessidade: Optional[str] = None
    aluno_id: Optional[int] = None


class FilhoUpdate(BaseModel):
    nome: Optional[str] = None
    idade: Optional[int] = None
    condicao: Optional[str] = None
    grau_necessidade: Optional[str] = None
    aluno_id: Optional[int] = None


class QuestionarioEstiloRequest(BaseModel):
    respostas: dict  # {"p1": "a", "p2": "b", ...}
    condicao: str
    idade: int
    grau: str


class GerarAtividadeRequest(BaseModel):
    area: str                       # "Matemática", "Leitura", "Comunicação", etc.
    descricao_situacao: str         # descrição do que o responsável quer trabalhar
    duracao_minutos: int = 20       # tempo disponível em casa


class PercepaoCreate(BaseModel):
    humor: str                      # "otimo"|"bem"|"regular"|"dificil"
    observacao: Optional[str] = None
    proxima_acao: str               # "repetir"|"adaptar"|"proxima"


class UpgradePlanoRequest(BaseModel):
    plano: str                      # "familia"


# =========================================================
# Guard de papel
# =========================================================

def _verificar_familia(current_user: Usuario) -> None:
    papel = (current_user.papel or "").lower()
    if papel not in PAPEL_FAMILIA:
        raise HTTPException(
            status_code=403,
            detail="Apenas responsáveis (papel 'familia') podem acessar este recurso."
        )


def _verificar_dono_filho(filho: FilhoPublico, current_user: Usuario) -> None:
    if filho.responsavel_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado a este filho.")


_EXCLUSIVAS_PAGO = {"questionario_estilo", "percepcao", "evolucao", "pdf"}
_PLANOS_PAGOS = {"familia", "professor", "escola"}


def verificar_acesso_plano(
    current_user: Usuario,
    funcionalidade: str,
    session: Session,
) -> tuple[bool, str]:
    plano = current_user.plano or "gratuito"

    if funcionalidade in _EXCLUSIVAS_PAGO:
        if plano == "gratuito":
            return False, "Esta funcionalidade é exclusiva do Plano Família."
        return True, ""

    if funcionalidade == "gerar_atividade":
        if plano in _PLANOS_PAGOS:
            return True, ""

        agora = datetime.utcnow()
        reset = current_user.atividades_mes_reset
        if (
            reset is None
            or reset.month != agora.month
            or reset.year != agora.year
        ):
            current_user.atividades_mes_count = 0
            current_user.atividades_mes_reset = agora
            session.add(current_user)
            session.commit()

        if current_user.atividades_mes_count >= 3:
            return (
                False,
                "Você atingiu o limite de 3 atividades gratuitas este mês. "
                "Assine o Plano Família para atividades ilimitadas.",
            )
        return True, ""

    return True, ""


# =========================================================
# POST /filhos/ — cadastrar filho
# =========================================================

@router.post("/filhos/", status_code=201)
def criar_filho(
    dados: FilhoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = FilhoPublico(
        responsavel_id=current_user.id,
        nome=dados.nome,
        idade=dados.idade,
        condicao=dados.condicao,
        grau_necessidade=dados.grau_necessidade,
        aluno_id=dados.aluno_id,
    )
    session.add(filho)
    session.commit()
    session.refresh(filho)
    return filho


# =========================================================
# GET /filhos/ — listar filhos do responsável
# =========================================================

@router.get("/filhos/")
def listar_filhos(
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filhos = session.exec(
        select(FilhoPublico).where(FilhoPublico.responsavel_id == current_user.id)
    ).all()
    return filhos


# =========================================================
# GET /filhos/{id} — detalhes de um filho
# =========================================================

@router.get("/filhos/{filho_id}")
def obter_filho(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)
    return filho


# =========================================================
# PUT /filhos/{id} — atualizar dados do filho
# =========================================================

@router.put("/filhos/{filho_id}")
def atualizar_filho(
    filho_id: int,
    dados: FilhoUpdate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(filho, campo, valor)

    session.add(filho)
    session.commit()
    session.refresh(filho)
    return filho


# =========================================================
# POST /filhos/{id}/questionario-estilo — analisar estilo via IA
# =========================================================

@router.post("/filhos/{filho_id}/questionario-estilo")
def questionario_estilo(
    filho_id: int,
    body: QuestionarioEstiloRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    tem_acesso, msg = verificar_acesso_plano(current_user, "questionario_estilo", session)
    if not tem_acesso:
        raise HTTPException(status_code=403, detail=msg)

    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    if len(body.respostas) < 4:
        raise HTTPException(
            status_code=422,
            detail="Mínimo de 4 respostas necessárias para análise."
        )

    try:
        # Converte dict {"p1": "a", ...} para list[dict] {"pergunta": k, "resposta": v}
        respostas_lista = [
            {"pergunta": k, "resposta": v}
            for k, v in body.respostas.items()
        ]

        analise = analisar_estilo_aprendizagem(
            respostas=respostas_lista,
            condicao=body.condicao,
            idade=body.idade,
            grau=body.grau,
        )

        # Persiste o resultado no perfil do filho
        filho.estilo_aprendizagem = analise["estilo"]
        if not filho.grau_necessidade:
            filho.grau_necessidade = analise["grau"]
        filho.relatorio_estilo = analise["relatorio"]

        session.add(filho)
        session.commit()
        session.refresh(filho)

        return {
            "estilo_aprendizagem": analise["estilo"],
            "grau_necessidade": analise["grau"],
            "relatorio": analise["relatorio"],
            "filho": filho,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERRO DETALHADO questionario-estilo: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


# =========================================================
# GET /filhos/{id}/relatorio-estilo — retorna o relatório salvo
# =========================================================

@router.get("/filhos/{filho_id}/relatorio-estilo")
def relatorio_estilo(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    if not filho.relatorio_estilo:
        raise HTTPException(
            status_code=404,
            detail="Relatório não disponível. Aplique o questionário primeiro."
        )

    return {
        "estilo_aprendizagem": filho.estilo_aprendizagem,
        "grau_necessidade": filho.grau_necessidade,
        "relatorio": filho.relatorio_estilo,
    }


# =========================================================
# POST /filhos/{id}/gerar-atividade — gerar atividade para casa
# =========================================================

@router.post("/filhos/{filho_id}/gerar-atividade", status_code=201)
def gerar_atividade(
    filho_id: int,
    body: GerarAtividadeRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    tem_acesso, msg = verificar_acesso_plano(current_user, "gerar_atividade", session)
    if not tem_acesso:
        raise HTTPException(status_code=403, detail=msg)

    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    try:
        atividade = gerar_atividade_familia(
            filho=filho,
            area=body.area,
            descricao_situacao=body.descricao_situacao,
            duracao_minutos=body.duracao_minutos,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na geração de atividade: {str(e)}")

    # Incrementa contador mensal após geração bem-sucedida
    current_user.atividades_mes_count += 1
    session.add(current_user)
    session.commit()

    return atividade


# =========================================================
# GET /filhos/{id}/atividades — listar atividades geradas
# =========================================================

@router.get("/filhos/{filho_id}/atividades")
def listar_atividades(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    atividades = session.exec(
        select(AtividadeGerada)
        .where(AtividadeGerada.aluno_id == filho_id)
        .order_by(AtividadeGerada.criado_em.desc())  # type: ignore[attr-defined]
    ).all()

    return atividades


# =========================================================
# Helpers de percepção
# =========================================================

_HUMOR_VALOR = {"otimo": 3, "bem": 2, "regular": 1, "dificil": 0}


def _humor_para_float(humor: str) -> float:
    return float(_HUMOR_VALOR.get(humor, 1))


def _tendencia(registros: list) -> str:
    """Últimos 5 registros da área, ordenados ASC. Compara média dos últimos 2 vs primeiros 3."""
    if len(registros) < 2:
        return "estavel"
    valores = [_humor_para_float(r.humor) for r in registros]
    ultimos2 = sum(valores[-2:]) / 2
    primeiros = valores[:-2]
    if not primeiros:
        return "estavel"
    media_primeiros = sum(primeiros) / len(primeiros)
    diff = ultimos2 - media_primeiros
    if diff > 0.3:
        return "melhorando"
    if diff < -0.3:
        return "precisa_atencao"
    return "estavel"


def _chamar_groq_json(prompt: str) -> dict | None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        raw = _limpar_json_resposta(response.choices[0].message.content)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Groq inline error: {e}")
        return None


# =========================================================
# POST /filhos/{filho_id}/atividades/{atividade_id}/percepcao
# =========================================================

@router.post("/filhos/{filho_id}/atividades/{atividade_id}/percepcao", status_code=201)
def registrar_percepcao(
    filho_id: int,
    atividade_id: int,
    body: PercepaoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    tem_acesso, msg = verificar_acesso_plano(current_user, "percepcao", session)
    if not tem_acesso:
        raise HTTPException(status_code=403, detail=msg)

    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    atividade = session.get(AtividadeGerada, atividade_id)
    if not atividade:
        raise HTTPException(status_code=404, detail="Atividade não encontrada.")

    analise_ia = None
    if body.observacao and body.observacao.strip():
        prompt = f"""Um pai registrou a seguinte observação sobre uma atividade com seu filho que tem {filho.condicao or "necessidade especial"}:

Observação: {body.observacao}
Humor da criança: {body.humor}

Analise brevemente (máximo 2 frases) e identifique:
1. Um ponto positivo observado
2. Uma sugestão prática para a próxima vez

Responda em JSON:
{{"ponto_positivo": "string", "sugestao": "string"}}"""

        resultado = _chamar_groq_json(prompt)
        if resultado:
            analise_ia = json.dumps(resultado, ensure_ascii=False)

    percepcao_existente = session.exec(
        select(RegistroPercepcao).where(
            RegistroPercepcao.atividade_id == atividade_id,
            RegistroPercepcao.filho_id == filho_id,
        )
    ).first()

    if percepcao_existente:
        percepcao_existente.humor = body.humor
        percepcao_existente.observacao = body.observacao
        percepcao_existente.proxima_acao = body.proxima_acao
        percepcao_existente.analise_ia = analise_ia
        percepcao_existente.criado_em = datetime.utcnow()
        session.add(percepcao_existente)
        session.commit()
        session.refresh(percepcao_existente)
        registro = percepcao_existente
    else:
        registro = RegistroPercepcao(
            filho_id=filho_id,
            atividade_id=atividade_id,
            responsavel_id=current_user.id,
            humor=body.humor,
            observacao=body.observacao,
            proxima_acao=body.proxima_acao,
            analise_ia=analise_ia,
            area=atividade.disciplina,
        )
        session.add(registro)
        session.commit()
        session.refresh(registro)

    return {
        "registro": registro,
        "analise_ia": json.loads(analise_ia) if analise_ia else None,
    }


# =========================================================
# GET /filhos/{filho_id}/percepcoes
# =========================================================

@router.get("/filhos/{filho_id}/percepcoes")
def listar_percepcoes(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    registros = session.exec(
        select(RegistroPercepcao)
        .where(RegistroPercepcao.filho_id == filho_id)
        .order_by(RegistroPercepcao.criado_em.desc())  # type: ignore[attr-defined]
    ).all()

    return [
        {
            **r.model_dump(),
            "analise_ia": json.loads(r.analise_ia) if r.analise_ia else None,
        }
        for r in registros
    ]


# =========================================================
# GET /filhos/{filho_id}/evolucao
# =========================================================

@router.get("/filhos/{filho_id}/evolucao")
def evolucao_filho(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    tem_acesso, msg = verificar_acesso_plano(current_user, "evolucao", session)
    if not tem_acesso:
        raise HTTPException(status_code=403, detail=msg)

    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    total_atividades = len(set(
        r.atividade_id for r in session.exec(
            select(RegistroPercepcao).where(RegistroPercepcao.filho_id == filho_id)
        ).all()
    ))

    registros = session.exec(
        select(RegistroPercepcao)
        .where(RegistroPercepcao.filho_id == filho_id)
        .order_by(RegistroPercepcao.criado_em.asc())  # type: ignore[attr-defined]
    ).all()

    total_registros = len(registros)

    # ── humor_geral ───────────────────────────────────────
    humor_geral = {"otimo": 0, "bem": 0, "regular": 0, "dificil": 0}
    for r in registros:
        if r.humor in humor_geral:
            humor_geral[r.humor] += 1

    # ── por_area ──────────────────────────────────────────
    areas_map: dict[str, list] = {}
    for r in registros:
        area_key = r.area or "Geral"
        areas_map.setdefault(area_key, []).append(r)

    por_area = []
    for area_key, regs in areas_map.items():
        valores = [_humor_para_float(r.humor) for r in regs]
        humor_medio = round(sum(valores) / len(valores), 2)
        ultimos5 = regs[-5:]
        por_area.append({
            "area": area_key,
            "total": len(regs),
            "humor_medio": humor_medio,
            "tendencia": _tendencia(ultimos5),
        })

    # ── ultimos_30_dias ───────────────────────────────────
    corte = datetime.utcnow() - timedelta(days=30)
    recentes = [r for r in registros if r.criado_em >= corte]

    dias_map: dict[str, list] = {}
    for r in recentes:
        dia = r.criado_em.date().isoformat()
        dias_map.setdefault(dia, []).append(r)

    ultimos_30_dias = [
        {
            "data": dia,
            "humor_valor": round(
                sum(_humor_para_float(r.humor) for r in regs) / len(regs), 2
            ),
            "total_atividades": len(regs),
        }
        for dia, regs in sorted(dias_map.items())
    ]

    # ── insights via Groq ─────────────────────────────────
    insights: list[str] = []
    if total_registros > 0:
        prompt = f"""Com base nos registros de atividades de {filho.nome} ({filho.condicao or "necessidade especial"}, {filho.idade or "?"} anos):

Total de atividades: {total_atividades}
Total de registros: {total_registros}
Humor geral: {humor_geral}
Áreas trabalhadas: {[p["area"] for p in por_area]}

Gere 3 insights curtos e encorajadores para os pais, baseados nos dados. Foque no progresso e em sugestões práticas.

Responda em JSON:
{{"insights": ["string", "string", "string"]}}"""

        resultado = _chamar_groq_json(prompt)
        if resultado and isinstance(resultado.get("insights"), list):
            insights = resultado["insights"][:3]

    return {
        "total_atividades": total_atividades,
        "total_registros": total_registros,
        "humor_geral": humor_geral,
        "por_area": por_area,
        "ultimos_30_dias": ultimos_30_dias,
        "insights": insights,
    }


# =========================================================
# GET /plano — status do plano do responsável
# =========================================================

@router.get("/plano")
def status_plano(
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    plano = current_user.plano or "gratuito"
    pago = plano in _PLANOS_PAGOS

    atividades_usadas = current_user.atividades_mes_count or 0
    limite = None if pago else 3
    restantes = None if pago else max(0, 3 - atividades_usadas)

    return {
        "plano": plano,
        "atividades_usadas": atividades_usadas,
        "atividades_limite": limite,
        "atividades_restantes": restantes,
        "funcionalidades": {
            "questionario_estilo": pago,
            "percepcao": pago,
            "evolucao": pago,
            "pdf": pago,
            "atividades_ilimitadas": pago,
        },
    }


# =========================================================
# POST /plano/upgrade — upgrade do plano (simulado)
# =========================================================

PLANOS_VALIDOS = {"familia", "professor", "escola", "gratuito"}


@router.post("/plano/upgrade")
def upgrade_plano(
    body: UpgradePlanoRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    if body.plano not in PLANOS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Plano inválido. Opções: {', '.join(PLANOS_VALIDOS)}"
        )

    current_user.plano = body.plano
    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    return {
        "mensagem": f"Plano atualizado para '{body.plano}' com sucesso.",
        "plano": current_user.plano,
        "email": current_user.email,
    }
