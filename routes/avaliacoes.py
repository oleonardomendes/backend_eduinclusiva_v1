# routes/avaliacoes.py
from collections import defaultdict
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import Avaliacao, Usuario
from app.database import get_session
from routes.auth import get_current_user

router = APIRouter()


# ========================
# Schemas
# ========================
class AvaliacaoCreate(BaseModel):
    aluno_id: int
    bimestre: int
    ano: int
    nota: float
    progresso: Optional[int] = None
    observacoes: Optional[str] = None


class AvaliacaoUpdate(BaseModel):
    bimestre: Optional[int] = None
    ano: Optional[int] = None
    nota: Optional[float] = None
    progresso: Optional[int] = None
    observacoes: Optional[str] = None


class ResumoBimestral(BaseModel):
    bimestre: int
    progresso_medio: int
    total_alunos: int


# =========================================================
# ➕ Criar avaliação
# =========================================================
@router.post("/", response_model=Avaliacao, status_code=status.HTTP_201_CREATED, summary="Criar avaliação")
def criar_avaliacao(
    body: AvaliacaoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    avaliacao = Avaliacao(**body.model_dump(), professor_id=current_user.id)
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# 📊 Resumo bimestral — declarado antes de /{id} para evitar conflito
# =========================================================
@router.get("/resumo/", response_model=List[ResumoBimestral], summary="Resumo bimestral de progresso")
def resumo_bimestral(
    ano: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    avaliacoes = session.exec(
        select(Avaliacao).where(
            Avaliacao.professor_id == current_user.id,
            Avaliacao.ano == ano,
            Avaliacao.progresso.is_not(None),  # type: ignore[attr-defined]
        )
    ).all()

    agrupado: dict[int, list[Avaliacao]] = defaultdict(list)
    for a in avaliacoes:
        agrupado[a.bimestre].append(a)

    return [
        ResumoBimestral(
            bimestre=bimestre,
            progresso_medio=int(sum(a.progresso for a in avs) / len(avs)),  # type: ignore[arg-type]
            total_alunos=len({a.aluno_id for a in avs}),
        )
        for bimestre, avs in sorted(agrupado.items())
    ]


# =========================================================
# 📋 Listar avaliações
# =========================================================
@router.get("/", response_model=List[Avaliacao], summary="Listar avaliações")
def listar_avaliacoes(
    aluno_id: Optional[int] = None,
    ano: Optional[int] = None,
    bimestre: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Avaliacao).where(Avaliacao.professor_id == current_user.id)
    if aluno_id is not None:
        query = query.where(Avaliacao.aluno_id == aluno_id)
    if ano is not None:
        query = query.where(Avaliacao.ano == ano)
    if bimestre is not None:
        query = query.where(Avaliacao.bimestre == bimestre)
    return session.exec(query).all()


# =========================================================
# ✏️ Atualizar avaliação
# =========================================================
@router.put("/{avaliacao_id}", response_model=Avaliacao, summary="Atualizar avaliação")
def atualizar_avaliacao(
    avaliacao_id: int,
    body: AvaliacaoUpdate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    avaliacao = session.get(Avaliacao, avaliacao_id)
    if not avaliacao:
        raise HTTPException(status_code=404, detail="Avaliação não encontrada.")
    if avaliacao.professor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(avaliacao, key, value)
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao
