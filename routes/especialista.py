# routes/especialista.py
"""
Módulo Clínico — endpoints para especialistas (psicopedagogos,
fonoaudiólogos, terapeutas ocupacionais, psicólogos, etc.)
gerenciarem pacientes, sessões e planos semanais.
"""
import os
import json
import logging
import secrets
import string
from typing import Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException
from groq import Groq
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    PacienteClinico,
    SessaoClinica,
    PlanoSemanal,
    RegistroPlanoFamilia,
    VinculoEspecialistaFamilia,
    AvaliacaoPsicomotricidade,
    FilhoPublico,
    Aluno,
    Usuario as UsuarioModel,
)
from routes.auth import get_current_user, Usuario
from services.ai_service import buscar_ou_gerar_atividade, _limpar_json_resposta, gerar_atividade_clinica

router = APIRouter()
logger = logging.getLogger("uvicorn")

PAPEIS_ESPECIALISTA = {"especialista", "professor"}


# =========================================================
# Guards
# =========================================================

def _verificar_especialista(current_user: Usuario) -> None:
    papel = (current_user.papel or "").lower()
    if papel not in PAPEIS_ESPECIALISTA:
        raise HTTPException(
            status_code=403,
            detail="Apenas especialistas podem acessar este recurso.",
        )


def _verificar_acesso_paciente(
    paciente_id: int,
    current_user: Usuario,
    session: Session,
) -> PacienteClinico:
    paciente = session.get(PacienteClinico, paciente_id)
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    if paciente.especialista_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return paciente


# =========================================================
# Schemas inline
# =========================================================

class PacienteCreate(BaseModel):
    nome: str
    filho_publico_id: Optional[int] = None
    data_nascimento: Optional[date] = None
    idade: Optional[int] = None
    condicao: Optional[str] = None
    grau: Optional[str] = None
    estilo_aprendizagem: Optional[str] = None
    e_verbal: Optional[bool] = None
    usa_comunicacao_alternativa: Optional[bool] = None
    observacoes: Optional[str] = None
    escola: Optional[str] = None
    serie: Optional[str] = None
    responsavel_nome: Optional[str] = None
    responsavel_telefone: Optional[str] = None
    responsavel_email: Optional[str] = None
    terapias_em_andamento: Optional[list] = None
    usa_aba: bool = False
    medicamentos: Optional[str] = None


class PacienteUpdate(BaseModel):
    nome: Optional[str] = None
    data_nascimento: Optional[date] = None
    idade: Optional[int] = None
    condicao: Optional[str] = None
    grau: Optional[str] = None
    estilo_aprendizagem: Optional[str] = None
    e_verbal: Optional[bool] = None
    usa_comunicacao_alternativa: Optional[bool] = None
    observacoes: Optional[str] = None
    escola: Optional[str] = None
    serie: Optional[str] = None
    responsavel_nome: Optional[str] = None
    responsavel_telefone: Optional[str] = None
    responsavel_email: Optional[str] = None
    terapias_em_andamento: Optional[list] = None
    usa_aba: Optional[bool] = None
    medicamentos: Optional[str] = None
    ativo: Optional[bool] = None


class SessaoCreate(BaseModel):
    especialidade: str
    data_sessao: date
    duracao_minutos: Optional[int] = None
    humor_inicio: Optional[str] = None
    atividades_realizadas: Optional[str] = None
    resposta_crianca: Optional[str] = None
    o_que_funcionou: Optional[str] = None
    o_que_nao_funcionou: Optional[str] = None
    observacoes_clinicas: Optional[str] = None
    proxima_sessao_foco: Optional[str] = None
    habilidades_trabalhadas: Optional[list] = None
    nivel_leitura: Optional[str] = None
    nivel_escrita: Optional[str] = None
    nivel_matematica: Optional[str] = None
    coordenacao_fina: Optional[str] = None
    coordenacao_grossa: Optional[str] = None
    equilibrio: Optional[str] = None
    lateralidade: Optional[str] = None
    esquema_corporal: Optional[str] = None


class TarefaItem(BaseModel):
    titulo: str
    descricao: Optional[str] = None
    duracao_minutos: int = 20
    area: Optional[str] = None


class PlanoCreate(BaseModel):
    semana_inicio: date
    semana_fim: date
    tarefas: list[TarefaItem]
    orientacoes_gerais: Optional[str] = None
    sessao_id: Optional[int] = None
    gerar_atividade_ia: bool = False


class RegistroTarefaCreate(BaseModel):
    concluiu: bool
    humor: Optional[str] = None
    observacao: Optional[str] = None


# =========================================================
# POST /pacientes/ — criar paciente
# =========================================================

@router.post("/pacientes/", status_code=201)
def criar_paciente(
    dados: PacienteCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)

    # Copia dados do FilhoPublico se vinculado
    nome = dados.nome
    idade = dados.idade
    condicao = dados.condicao
    grau = dados.grau
    estilo = dados.estilo_aprendizagem

    if dados.filho_publico_id:
        filho = session.get(FilhoPublico, dados.filho_publico_id)
        if not filho:
            raise HTTPException(status_code=404, detail="FilhoPublico não encontrado.")
        nome = nome or filho.nome
        idade = idade or filho.idade
        condicao = condicao or filho.condicao
        grau = grau or filho.grau_necessidade
        estilo = estilo or filho.estilo_aprendizagem

    terapias_json = (
        json.dumps(dados.terapias_em_andamento, ensure_ascii=False)
        if dados.terapias_em_andamento else None
    )

    paciente = PacienteClinico(
        especialista_id=current_user.id,
        filho_publico_id=dados.filho_publico_id,
        nome=nome,
        data_nascimento=dados.data_nascimento,
        idade=idade,
        condicao=condicao,
        grau=grau,
        estilo_aprendizagem=estilo,
        e_verbal=dados.e_verbal,
        usa_comunicacao_alternativa=dados.usa_comunicacao_alternativa,
        observacoes=dados.observacoes,
        escola=dados.escola,
        serie=dados.serie,
        responsavel_nome=dados.responsavel_nome,
        responsavel_telefone=dados.responsavel_telefone,
        responsavel_email=dados.responsavel_email,
        terapias_em_andamento=terapias_json,
        usa_aba=dados.usa_aba,
        medicamentos=dados.medicamentos,
    )
    session.add(paciente)
    session.commit()
    session.refresh(paciente)
    return paciente


# =========================================================
# GET /pacientes/ — listar pacientes
# =========================================================

@router.get("/pacientes/")
def listar_pacientes(
    ativo: Optional[bool] = None,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    query = select(PacienteClinico).where(
        PacienteClinico.especialista_id == current_user.id
    )
    if ativo is not None:
        query = query.where(PacienteClinico.ativo == ativo)
    query = query.order_by(PacienteClinico.nome)  # type: ignore[attr-defined]
    return session.exec(query).all()


# =========================================================
# GET /pacientes/{id} — detalhe do paciente
# =========================================================

@router.get("/pacientes/{paciente_id}")
def obter_paciente(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    return _verificar_acesso_paciente(paciente_id, current_user, session)


# =========================================================
# PUT /pacientes/{id} — atualizar paciente
# =========================================================

@router.put("/pacientes/{paciente_id}")
def atualizar_paciente(
    paciente_id: int,
    dados: PacienteUpdate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    updates = dados.model_dump(exclude_unset=True)
    if "terapias_em_andamento" in updates and isinstance(updates["terapias_em_andamento"], list):
        updates["terapias_em_andamento"] = json.dumps(
            updates["terapias_em_andamento"], ensure_ascii=False
        )

    for campo, valor in updates.items():
        setattr(paciente, campo, valor)

    session.add(paciente)
    session.commit()
    session.refresh(paciente)
    return paciente


# =========================================================
# POST /pacientes/{id}/sessoes/ — criar sessão
# =========================================================

@router.post("/pacientes/{paciente_id}/sessoes/", status_code=201)
def criar_sessao(
    paciente_id: int,
    dados: SessaoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    habilidades_json = (
        json.dumps(dados.habilidades_trabalhadas, ensure_ascii=False)
        if dados.habilidades_trabalhadas else None
    )

    sessao = SessaoClinica(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        especialidade=dados.especialidade,
        data_sessao=dados.data_sessao,
        duracao_minutos=dados.duracao_minutos,
        humor_inicio=dados.humor_inicio,
        atividades_realizadas=dados.atividades_realizadas,
        resposta_crianca=dados.resposta_crianca,
        o_que_funcionou=dados.o_que_funcionou,
        o_que_nao_funcionou=dados.o_que_nao_funcionou,
        observacoes_clinicas=dados.observacoes_clinicas,
        proxima_sessao_foco=dados.proxima_sessao_foco,
        habilidades_trabalhadas=habilidades_json,
        nivel_leitura=dados.nivel_leitura,
        nivel_escrita=dados.nivel_escrita,
        nivel_matematica=dados.nivel_matematica,
        coordenacao_fina=dados.coordenacao_fina,
        coordenacao_grossa=dados.coordenacao_grossa,
        equilibrio=dados.equilibrio,
        lateralidade=dados.lateralidade,
        esquema_corporal=dados.esquema_corporal,
    )
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


# =========================================================
# GET /pacientes/{id}/sessoes/ — listar sessões
# =========================================================

@router.get("/pacientes/{paciente_id}/sessoes/")
def listar_sessoes(
    paciente_id: int,
    especialidade: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    query = (
        select(SessaoClinica)
        .where(SessaoClinica.paciente_id == paciente_id)
        .order_by(SessaoClinica.data_sessao.desc())  # type: ignore[attr-defined]
    )
    if especialidade:
        query = query.where(SessaoClinica.especialidade == especialidade)
    return session.exec(query).all()


# =========================================================
# GET /sessoes/{id} — detalhe da sessão
# =========================================================

@router.get("/sessoes/{sessao_id}")
def obter_sessao(
    sessao_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    sessao = session.get(SessaoClinica, sessao_id)
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    if sessao.especialista_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return sessao


# =========================================================
# POST /pacientes/{id}/planos/ — criar plano semanal
# =========================================================

@router.post("/pacientes/{paciente_id}/planos/", status_code=201)
def criar_plano(
    paciente_id: int,
    dados: PlanoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    tarefas_json = json.dumps(
        [t.model_dump() for t in dados.tarefas], ensure_ascii=False
    )

    atividade_ia_id = None
    if dados.gerar_atividade_ia and dados.tarefas:
        primeira = dados.tarefas[0]
        parametros = {
            "titulo": primeira.titulo,
            "disciplina": primeira.area or "Geral",
            "descricao": primeira.descricao or "",
            "duracao_minutos": primeira.duracao_minutos,
        }
        # Usa aluno_id do paciente (pode ser FilhoPublico.id ou Aluno.id)
        aluno_id = paciente.filho_publico_id or paciente_id
        try:
            resultado = buscar_ou_gerar_atividade(
                aluno_id=aluno_id,
                professor_id=current_user.id,
                parametros=parametros,
                session=session,
            )
            atividade_ia_id = resultado["atividade"].get("id")
        except Exception as e:
            logger.warning(f"Falha ao gerar atividade IA para plano: {e}")

    plano = PlanoSemanal(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        sessao_id=dados.sessao_id,
        semana_inicio=dados.semana_inicio,
        semana_fim=dados.semana_fim,
        tarefas=tarefas_json,
        orientacoes_gerais=dados.orientacoes_gerais,
        atividade_ia_id=atividade_ia_id,
    )
    session.add(plano)
    session.commit()
    session.refresh(plano)

    return {
        **plano.model_dump(),
        "tarefas": dados.tarefas,
        "atividade_ia_gerada": atividade_ia_id is not None,
    }


# =========================================================
# GET /pacientes/{id}/planos/ — listar planos
# =========================================================

@router.get("/pacientes/{paciente_id}/planos/")
def listar_planos(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    planos = session.exec(
        select(PlanoSemanal)
        .where(PlanoSemanal.paciente_id == paciente_id)
        .order_by(PlanoSemanal.semana_inicio.desc())  # type: ignore[attr-defined]
    ).all()

    result = []
    for p in planos:
        d = p.model_dump()
        try:
            d["tarefas"] = json.loads(p.tarefas)
        except (json.JSONDecodeError, TypeError):
            d["tarefas"] = []
        result.append(d)
    return result


# =========================================================
# POST /planos/{id}/enviar-familia — marcar como enviado
# =========================================================

@router.post("/planos/{plano_id}/enviar-familia")
def enviar_plano_familia(
    plano_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    plano = session.get(PlanoSemanal, plano_id)
    if not plano:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")
    if plano.especialista_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    plano.enviado_familia = True
    plano.enviado_em = datetime.utcnow()
    session.add(plano)
    session.commit()
    session.refresh(plano)
    return {"mensagem": "Plano enviado para a família.", "enviado_em": plano.enviado_em}


# =========================================================
# GET /pacientes/{id}/evolucao/ — relatório evolutivo via IA
# =========================================================

@router.get("/pacientes/{paciente_id}/evolucao/")
def evolucao_paciente(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    sessoes = session.exec(
        select(SessaoClinica)
        .where(SessaoClinica.paciente_id == paciente_id)
        .order_by(SessaoClinica.data_sessao.desc())  # type: ignore[attr-defined]
        .limit(10)
    ).all()

    relatorio_ia = None
    if sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao} ({s.especialidade}): "
            f"funcionou={s.o_que_funcionou or 'não registrado'}, "
            f"atenção={s.o_que_nao_funcionou or 'não registrado'}, "
            f"foco próxima={s.proxima_sessao_foco or 'não registrado'}"
            for s in sessoes
        )

        prompt = f"""Analise as sessões clínicas de {paciente.nome} ({paciente.condicao or "necessidade especial"}, {paciente.idade or "?"} anos):

Últimas {len(sessoes)} sessões:
{resumo_sessoes}

Gere um relatório evolutivo breve com:
1. Pontos de progresso observados
2. Áreas que precisam de atenção
3. Sugestões para as próximas sessões
4. Orientações para a família

Responda em JSON:
{{"progresso": ["string"], "atencao": ["string"], "sugestoes_sessao": ["string"], "orientacoes_familia": ["string"], "resumo_geral": "string"}}"""

        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            try:
                client = Groq(api_key=api_key)
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                )
                raw = _limpar_json_resposta(response.choices[0].message.content)
                relatorio_ia = json.loads(raw)
            except Exception as e:
                logger.error(f"Groq evolução clínica: {e}")

    return {
        "paciente": paciente,
        "total_sessoes": len(sessoes),
        "ultimas_sessoes": [s.model_dump() for s in sessoes],
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/gerar-convite
# =========================================================

@router.post("/pacientes/{paciente_id}/gerar-convite", status_code=201)
def gerar_convite(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    codigo = "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8)
    )

    vinculo = VinculoEspecialistaFamilia(
        especialista_id=current_user.id,
        paciente_id=paciente_id,
        codigo_convite=codigo,
        status="pendente",
    )
    session.add(vinculo)
    session.commit()
    session.refresh(vinculo)

    _FRONTEND_URL = "https://edumaisinclusiva.com.br"
    return {
        "codigo_convite": codigo,
        "link_convite": f"{_FRONTEND_URL}/cadastro?tipo=familia&convite={codigo}",
        "instrucoes": (
            "Compartilhe este link com a família do paciente. "
            "Ao clicar, eles serão direcionados para criar a conta "
            "e já ficarão vinculados automaticamente."
        ),
        "expira_em": "nunca (válido até ser usado)",
    }


# =========================================================
# GET /pacientes/{id}/vinculos/
# =========================================================

@router.get("/pacientes/{paciente_id}/vinculos/")
def listar_vinculos(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    vinculos = session.exec(
        select(VinculoEspecialistaFamilia).where(
            VinculoEspecialistaFamilia.paciente_id == paciente_id
        )
    ).all()

    result = []
    for v in vinculos:
        d = v.model_dump()
        if v.responsavel_id:
            responsavel = session.get(UsuarioModel, v.responsavel_id)
            d["responsavel_nome"] = responsavel.nome if responsavel else None
        else:
            d["responsavel_nome"] = None
        result.append(d)
    return result


# =========================================================
# GET /pacientes/{id}/registros-familia/
# =========================================================

@router.get("/pacientes/{paciente_id}/registros-familia/")
def registros_familia(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    planos = session.exec(
        select(PlanoSemanal)
        .where(
            PlanoSemanal.paciente_id == paciente_id,
            PlanoSemanal.enviado_familia == True,  # noqa: E712
        )
        .order_by(PlanoSemanal.semana_inicio.desc())  # type: ignore[attr-defined]
    ).all()

    total_tarefas_enviadas = 0
    total_tarefas_concluidas = 0
    planos_result = []

    for plano in planos:
        registros = session.exec(
            select(RegistroPlanoFamilia).where(
                RegistroPlanoFamilia.plano_id == plano.id
            )
        ).all()

        try:
            tarefas = json.loads(plano.tarefas)
        except (json.JSONDecodeError, TypeError):
            tarefas = []

        total_plano = len(tarefas)
        concluidas_plano = sum(1 for r in registros if r.concluiu)
        percentual = round(concluidas_plano / total_plano * 100, 1) if total_plano else 0.0

        total_tarefas_enviadas += total_plano
        total_tarefas_concluidas += concluidas_plano

        planos_result.append({
            "id": plano.id,
            "semana_inicio": plano.semana_inicio,
            "semana_fim": plano.semana_fim,
            "tarefas": tarefas,
            "enviado_em": plano.enviado_em,
            "percentual_conclusao": percentual,
            "registros": [
                {
                    "tarefa_index": r.tarefa_index,
                    "tarefa_titulo": (
                        tarefas[r.tarefa_index].get("titulo")
                        if r.tarefa_index < len(tarefas) else None
                    ),
                    "concluiu": r.concluiu,
                    "humor": r.humor,
                    "observacao": r.observacao,
                    "criado_em": r.criado_em,
                }
                for r in registros
            ],
        })

    engajamento = (
        round(total_tarefas_concluidas / total_tarefas_enviadas * 100, 1)
        if total_tarefas_enviadas else 0.0
    )

    return {
        "planos": planos_result,
        "total_tarefas_enviadas": total_tarefas_enviadas,
        "total_tarefas_concluidas": total_tarefas_concluidas,
        "engajamento_geral": engajamento,
    }


# =========================================================
# Psicomotricidade — Schemas
# =========================================================

class AvaliacaoPsicomotricidadeCreate(BaseModel):
    data_avaliacao: date
    coordenacao_fina: Optional[str] = None
    coordenacao_fina_obs: Optional[str] = None
    coordenacao_grossa: Optional[str] = None
    coordenacao_grossa_obs: Optional[str] = None
    equilibrio: Optional[str] = None
    equilibrio_obs: Optional[str] = None
    lateralidade: Optional[str] = None
    lateralidade_obs: Optional[str] = None
    esquema_corporal: Optional[str] = None
    esquema_corporal_obs: Optional[str] = None
    orientacao_espacial: Optional[str] = None
    orientacao_espacial_obs: Optional[str] = None
    orientacao_temporal: Optional[str] = None
    orientacao_temporal_obs: Optional[str] = None
    tonus_muscular: Optional[str] = None
    tonus_muscular_obs: Optional[str] = None
    praxia_global: Optional[str] = None
    praxia_global_obs: Optional[str] = None
    praxia_fina: Optional[str] = None
    praxia_fina_obs: Optional[str] = None
    observacoes_gerais: Optional[str] = None


class GerarAtividadePsicomotricidadeRequest(BaseModel):
    area_foco: str
    nivel_atual: str
    duracao_minutos: int = 15
    observacoes: Optional[str] = None


# =========================================================
# Psicomotricidade — Helper de tendência
# =========================================================

_NIVEL_VALOR = {"emergente": 1, "em_desenvolvimento": 2, "consolidado": 3}


def _tendencia_habilidade(valores: list) -> str:
    numeros = [_NIVEL_VALOR[v] for v in valores if v in _NIVEL_VALOR]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/psicomotricidade/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicomotricidade/avaliacao/", status_code=201)
def criar_avaliacao_psicomotricidade(
    paciente_id: int,
    dados: AvaliacaoPsicomotricidadeCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoPsicomotricidade(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/psicomotricidade/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicomotricidade/avaliacao/")
def listar_avaliacoes_psicomotricidade(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoPsicomotricidade)
        .where(AvaliacaoPsicomotricidade.paciente_id == paciente_id)
        .order_by(AvaliacaoPsicomotricidade.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# GET /pacientes/{id}/psicomotricidade/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicomotricidade/evolucao/")
def evolucao_psicomotricidade(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    sessoes = session.exec(
        select(SessaoClinica)
        .where(
            SessaoClinica.paciente_id == paciente_id,
            SessaoClinica.especialidade == "psicomotricidade",
        )
        .order_by(SessaoClinica.data_sessao.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES = [
        "coordenacao_fina",
        "coordenacao_grossa",
        "equilibrio",
        "lateralidade",
        "esquema_corporal",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES:
        historico = [
            {"data": str(s.data_sessao), "valor": getattr(s, hab)}
            for s in sessoes
            if getattr(s, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade(valores),
        }

    relatorio_ia = None
    if sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao}: "
            f"coord_fina={s.coordenacao_fina or '?'}, "
            f"coord_grossa={s.coordenacao_grossa or '?'}, "
            f"equilibrio={s.equilibrio or '?'}, "
            f"lateralidade={s.lateralidade or '?'}, "
            f"esquema_corporal={s.esquema_corporal or '?'}, "
            f"funcionou={s.o_que_funcionou or 'não registrado'}"
            for s in sessoes[-10:]
        )

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES
        )

        prompt = f"""Você é um especialista em psicomotricidade analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Dados das últimas {len(sessoes[-10:])} sessões:
{resumo_sessoes}

Habilidades atuais:
{habilidades_atuais}

Gere um relatório clínico breve com:
1. Pontos de progresso observados
2. Áreas que precisam de atenção
3. Sugestões para as próximas sessões
4. Orientações práticas para a família

Responda em JSON:
{{"pontos_positivos": ["string"], "areas_atencao": ["string"], "sugestoes_sessao": ["string"], "orientacoes_familia": ["string"], "resumo": "string"}}"""

        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            try:
                client = Groq(api_key=api_key)
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                )
                raw = _limpar_json_resposta(response.choices[0].message.content)
                relatorio_ia = json.loads(raw)
            except Exception as e:
                logger.error(f"Groq psicomotricidade evolução: {e}")

    return {
        "total_sessoes": len(sessoes),
        "habilidades": habilidades,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/psicomotricidade/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicomotricidade/gerar-atividade/", status_code=201)
def gerar_atividade_psicomotricidade(
    paciente_id: int,
    dados: GerarAtividadePsicomotricidadeRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    area_label = dados.area_foco.replace("_", " ").title()
    parametros = {
        "titulo": f"Atividade de Psicomotricidade — {area_label}",
        "disciplina": "Psicomotricidade",
        "tipo_atividade": "psicomotricidade",
        "nivel_dificuldade": dados.nivel_atual,
        "duracao_minutos": dados.duracao_minutos,
        "descricao": (
            f"Área de foco: {area_label}. "
            f"Nível atual: {dados.nivel_atual}. "
            f"{dados.observacoes or ''}"
        ).strip(),
    }

    try:
        resultado = gerar_atividade_clinica(
            paciente=paciente,
            especialista_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar atividade: {e}")

    return {
        "fonte": resultado["fonte"],
        "atividade": resultado["atividade"],
        "area_foco": dados.area_foco,
        "nivel_atual": dados.nivel_atual,
    }
