# routes/metas.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import Meta, Usuario
from app.database import get_session
from routes.auth import get_current_user

router = APIRouter()


# ========================
# Schemas
# ========================
class MetaCreate(BaseModel):
    sala: Optional[str] = None
    bimestre: int
    ano: int
    meta_progresso: int
    descricao: Optional[str] = None


class MetaUpdate(BaseModel):
    sala: Optional[str] = None
    bimestre: Optional[int] = None
    ano: Optional[int] = None
    meta_progresso: Optional[int] = None
    descricao: Optional[str] = None


# =========================================================
# ➕ Criar meta
# =========================================================
@router.post("/", response_model=Meta, status_code=status.HTTP_201_CREATED, summary="Criar meta bimestral")
def criar_meta(
    body: MetaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    meta = Meta(**body.model_dump(), professor_id=current_user.id)
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


# =========================================================
# 📋 Listar metas do professor logado
# =========================================================
@router.get("/", response_model=List[Meta], summary="Listar metas")
def listar_metas(
    ano: Optional[int] = None,
    bimestre: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Meta).where(Meta.professor_id == current_user.id)
    if ano is not None:
        query = query.where(Meta.ano == ano)
    if bimestre is not None:
        query = query.where(Meta.bimestre == bimestre)
    return session.exec(query).all()


# =========================================================
# ✏️ Atualizar meta
# =========================================================
@router.put("/{meta_id}", response_model=Meta, summary="Atualizar meta")
def atualizar_meta(
    meta_id: int,
    body: MetaUpdate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    meta = session.get(Meta, meta_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Meta não encontrada.")
    if meta.professor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(meta, key, value)
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


# =========================================================
# 🗑️ Remover meta
# =========================================================
@router.delete("/{meta_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover meta")
def remover_meta(
    meta_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    meta = session.get(Meta, meta_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Meta não encontrada.")
    if meta.professor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    session.delete(meta)
    session.commit()
