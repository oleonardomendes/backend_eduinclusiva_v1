# app/crud.py
from typing import List, Optional
from sqlmodel import Session, select
from sqlalchemy.exc import SQLAlchemyError
from app.models import Aluno, Plano
import logging

logger = logging.getLogger("uvicorn")

# =========================================================
# 🧩 CRUD DE ALUNOS
# =========================================================

def get_alunos(session: Session) -> List[Aluno]:
    """
    Retorna todos os alunos cadastrados.
    """
    try:
        return session.exec(select(Aluno)).all()
    except SQLAlchemyError as e:
        logger.error(f"Erro ao buscar alunos: {e}")
        raise


def get_aluno_by_id(session: Session, aluno_id: int) -> Optional[Aluno]:
    """
    Busca um aluno pelo ID.
    """
    try:
        return session.get(Aluno, aluno_id)
    except SQLAlchemyError as e:
        logger.error(f"Erro ao buscar aluno {aluno_id}: {e}")
        raise


def create_aluno(session: Session, aluno: Aluno) -> Aluno:
    """
    Cria um novo aluno no banco de dados.
    """
    try:
        session.add(aluno)
        session.commit()
        session.refresh(aluno)
        logger.info(f"Aluno criado com sucesso: {aluno.nome} (ID: {aluno.id})")
        return aluno
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao criar aluno: {e}")
        raise


def update_aluno(session: Session, aluno_id: int, updates: dict) -> Optional[Aluno]:
    """
    Atualiza informações de um aluno existente.
    """
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        return None

    for key, value in updates.items():
        if hasattr(aluno, key):
            setattr(aluno, key, value)

    try:
        session.add(aluno)
        session.commit()
        session.refresh(aluno)
        logger.info(f"Aluno atualizado: {aluno.nome} (ID: {aluno.id})")
        return aluno
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao atualizar aluno {aluno_id}: {e}")
        raise


def delete_aluno(session: Session, aluno_id: int) -> bool:
    """
    Remove um aluno pelo ID.
    """
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        return False

    try:
        session.delete(aluno)
        session.commit()
        logger.info(f"Aluno removido: ID {aluno_id}")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao deletar aluno {aluno_id}: {e}")
        raise


# =========================================================
# 📘 CRUD DE PLANOS
# =========================================================

def get_planos_by_aluno(session: Session, aluno_id: int) -> List[Plano]:
    """
    Retorna todos os planos de ensino de um aluno específico.
    """
    try:
        return session.exec(select(Plano).where(Plano.aluno_id == aluno_id)).all()
    except SQLAlchemyError as e:
        logger.error(f"Erro ao buscar planos do aluno {aluno_id}: {e}")
        raise


def get_plano_by_id(session: Session, plano_id: int) -> Optional[Plano]:
    """
    Retorna um plano de ensino pelo ID.
    """
    try:
        return session.get(Plano, plano_id)
    except SQLAlchemyError as e:
        logger.error(f"Erro ao buscar plano {plano_id}: {e}")
        raise


def create_plano(session: Session, plano: Plano) -> Plano:
    """
    Cria um novo plano de ensino adaptado.
    """
    try:
        session.add(plano)
        session.commit()
        session.refresh(plano)
        logger.info(f"Plano criado com sucesso: {plano.titulo} (ID: {plano.id})")
        return plano
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao criar plano: {e}")
        raise


def update_plano(session: Session, plano_id: int, updates: dict) -> Optional[Plano]:
    """
    Atualiza campos de um plano existente.
    """
    plano = session.get(Plano, plano_id)
    if not plano:
        return None

    for key, value in updates.items():
        if hasattr(plano, key):
            setattr(plano, key, value)

    try:
        session.add(plano)
        session.commit()
        session.refresh(plano)
        logger.info(f"Plano atualizado: {plano.titulo} (ID: {plano.id})")
        return plano
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao atualizar plano {plano_id}: {e}")
        raise


def delete_plano(session: Session, plano_id: int) -> bool:
    """
    Remove um plano do banco de dados.
    """
    plano = session.get(Plano, plano_id)
    if not plano:
        return False

    try:
        session.delete(plano)
        session.commit()
        logger.info(f"Plano removido: ID {plano_id}")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Erro ao deletar plano {plano_id}: {e}")
        raise
