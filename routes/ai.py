# routes/ai.py
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import Dict, List, Optional
from datetime import datetime
import json

from pydantic import BaseModel

from app.database import get_session
from app.schemas import PlanoGeradoIA, PlanoCreate, PlanoRead
from services.rag_service import gerar_plano_adaptado
from services.ai_service import buscar_ou_gerar_atividade
from app.crud import create_plano
from app.models import Plano, Aluno, AtividadeGerada, AtividadeTemplate, ConclusaoAtividade, FilhoPublico
from routes.auth import get_current_user

router = APIRouter()

ROLES_GESTAO = {"secretary", "secretaria", "coordinator", "coordenadora", "admin", "gestor"}


# =========================================================
# Helpers
# =========================================================

def _pode_ver_aluno(current_user, aluno: Aluno) -> bool:
    papel = (current_user.papel or "").lower()
    if papel in ROLES_GESTAO:
        return True
    return aluno.professor_id == current_user.id


def _desserializar_atividade(atividade: AtividadeGerada) -> dict:
    """Converte campos JSON string para listas/dict para o response."""
    d = atividade.model_dump()
    # Campos lista
    for campo in ("materiais", "passo_a_passo", "adaptacoes", "criterios_avaliacao", "tags"):
        valor = d.get(campo)
        if isinstance(valor, str):
            try:
                d[campo] = json.loads(valor)
            except (json.JSONDecodeError, TypeError):
                d[campo] = []
    # Campos dict
    for campo in ("parametros_professor",):
        valor = d.get(campo)
        if isinstance(valor, str):
            try:
                d[campo] = json.loads(valor)
            except (json.JSONDecodeError, TypeError):
                d[campo] = {}
    return d


# =========================================================
# Schemas
# =========================================================

class GerarAtividadeRequest(BaseModel):
    aluno_id: int
    titulo: Optional[str] = None
    disciplina: Optional[str] = None
    tipo_atividade: Optional[str] = None
    nivel_dificuldade: Optional[str] = None
    duracao_minutos: Optional[int] = 30
    descricao: Optional[str] = None
    objetivos: Optional[str] = None


class ConcluirAtividadeRequest(BaseModel):
    observacoes: Optional[str] = None
    competencias_trabalhadas: Optional[list] = None
    nota_comunicacao: Optional[float] = None
    nota_coordenacao_motora: Optional[float] = None
    nota_cognicao: Optional[float] = None
    nota_socializacao: Optional[float] = None
    nota_autonomia: Optional[float] = None
    nota_linguagem: Optional[float] = None


class AtividadeTemplateCreate(BaseModel):
    titulo: str
    descricao: Optional[str] = None
    disciplina: Optional[str] = None
    tipo_atividade: Optional[str] = None
    nivel_dificuldade: Optional[str] = None
    nivel_aprendizado: Optional[str] = None
    duracao_minutos: Optional[int] = None
    necessidades_alvo: Optional[List[str]] = None
    objetivo: Optional[str] = None
    instrucao_professor: Optional[str] = None
    instrucao_familia: Optional[str] = None
    conteudo_atividade: Optional[str] = None
    materiais: Optional[List[str]] = None
    passo_a_passo: Optional[List[str]] = None
    adaptacoes: Optional[List[str]] = None
    criterios_avaliacao: Optional[List[str]] = None
    tags: Optional[List[str]] = None


# =========================================================
# Planos (OpenAI / RAG — mantidos sem alteração)
# =========================================================

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
# Templates de atividade
# =========================================================

@router.get("/templates/", summary="Listar templates de atividade")
def listar_templates(
    necessidade: Optional[str] = None,
    nivel: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    templates = session.exec(
        select(AtividadeTemplate).where(AtividadeTemplate.ativo == True)  # noqa: E712
    ).all()

    resultado = []
    for t in templates:
        # Filtra por necessidade (campo é JSON list)
        if necessidade and t.necessidades_alvo:
            try:
                nees = json.loads(t.necessidades_alvo)
            except (json.JSONDecodeError, TypeError):
                nees = []
            if necessidade not in nees:
                continue

        # Filtra por nivel_dificuldade
        if nivel and t.nivel_dificuldade and t.nivel_dificuldade != nivel:
            continue

        resultado.append(t.model_dump())

    return resultado


@router.post("/templates/", summary="Criar template de atividade")
def criar_template(
    body: AtividadeTemplateCreate,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    def _ser(valor) -> Optional[str]:
        if valor is None:
            return None
        return json.dumps(valor, ensure_ascii=False)

    template = AtividadeTemplate(
        titulo=body.titulo,
        descricao=body.descricao,
        disciplina=body.disciplina,
        tipo_atividade=body.tipo_atividade,
        nivel_dificuldade=body.nivel_dificuldade,
        nivel_aprendizado=body.nivel_aprendizado,
        duracao_minutos=body.duracao_minutos,
        necessidades_alvo=_ser(body.necessidades_alvo),
        objetivo=body.objetivo,
        instrucao_professor=body.instrucao_professor,
        instrucao_familia=body.instrucao_familia,
        conteudo_atividade=body.conteudo_atividade,
        materiais=_ser(body.materiais),
        passo_a_passo=_ser(body.passo_a_passo),
        adaptacoes=_ser(body.adaptacoes),
        criterios_avaliacao=_ser(body.criterios_avaliacao),
        tags=_ser(body.tags),
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template.model_dump()


# =========================================================
# Geração de atividade adaptada (Groq — 3 camadas)
# =========================================================

@router.post("/gerar_atividade", summary="Gerar atividade adaptada via IA (3 camadas)")
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

    parametros = {
        "titulo": body.titulo,
        "disciplina": body.disciplina,
        "tipo_atividade": body.tipo_atividade,
        "nivel_dificuldade": body.nivel_dificuldade,
        "duracao_minutos": body.duracao_minutos,
        "descricao": body.descricao,
        "objetivos": body.objetivos,
    }

    try:
        resultado = buscar_ou_gerar_atividade(
            aluno_id=body.aluno_id,
            professor_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        print(f"Erro ao gerar atividade: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao gerar atividade.")

    # resultado["atividade"] já é um dict (model_dump do AtividadeGerada ou Template)
    atividade = resultado["atividade"]

    # Desserializar campos JSON lista/dict para o response
    for campo in ("materiais", "passo_a_passo", "adaptacoes", "criterios_avaliacao", "tags"):
        valor = atividade.get(campo)
        if isinstance(valor, str):
            try:
                atividade[campo] = json.loads(valor)
            except (json.JSONDecodeError, TypeError):
                atividade[campo] = []

    for campo in ("parametros_professor",):
        valor = atividade.get(campo)
        if isinstance(valor, str):
            try:
                atividade[campo] = json.loads(valor)
            except (json.JSONDecodeError, TypeError):
                atividade[campo] = {}

    return {"fonte": resultado["fonte"], "atividade": atividade}


# =========================================================
# Concluir atividade com avaliação por competências
# =========================================================

@router.patch("/atividades/{atividade_id}/concluir", summary="Concluir atividade e avaliar por competências")
def concluir_atividade(
    atividade_id: int,
    body: ConcluirAtividadeRequest,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    atividade = session.get(AtividadeGerada, atividade_id)
    if not atividade:
        raise HTTPException(status_code=404, detail="Atividade não encontrada.")

    papel = (current_user.papel or "").lower()
    aluno = None

    if papel == "familia":
        filho = session.exec(
            select(FilhoPublico).where(
                FilhoPublico.id == atividade.aluno_id,
                FilhoPublico.responsavel_id == current_user.id,
            )
        ).first()
        if not filho:
            raise HTTPException(status_code=403, detail="Acesso negado.")
    else:
        aluno = session.get(Aluno, atividade.aluno_id)
        if not aluno or not _pode_ver_aluno(current_user, aluno):
            raise HTTPException(status_code=403, detail="Acesso negado a esta atividade.")

    # Calcula nota_geral como média das competências preenchidas
    campos_nota = [
        body.nota_comunicacao,
        body.nota_coordenacao_motora,
        body.nota_cognicao,
        body.nota_socializacao,
        body.nota_autonomia,
        body.nota_linguagem,
    ]
    notas_preenchidas = [n for n in campos_nota if n is not None]
    nota_geral = round(sum(notas_preenchidas) / len(notas_preenchidas), 2) if notas_preenchidas else None

    # Cria o registro de conclusão
    conclusao = ConclusaoAtividade(
        atividade_id=atividade_id,
        aluno_id=atividade.aluno_id,
        professor_id=current_user.id,
        observacoes=body.observacoes,
        nota_comunicacao=body.nota_comunicacao,
        nota_coordenacao_motora=body.nota_coordenacao_motora,
        nota_cognicao=body.nota_cognicao,
        nota_socializacao=body.nota_socializacao,
        nota_autonomia=body.nota_autonomia,
        nota_linguagem=body.nota_linguagem,
        nota_geral=nota_geral,
        competencias_trabalhadas=(
            json.dumps(body.competencias_trabalhadas, ensure_ascii=False)
            if body.competencias_trabalhadas else None
        ),
    )
    session.add(conclusao)

    # Marca a atividade como concluída
    atividade.concluida = True
    atividade.concluida_em = datetime.utcnow()
    session.add(atividade)

    # Atualiza progresso_geral do aluno (não aplicável para usuários família)
    if aluno is not None:
        progresso_atual = aluno.progresso_geral or 0
        if nota_geral is not None:
            if nota_geral >= 7.0:
                aluno.progresso_geral = min(100, progresso_atual + 5)
            elif nota_geral >= 5.0:
                aluno.progresso_geral = min(100, progresso_atual + 2)
            # nota < 5.0 → não altera
        else:
            aluno.progresso_geral = min(100, progresso_atual + 1)
        session.add(aluno)

    session.commit()
    session.refresh(conclusao)
    session.refresh(atividade)
    if aluno is not None:
        session.refresh(aluno)

    # Desserializa competencias_trabalhadas para o response
    conclusao_dict = conclusao.model_dump()
    if isinstance(conclusao_dict.get("competencias_trabalhadas"), str):
        try:
            conclusao_dict["competencias_trabalhadas"] = json.loads(conclusao_dict["competencias_trabalhadas"])
        except (json.JSONDecodeError, TypeError):
            conclusao_dict["competencias_trabalhadas"] = []

    return {
        "conclusao": conclusao_dict,
        "atividade": _desserializar_atividade(atividade),
        "progresso_atualizado": aluno.progresso_geral,
    }


# =========================================================
# Histórico de atividades geradas por aluno
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


# =========================================================
# Conclusões de atividades por aluno
# =========================================================

@router.get("/atividades/{aluno_id}/conclusoes", summary="Listar conclusões de atividades de um aluno")
def listar_conclusoes(
    aluno_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user),
):
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    if not _pode_ver_aluno(current_user, aluno):
        raise HTTPException(status_code=403, detail="Acesso negado a este aluno.")

    conclusoes = session.exec(
        select(ConclusaoAtividade)
        .where(ConclusaoAtividade.aluno_id == aluno_id)
        .order_by(ConclusaoAtividade.concluido_em.desc())  # type: ignore[attr-defined]
    ).all()

    resultado = []
    for c in conclusoes:
        d = c.model_dump()
        if isinstance(d.get("competencias_trabalhadas"), str):
            try:
                d["competencias_trabalhadas"] = json.loads(d["competencias_trabalhadas"])
            except (json.JSONDecodeError, TypeError):
                d["competencias_trabalhadas"] = []
        resultado.append(d)

    return resultado
