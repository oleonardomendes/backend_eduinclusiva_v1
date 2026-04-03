from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import Dict, List
from datetime import datetime
import json

from pydantic import BaseModel

from app.database import get_session
from app.schemas import PlanoGeradoIA, PlanoCreate, PlanoRead
from services.rag_service import gerar_plano_adaptado
from services.ai_service import gerar_atividade_adaptada
from app.crud import create_plano
from app.models import Plano, Aluno, AtividadeGerada
from routes.auth import get_current_user

router = APIRouter()

ROLES_GESTAO = {"secretary", "secretaria", "coordinator", "coordenadora", "admin", "gestor"}


def _pode_ver_aluno(current_user, aluno: Aluno) -> bool:
    papel = (current_user.papel or "").lower()
    if papel in ROLES_GESTAO:
        return True
    return aluno.professor_id == current_user.id


def _desserializar_atividade(atividade: AtividadeGerada) -> dict:
    """Converte campos JSON string para listas para o response."""
    d = atividade.model_dump()
    for campo in ("materiais", "passo_a_passo", "adaptacoes", "criterios_avaliacao"):
        valor = d.get(campo)
        if isinstance(valor, str):
            try:
                d[campo] = json.loads(valor)
            except (json.JSONDecodeError, TypeError):
                d[campo] = []
    return d


class GerarAtividadeRequest(BaseModel):
    aluno_id: int


@router.post("/gerar_plano", response_model=PlanoGeradoIA)
async def gerar_plano_ia(
    payload: Dict,
    session: Session = Depends(get_session),
):
    """
    Endpoint para gerar plano adaptado via IA.

    Exemplo de entrada (JSON):
    {
        "aluno_id": 1,
        "descricao_aluno": "Criança de 9 anos com dislexia leve",
        "conteudo": "Leitura de textos narrativos",
        "materia": "Português",
        "competencia": "Leitura e interpretação de textos"
    }
    """
    aluno_id = payload.get("aluno_id")
    descricao_aluno = payload.get("descricao_aluno")
    conteudo = payload.get("conteudo")
    materia = payload.get("materia")
    competencia = payload.get("competencia")

    if not aluno_id or not descricao_aluno or not conteudo:
        raise HTTPException(
            status_code=400,
            detail="Campos obrigatórios ausentes (aluno_id, descricao_aluno, conteudo)."
        )

    try:
        plano_data = await gerar_plano_adaptado(
            aluno_id=aluno_id,
            descricao_aluno=descricao_aluno,
            conteudo=conteudo,
            materia=materia,
            competencia=competencia,
        )

        titulo = plano_data.get("titulo", f"Plano adaptado - {conteudo}")
        atividades = plano_data.get("atividades", [])
        recomendacoes = plano_data.get("recomendacoes", [])

        plano_db = PlanoCreate(
            aluno_id=aluno_id,
            titulo=titulo,
            atividades=json.dumps(atividades, ensure_ascii=False),
            recomendacoes=json.dumps(recomendacoes, ensure_ascii=False),
        )

        create_plano(session, plano_db)

        return PlanoGeradoIA(
            titulo=titulo,
            atividades=atividades,
            recomendacoes=recomendacoes,
        )

    except Exception as e:
        print(f"Erro ao gerar plano via IA: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao gerar plano"
        )


@router.get("/historico/{aluno_id}", response_model=list[PlanoRead])
def listar_planos_gerados_por_aluno(
    aluno_id: int,
    session: Session = Depends(get_session)
):
    """
    Retorna o histórico de planos (incluindo os gerados por IA)
    vinculados a um aluno específico.

    Exemplo:
    GET /v1/ai/historico/1
    """
    try:
        statement = (
            select(Plano)
            .where(Plano.aluno_id == aluno_id)
            .order_by(Plano.criado_em)
        )

        planos = session.exec(statement).all()

        if not planos:
            raise HTTPException(
                status_code=404,
                detail="Nenhum plano encontrado para este aluno."
            )

        for plano in planos:
            if isinstance(plano.atividades, str):
                plano.atividades = json.loads(plano.atividades)
            if isinstance(plano.recomendacoes, str):
                plano.recomendacoes = json.loads(plano.recomendacoes)

        return planos

    except HTTPException:
        raise
    except Exception as e:
        print(f"Erro ao buscar histórico de planos: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao buscar histórico de planos."
        )


# =========================================================
# 🤖 Gerar atividade adaptada via Gemini
# =========================================================
@router.post("/gerar_atividade", summary="Gerar atividade adaptada via Gemini")
def gerar_atividade(
    body: GerarAtividadeRequest,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    aluno = session.get(Aluno, body.aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")

    try:
        atividade_dict = gerar_atividade_adaptada(body.aluno_id, current_user.id, session)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        print(f"Erro ao gerar atividade via Gemini: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao gerar atividade.")

    now = datetime.now()
    bimestre = (now.month - 1) // 3 + 1

    atividade = AtividadeGerada(
        aluno_id=body.aluno_id,
        professor_id=current_user.id,
        titulo=atividade_dict["titulo"],
        objetivo=atividade_dict.get("objetivo"),
        duracao_minutos=atividade_dict.get("duracao_minutos"),
        dificuldade=atividade_dict.get("dificuldade"),
        materiais=json.dumps(atividade_dict.get("materiais", []), ensure_ascii=False),
        passo_a_passo=json.dumps(atividade_dict.get("passo_a_passo", []), ensure_ascii=False),
        adaptacoes=json.dumps(atividade_dict.get("adaptacoes", []), ensure_ascii=False),
        criterios_avaliacao=json.dumps(atividade_dict.get("criterios_avaliacao", []), ensure_ascii=False),
        justificativa=atividade_dict.get("justificativa"),
        bimestre=bimestre,
        ano=now.year,
    )
    session.add(atividade)
    session.commit()
    session.refresh(atividade)

    return _desserializar_atividade(atividade)


# =========================================================
# 📋 Histórico de atividades geradas por aluno
# =========================================================
@router.get("/atividades/{aluno_id}", summary="Listar atividades geradas para um aluno")
def listar_atividades(
    aluno_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")

    atividades = session.exec(
        select(AtividadeGerada)
        .where(AtividadeGerada.aluno_id == aluno_id)
        .order_by(AtividadeGerada.criado_em.desc())  # type: ignore[attr-defined]
    ).all()

    return [_desserializar_atividade(a) for a in atividades]