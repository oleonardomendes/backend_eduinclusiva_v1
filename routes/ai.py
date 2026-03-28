from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import Dict, List
import json

from app.database import get_session
from app.schemas import PlanoGeradoIA, PlanoCreate, PlanoRead
from app.services.rag_service import gerar_plano_adaptado
from app.crud import create_plano
from app.models import Plano  # ✅ ajuste conforme seu models.py

router = APIRouter()


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


@router.get("/historico/{aluno_id}", response_model=List[PlanoRead])
def listar_planos_gerados_por_aluno(
    aluno_id: int,
    session: Session = Depends(get_session),
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