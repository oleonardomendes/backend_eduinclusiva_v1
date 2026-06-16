# routes/familia.py
"""
Portal da Família — endpoints para responsáveis acompanharem e estimularem
seus filhos com necessidades especiais em casa.
"""
import os
import re
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
from app.models import (
    FilhoPublico,
    AtividadeGerada,
    RegistroPercepcao,
    PacienteClinico,
    PlanoSemanal,
    RegistroPlanoFamilia,
    VinculoEspecialistaFamilia,
    Usuario as UsuarioModel,
    RotinaSemanal,
    ItemRotina,
    MudancaRotina,
    ImprevistoDia,
)
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
        logger.error("_chamar_groq_json: GROQ_API_KEY não configurada")
        return None
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1000,
        )
        resposta_raw = response.choices[0].message.content or ""
        print(f"Resposta RAW do Groq: '{resposta_raw}'")
        if not resposta_raw.strip():
            logger.error("_chamar_groq_json: Groq retornou resposta vazia")
            return None
        resposta_limpa = re.sub(r'```(?:json)?\s*|\s*```', '', resposta_raw).strip()
        return json.loads(resposta_limpa)
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


# =========================================================
# GET /planos-prescritos/ — planos semanais enviados pelo especialista
# =========================================================

_CORES_ESPECIALIDADE = {
    "psicomotricidade": "#1B4332",
    "psicopedagogia":   "#1E3A5F",
    "fono":             "#7B2D8B",
    "to":               "#C05200",
    "psicologia":       "#7F1D1D",
    "aba":              "#1A3A4A",
    "nutricao":         "#14532D",
    "fisioterapia":     "#1E1B4B",
}


@router.get("/planos-prescritos/")
def planos_prescritos(
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)

    vinculos = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.responsavel_id == current_user.id,
            VinculoEspecialistaFamilia.status == "ativo",
        )
    ).all()

    vazio = {"semana_atual": None, "por_especialidade": [], "semanas_anteriores": []}
    if not vinculos:
        return vazio

    paciente_ids = [v.paciente_id for v in vinculos]
    especialista_ids = {v.especialista_id for v in vinculos}

    especialistas = {
        u.id: u.nome
        for u in session.exec(
            select(UsuarioModel).where(
                UsuarioModel.id.in_(especialista_ids)  # type: ignore[attr-defined]
            )
        ).all()
    }

    planos = session.exec(
        select(PlanoSemanal)
        .where(
            PlanoSemanal.paciente_id.in_(paciente_ids),  # type: ignore[attr-defined]
            PlanoSemanal.enviado_familia == True,  # noqa: E712
        )
        .order_by(PlanoSemanal.semana_inicio.desc())  # type: ignore[attr-defined]
    ).all()

    if not planos:
        return vazio

    def _montar_grupo(plano: PlanoSemanal) -> dict:
        try:
            tarefas = json.loads(plano.tarefas)
        except (json.JSONDecodeError, TypeError):
            tarefas = []
        registros = session.exec(
            select(RegistroPlanoFamilia).where(
                RegistroPlanoFamilia.plano_id == plano.id
            )
        ).all()
        total = len(tarefas)
        concluidas = sum(1 for r in registros if r.concluiu)
        percentual = round(concluidas / total * 100, 1) if total else 0.0
        esp = plano.especialidade or "geral"
        return {
            "especialidade": esp,
            "cor": _CORES_ESPECIALIDADE.get(esp, "#374151"),
            "especialista_nome": especialistas.get(plano.especialista_id),
            "plano_id": plano.id,
            "tarefas": tarefas,
            "orientacoes_gerais": plano.orientacoes_gerais,
            "registros": [
                {
                    "tarefa_index": r.tarefa_index,
                    "concluiu": r.concluiu,
                    "humor": r.humor,
                    "observacao": r.observacao,
                }
                for r in registros
            ],
            "percentual_conclusao": percentual,
        }

    # Agrupa planos por (semana_inicio, semana_fim)
    semanas_map: dict[tuple, list] = {}
    for p in planos:
        chave = (p.semana_inicio, p.semana_fim)
        semanas_map.setdefault(chave, []).append(p)

    semanas_ordenadas = sorted(semanas_map.keys(), key=lambda x: x[0], reverse=True)

    # Determina semana atual: contém hoje, ou a mais recente
    hoje = date.today()
    chave_atual = next(
        (k for k in semanas_ordenadas if k[0] <= hoje <= k[1]),
        semanas_ordenadas[0],
    )
    inicio_atual, fim_atual = chave_atual

    por_especialidade = [_montar_grupo(p) for p in semanas_map[chave_atual]]

    semanas_anteriores = [
        {
            "semana": {"inicio": str(k[0]), "fim": str(k[1])},
            "por_especialidade": [_montar_grupo(p) for p in semanas_map[k]],
        }
        for k in semanas_ordenadas
        if k != chave_atual
    ]

    return {
        "semana_atual": {"inicio": str(inicio_atual), "fim": str(fim_atual)},
        "por_especialidade": por_especialidade,
        "semanas_anteriores": semanas_anteriores,
    }


# =========================================================
# POST /planos/{plano_id}/tarefas/{tarefa_index}/registrar
# =========================================================

class RegistroTarefaCreate(BaseModel):
    concluiu: bool
    humor: Optional[str] = None
    observacao: Optional[str] = None


@router.post("/planos/{plano_id}/tarefas/{tarefa_index}/registrar", status_code=201)
def registrar_tarefa(
    plano_id: int,
    tarefa_index: int,
    body: RegistroTarefaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)

    plano = session.get(PlanoSemanal, plano_id)
    if not plano:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")
    if not plano.enviado_familia:
        raise HTTPException(status_code=403, detail="Plano não disponível para a família.")

    # Verifica acesso via vínculo ativo
    vinculo = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.paciente_id == plano.paciente_id,
            VinculoEspecialistaFamilia.responsavel_id == current_user.id,
            VinculoEspecialistaFamilia.status == "ativo",
        )
    ).first()
    if not vinculo:
        raise HTTPException(status_code=403, detail="Acesso negado a este plano.")

    try:
        tarefas = json.loads(plano.tarefas)
    except (json.JSONDecodeError, TypeError):
        tarefas = []

    if tarefa_index < 0 or tarefa_index >= len(tarefas):
        raise HTTPException(status_code=422, detail="Índice de tarefa inválido.")

    # Upsert por (plano_id, tarefa_index, responsavel_id)
    registro = session.exec(
        select(RegistroPlanoFamilia).where(
            RegistroPlanoFamilia.plano_id == plano_id,
            RegistroPlanoFamilia.tarefa_index == tarefa_index,
            RegistroPlanoFamilia.responsavel_id == current_user.id,
        )
    ).first()

    if registro:
        registro.concluiu = body.concluiu
        registro.humor = body.humor
        registro.observacao = body.observacao
    else:
        registro = RegistroPlanoFamilia(
            plano_id=plano_id,
            paciente_id=plano.paciente_id,
            responsavel_id=current_user.id,
            tarefa_index=tarefa_index,
            concluiu=body.concluiu,
            humor=body.humor,
            observacao=body.observacao,
            especialidade=plano.especialidade,
        )

    session.add(registro)
    session.commit()
    session.refresh(registro)
    return registro


# =========================================================
# POST /vincular-especialista/ — aceitar convite
# =========================================================

class VincularEspecialistaRequest(BaseModel):
    codigo_convite: str
    filho_id: Optional[int] = None


# =========================================================
# Helper interno — ativa o vínculo e sincroniza o paciente
# =========================================================

def _ativar_vinculo(
    vinculo: VinculoEspecialistaFamilia,
    filho: FilhoPublico,
    paciente,
    current_user: Usuario,
    session: Session,
) -> dict:
    vinculo.filho_publico_id = filho.id
    vinculo.responsavel_id = current_user.id
    vinculo.status = "ativo"
    vinculo.aceito_em = datetime.utcnow()
    session.add(vinculo)

    if paciente:
        paciente.filho_publico_id = filho.id
        session.add(paciente)

    session.commit()
    session.refresh(vinculo)

    especialista = session.get(UsuarioModel, vinculo.especialista_id)
    return {
        "mensagem": "Vínculo criado com sucesso!",
        "especialista": especialista.nome if especialista else None,
        "paciente": paciente.nome if paciente else None,
    }


# =========================================================
# POST /vincular-especialista/ — iniciar vínculo via código
# =========================================================

@router.post("/vincular-especialista/", status_code=201)
def vincular_especialista(
    body: VincularEspecialistaRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)

    vinculo = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.codigo_convite == body.codigo_convite
        )
    ).first()

    if not vinculo:
        raise HTTPException(status_code=404, detail="Código inválido.")
    if vinculo.status != "pendente":
        raise HTTPException(status_code=400, detail="Código já utilizado.")

    paciente = session.get(PacienteClinico, vinculo.paciente_id)

    filhos = session.exec(
        select(FilhoPublico).where(FilhoPublico.responsavel_id == current_user.id)
    ).all()

    if not filhos:
        raise HTTPException(
            status_code=422,
            detail="Cadastre ao menos um filho antes de vincular um especialista.",
        )

    # filho_id fornecido → confirmar diretamente
    if body.filho_id is not None:
        filho = next((f for f in filhos if f.id == body.filho_id), None)
        if not filho:
            raise HTTPException(status_code=403, detail="Acesso negado a este filho.")
        return _ativar_vinculo(vinculo, filho, paciente, current_user, session)

    # filho único → vínculo automático
    if len(filhos) == 1:
        return _ativar_vinculo(vinculo, filhos[0], paciente, current_user, session)

    # múltiplos filhos → retorna lista para o frontend escolher
    return {
        "requer_selecao": True,
        "paciente": {
            "nome": paciente.nome if paciente else None,
            "condicao": paciente.condicao if paciente else None,
            "grau": paciente.grau if paciente else None,
        },
        "filhos_disponiveis": [
            {"id": f.id, "nome": f.nome, "condicao": f.condicao}
            for f in filhos
        ],
        "codigo_convite": body.codigo_convite,
    }


# =========================================================
# POST /vincular-especialista/confirmar/ — confirmar filho selecionado
# =========================================================

@router.post("/vincular-especialista/confirmar/", status_code=201)
def confirmar_vinculo(
    body: VincularEspecialistaRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)

    if body.filho_id is None:
        raise HTTPException(
            status_code=422,
            detail="filho_id é obrigatório para confirmar o vínculo.",
        )

    vinculo = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.codigo_convite == body.codigo_convite
        )
    ).first()

    if not vinculo:
        raise HTTPException(status_code=404, detail="Código inválido.")
    if vinculo.status != "pendente":
        raise HTTPException(status_code=400, detail="Código já utilizado.")

    filho = session.get(FilhoPublico, body.filho_id)
    if not filho or filho.responsavel_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado a este filho.")

    paciente = session.get(PacienteClinico, vinculo.paciente_id)
    return _ativar_vinculo(vinculo, filho, paciente, current_user, session)


# =========================================================
# GET /meus-especialistas/ — vínculos ativos da família
# =========================================================

@router.get("/meus-especialistas/")
def meus_especialistas(
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)

    vinculos = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.responsavel_id == current_user.id,
            VinculoEspecialistaFamilia.status == "ativo",
        )
    ).all()

    result = []
    for v in vinculos:
        especialista = session.get(UsuarioModel, v.especialista_id)
        paciente = session.get(PacienteClinico, v.paciente_id)
        result.append({
            "vinculo_id": v.id,
            "especialista_nome": especialista.nome if especialista else None,
            "paciente_nome": paciente.nome if paciente else None,
            "aceito_em": v.aceito_em,
        })
    return result


# =========================================================
# Schemas — Rotina Visual
# =========================================================

class ItemRotinaCreate(BaseModel):
    dia_semana: int
    periodo: str
    ordem: int
    titulo: str
    descricao: Optional[str] = None
    icone: Optional[str] = None
    duracao_minutos: Optional[int] = None


class RotinaCreate(BaseModel):
    semana_inicio: date
    semana_fim: date
    itens: list[ItemRotinaCreate]


class MudancaCreate(BaseModel):
    titulo: str
    descricao: Optional[str] = None
    data_inicio: date
    data_fim: Optional[date] = None
    tipo: str


class ImprevistoCreate(BaseModel):
    tipo: str
    descricao: str
    data: date


_DIA_LABEL = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo",
}


# =========================================================
# POST /filhos/{filho_id}/rotina/ — criar/substituir rotina
# =========================================================

@router.post("/filhos/{filho_id}/rotina/", status_code=201)
def criar_rotina(
    filho_id: int,
    body: RotinaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    # Desativa rotinas ativas anteriores
    rotinas_ativas = session.exec(
        select(RotinaSemanal).where(
            RotinaSemanal.filho_id == filho_id,
            RotinaSemanal.ativa == True,  # noqa: E712
        )
    ).all()
    for r in rotinas_ativas:
        r.ativa = False
        session.add(r)

    rotina = RotinaSemanal(
        filho_id=filho_id,
        responsavel_id=current_user.id,
        semana_inicio=body.semana_inicio,
        semana_fim=body.semana_fim,
    )
    session.add(rotina)
    session.flush()  # obtém rotina.id antes do commit

    itens = []
    for item_data in body.itens:
        item = ItemRotina(
            rotina_id=rotina.id,
            dia_semana=item_data.dia_semana,
            periodo=item_data.periodo,
            ordem=item_data.ordem,
            titulo=item_data.titulo,
            descricao=item_data.descricao,
            icone=item_data.icone,
            duracao_minutos=item_data.duracao_minutos,
        )
        session.add(item)
        itens.append(item)

    session.commit()
    session.refresh(rotina)
    for item in itens:
        session.refresh(item)

    return {"rotina": rotina, "itens": itens}


# =========================================================
# GET /filhos/{filho_id}/rotina/ — rotina ativa organizada
# =========================================================

@router.get("/filhos/{filho_id}/rotina/")
def buscar_rotina(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    rotina = session.exec(
        select(RotinaSemanal).where(
            RotinaSemanal.filho_id == filho_id,
            RotinaSemanal.ativa == True,  # noqa: E712
        )
    ).first()

    if not rotina:
        raise HTTPException(status_code=404, detail="Nenhuma rotina ativa encontrada.")

    itens = session.exec(
        select(ItemRotina).where(ItemRotina.rotina_id == rotina.id)
    ).all()

    dias: dict[str, dict] = {
        str(d): {"label": _DIA_LABEL[d], "manha": [], "tarde": [], "noite": []}
        for d in range(7)
    }

    for item in sorted(itens, key=lambda x: (x.dia_semana, x.ordem)):
        dia_key = str(item.dia_semana)
        if item.periodo in ("manha", "tarde", "noite"):
            dias[dia_key][item.periodo].append(item.model_dump())

    return {
        "rotina_id": rotina.id,
        "semana_inicio": str(rotina.semana_inicio),
        "semana_fim": str(rotina.semana_fim),
        "dias": dias,
    }


# =========================================================
# POST /filhos/{filho_id}/mudancas/ — registrar mudança + plano IA
# =========================================================

@router.post("/filhos/{filho_id}/mudancas/", status_code=201)
def criar_mudanca(
    filho_id: int,
    body: MudancaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    prompt = f"""Uma família com uma criança de {filho.idade or "?"} anos com {filho.condicao or "necessidade especial"} ({filho.grau_necessidade or "grau não informado"}) vai ter a seguinte mudança na rotina:

Mudança: {body.titulo}
Descrição: {body.descricao or "Não informada"}
Data: {body.data_inicio}
Tipo: {body.tipo}

Gere um plano de preparação gradual de 5 a 7 dias para preparar a criança para essa mudança.
Cada dia deve ter 1-2 orientações práticas simples para os pais implementarem.

Considere que crianças com {filho.condicao or "necessidade especial"} precisam de antecipação, rotina visual e preparação gradual.

Responda em JSON:
{{
    "dias_preparacao": [
        {{
            "dias_antes": 7,
            "titulo": "string",
            "orientacoes": ["string", "string"]
        }}
    ],
    "dicas_gerais": ["string"],
    "o_que_levar": ["string"]
}}"""

    plano_ia = _chamar_groq_json(prompt)
    plano_json = json.dumps(plano_ia, ensure_ascii=False) if plano_ia else None

    mudanca = MudancaRotina(
        filho_id=filho_id,
        responsavel_id=current_user.id,
        titulo=body.titulo,
        descricao=body.descricao,
        data_inicio=body.data_inicio,
        data_fim=body.data_fim,
        tipo=body.tipo,
        plano_preparacao=plano_json,
    )
    session.add(mudanca)
    session.commit()
    session.refresh(mudanca)

    return {
        **mudanca.model_dump(),
        "plano_preparacao": plano_ia,
    }


# =========================================================
# GET /filhos/{filho_id}/mudancas/ — listar mudanças
# =========================================================

@router.get("/filhos/{filho_id}/mudancas/")
def listar_mudancas(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    mudancas = session.exec(
        select(MudancaRotina)
        .where(MudancaRotina.filho_id == filho_id)
        .order_by(MudancaRotina.data_inicio.desc())  # type: ignore[attr-defined]
    ).all()

    return [
        {
            **m.model_dump(),
            "plano_preparacao": json.loads(m.plano_preparacao) if m.plano_preparacao else None,
        }
        for m in mudancas
    ]


# =========================================================
# POST /filhos/{filho_id}/imprevistos/ — registrar imprevisto + orientações IA
# =========================================================

@router.post("/filhos/{filho_id}/imprevistos/", status_code=201)
def criar_imprevisto(
    filho_id: int,
    body: ImprevistoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    print(f"Gerando orientações para imprevisto: {body.tipo}")
    print(f"Filho: {filho.nome}, {filho.condicao}")

    prompt = f"""Um pai registrou o seguinte imprevisto com seu filho de {filho.idade or "?"} anos com {filho.condicao or "necessidade especial"} ({filho.grau_necessidade or "grau não informado"}):

Tipo: {body.tipo}
Descrição: {body.descricao}

Gere orientações práticas e acolhedoras para o pai lidar com essa situação em casa hoje.

Responda em JSON:
{{
    "orientacoes_imediatas": ["string"],
    "o_que_evitar": ["string"],
    "quando_buscar_ajuda": "string",
    "mensagem_encorajamento": "string"
}}"""

    orientacoes_ia = _chamar_groq_json(prompt)
    print(f"orientacoes_ia retornado pelo Groq: {orientacoes_ia}")
    orientacoes_json = json.dumps(orientacoes_ia, ensure_ascii=False) if orientacoes_ia else None

    imprevisto = ImprevistoDia(
        filho_id=filho_id,
        responsavel_id=current_user.id,
        data=body.data,
        tipo=body.tipo,
        descricao=body.descricao,
        orientacoes_ia=orientacoes_json,
    )
    session.add(imprevisto)
    session.commit()
    session.refresh(imprevisto)

    return {
        **imprevisto.model_dump(),
        "orientacoes_ia": orientacoes_ia,
    }


# =========================================================
# GET /filhos/{filho_id}/imprevistos/ — últimos 30 dias
# =========================================================

@router.get("/filhos/{filho_id}/imprevistos/")
def listar_imprevistos(
    filho_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_familia(current_user)
    filho = session.get(FilhoPublico, filho_id)
    if not filho:
        raise HTTPException(status_code=404, detail="Filho não encontrado.")
    _verificar_dono_filho(filho, current_user)

    corte = date.today() - timedelta(days=30)
    imprevistos = session.exec(
        select(ImprevistoDia)
        .where(
            ImprevistoDia.filho_id == filho_id,
            ImprevistoDia.data >= corte,
        )
        .order_by(ImprevistoDia.data.desc())  # type: ignore[attr-defined]
    ).all()

    return [
        {
            **i.model_dump(),
            "orientacoes_ia": json.loads(i.orientacoes_ia) if i.orientacoes_ia else None,
        }
        for i in imprevistos
    ]
