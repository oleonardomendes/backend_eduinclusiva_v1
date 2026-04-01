# routes/alunos.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from typing import List, Optional

from app.models import Aluno, Usuario
from app.database import get_session
from app import crud
from app.schemas import AlunoUpdate
from routes.auth import get_current_user  # reutiliza o guard de auth

router = APIRouter()

ROLES_GESTAO = {"secretary", "secretaria", "coordinator", "coordenadora", "admin", "gestor"}


def _pode_ver_aluno(current_user: Usuario, aluno: Aluno) -> bool:
    """Verifica se o usuário tem permissão para acessar este aluno."""
    papel = (current_user.papel or "").lower()
    if papel in ROLES_GESTAO:
        return True  # gestor/secretário vê todos
    return aluno.professor_id == current_user.id  # professor só vê os seus


# =========================================================
# 📋 Listar alunos
# =========================================================
@router.get("/", response_model=List[Aluno], summary="Listar alunos")
def listar_alunos(
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    """
    - Professor: retorna apenas seus próprios alunos.
    - Coordenador / Secretário / Admin: retorna todos.
    """
    papel = (current_user.papel or "").lower()
    if papel in ROLES_GESTAO:
        return crud.get_alunos(session)  # todos
    return crud.get_alunos(session, professor_id=current_user.id)  # só os seus


# =========================================================
# 🔍 Buscar aluno por ID
# =========================================================
@router.get("/{aluno_id}", response_model=Aluno, summary="Buscar aluno por ID")
def buscar_aluno(
    aluno_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    aluno = crud.get_aluno_by_id(session, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")
    return aluno


# =========================================================
# ➕ Criar aluno
# =========================================================
@router.post("/", response_model=Aluno, status_code=status.HTTP_201_CREATED, summary="Criar novo aluno")
def criar_aluno(
    aluno_data: Aluno,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    """
    O professor_id é sempre definido como o usuário autenticado,
    exceto para gestores que podem informar outro professor_id.
    """
    papel = (current_user.papel or "").lower()
    if papel not in ROLES_GESTAO:
        # Professor sempre cria aluno vinculado a si mesmo
        aluno_data.professor_id = current_user.id
    elif not aluno_data.professor_id:
        # Gestor criando aluno sem professor definido → vincula a si mesmo
        aluno_data.professor_id = current_user.id

    return crud.create_aluno(session, aluno_data)


# =========================================================
# ✏️ Atualizar aluno
# =========================================================
@router.put("/{aluno_id}", response_model=Aluno, summary="Atualizar aluno")
def atualizar_aluno(
    aluno_id: int,
    updates: AlunoUpdate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    aluno = crud.get_aluno_by_id(session, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")

    atualizado = crud.update_aluno(session, aluno_id, updates.model_dump(exclude_unset=True))
    return atualizado


# =========================================================
# 🗑️ Deletar aluno
# =========================================================
@router.delete("/{aluno_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir aluno")
def excluir_aluno(
    aluno_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    aluno = crud.get_aluno_by_id(session, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")

    crud.delete_aluno(session, aluno_id)
