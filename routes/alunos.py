# app/routes/alunos.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from typing import List
from app.models import Aluno
from app.database import get_session
from app import crud

router = APIRouter()

@router.get("/", response_model=List[Aluno], summary="Listar todos os alunos")
def listar_alunos(session: Session = Depends(get_session)):
    alunos = crud.get_alunos(session)
    return alunos


@router.get("/{aluno_id}", response_model=Aluno, summary="Buscar aluno por ID")
def buscar_aluno(aluno_id: int, session: Session = Depends(get_session)):
    aluno = crud.get_aluno_by_id(session, aluno_id)
    if not aluno:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aluno não encontrado.")
    return aluno


@router.post("/", response_model=Aluno, status_code=status.HTTP_201_CREATED, summary="Criar novo aluno")
def criar_aluno(aluno: Aluno, session: Session = Depends(get_session)):
    novo_aluno = crud.create_aluno(session, aluno)
    return novo_aluno


@router.put("/{aluno_id}", response_model=Aluno, summary="Atualizar aluno existente")
def atualizar_aluno(aluno_id: int, updates: dict, session: Session = Depends(get_session)):
    aluno_atualizado = crud.update_aluno(session, aluno_id, updates)
    if not aluno_atualizado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aluno não encontrado para atualização.")
    return aluno_atualizado


@router.delete("/{aluno_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir aluno")
def excluir_aluno(aluno_id: int, session: Session = Depends(get_session)):
    deletado = crud.delete_aluno(session, aluno_id)
    if not deletado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aluno não encontrado para exclusão.")
    return {"message": "Aluno removido com sucesso."}
