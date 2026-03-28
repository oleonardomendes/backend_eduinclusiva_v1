# app/routes/planos.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from typing import List
from app.models import Plano
from app.database import get_session
from app import crud

router = APIRouter()

@router.get("/aluno/{aluno_id}", response_model=List[Plano], summary="Listar planos de um aluno")
def listar_planos_por_aluno(aluno_id: int, session: Session = Depends(get_session)):
    planos = crud.get_planos_by_aluno(session, aluno_id)
    return planos


@router.get("/{plano_id}", response_model=Plano, summary="Buscar plano por ID")
def buscar_plano(plano_id: int, session: Session = Depends(get_session)):
    plano = crud.get_plano_by_id(session, plano_id)
    if not plano:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano não encontrado.")
    return plano


@router.post("/", response_model=Plano, status_code=status.HTTP_201_CREATED, summary="Criar novo plano adaptado")
def criar_plano(plano: Plano, session: Session = Depends(get_session)):
    novo_plano = crud.create_plano(session, plano)
    return novo_plano


@router.put("/{plano_id}", response_model=Plano, summary="Atualizar plano existente")
def atualizar_plano(plano_id: int, updates: dict, session: Session = Depends(get_session)):
    plano_atualizado = crud.update_plano(session, plano_id, updates)
    if not plano_atualizado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano não encontrado para atualização.")
    return plano_atualizado


@router.delete("/{plano_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir plano")
def excluir_plano(plano_id: int, session: Session = Depends(get_session)):
    deletado = crud.delete_plano(session, plano_id)
    if not deletado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano não encontrado para exclusão.")
    return {"message": "Plano removido com sucesso."}
