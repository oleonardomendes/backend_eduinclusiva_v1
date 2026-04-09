# routes/familia.py
"""
Portal da Família — endpoints para responsáveis acompanharem e estimularem
seus filhos com necessidades especiais em casa.
"""
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import FilhoPublico, AtividadeFamilia
from routes.auth import get_current_user, Usuario
from services.ai_service import analisar_estilo_aprendizagem, gerar_atividade_familia

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
        analise = analisar_estilo_aprendizagem(
            respostas=body.respostas,
            condicao=body.condicao,
            idade=body.idade,
            grau=body.grau,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na análise de IA: {str(e)}")

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
        select(AtividadeFamilia)
        .where(AtividadeFamilia.filho_id == filho_id)
        .order_by(AtividadeFamilia.criado_em.desc())  # type: ignore[attr-defined]
    ).all()

    return atividades
