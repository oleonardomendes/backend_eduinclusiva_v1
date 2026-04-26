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
    AvaliacaoPsicopedagogia,
    AvaliacaoFono,
    AvaliacaoTO,
    AvaliacaoPsicologia,
    AvaliacaoABA,
    RegistroComportamentoABA,
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
# Psicopedagogia — Schemas
# =========================================================

class AvaliacaoPsicopedagogiaCreate(BaseModel):
    data_avaliacao: date
    nivel_leitura: Optional[str] = None
    nivel_leitura_obs: Optional[str] = None
    nivel_escrita: Optional[str] = None
    nivel_escrita_obs: Optional[str] = None
    nivel_matematica: Optional[str] = None
    nivel_matematica_obs: Optional[str] = None
    atencao: Optional[str] = None
    atencao_obs: Optional[str] = None
    memoria: Optional[str] = None
    memoria_obs: Optional[str] = None
    raciocinio_logico: Optional[str] = None
    raciocinio_logico_obs: Optional[str] = None
    linguagem_oral: Optional[str] = None
    linguagem_oral_obs: Optional[str] = None
    compreensao: Optional[str] = None
    compreensao_obs: Optional[str] = None
    organizacao: Optional[str] = None
    organizacao_obs: Optional[str] = None
    observacoes_gerais: Optional[str] = None


class GerarAtividadePsicopedagogiaRequest(BaseModel):
    area_foco: str   # "leitura" | "escrita" | "matematica" | "atencao" | "memoria" | etc
    nivel_atual: str
    duracao_minutos: int = 20
    observacoes: Optional[str] = None


# =========================================================
# Fono — Schemas
# =========================================================

class AvaliacaoFonoCreate(BaseModel):
    data_avaliacao: date
    linguagem_expressiva: Optional[str] = None
    linguagem_expressiva_obs: Optional[str] = None
    linguagem_receptiva: Optional[str] = None
    linguagem_receptiva_obs: Optional[str] = None
    articulacao: Optional[str] = None
    articulacao_obs: Optional[str] = None
    vocabulario: Optional[str] = None
    vocabulario_obs: Optional[str] = None
    fluencia: Optional[str] = None
    fluencia_obs: Optional[str] = None
    pragmatica: Optional[str] = None
    pragmatica_obs: Optional[str] = None
    qualidade_vocal: Optional[str] = None
    qualidade_vocal_obs: Optional[str] = None
    degluticao: Optional[str] = None
    degluticao_obs: Optional[str] = None
    usa_comunicacao_alternativa: Optional[bool] = None
    tipo_comunicacao_alternativa: Optional[str] = None
    comunicacao_alternativa_obs: Optional[str] = None
    fonemas_dificuldade: Optional[str] = None
    observacoes_gerais: Optional[str] = None


class GerarAtividadeFonoRequest(BaseModel):
    area_foco: str   # linguagem_expressiva|linguagem_receptiva|articulacao|vocabulario|pragmatica|comunicacao_alternativa
    nivel_atual: str
    duracao_minutos: int = 15
    observacoes: Optional[str] = None


# =========================================================
# TO — Schemas
# =========================================================

class AvaliacaoTOCreate(BaseModel):
    data_avaliacao: date
    alimentacao: Optional[str] = None
    alimentacao_obs: Optional[str] = None
    higiene: Optional[str] = None
    higiene_obs: Optional[str] = None
    vestir: Optional[str] = None
    vestir_obs: Optional[str] = None
    mobilidade: Optional[str] = None
    mobilidade_obs: Optional[str] = None
    organizacao_ambiente: Optional[str] = None
    organizacao_ambiente_obs: Optional[str] = None
    brincar: Optional[str] = None
    brincar_obs: Optional[str] = None
    integracao_sensorial: Optional[str] = None
    integracao_sensorial_obs: Optional[str] = None
    processamento_sensorial: Optional[str] = None
    processamento_sensorial_obs: Optional[str] = None
    participacao_escolar: Optional[str] = None
    participacao_escolar_obs: Optional[str] = None
    grafomotora: Optional[str] = None
    grafomotora_obs: Optional[str] = None
    indice_autonomia: Optional[int] = None
    observacoes_gerais: Optional[str] = None


class GerarAtividadeTORequest(BaseModel):
    area_foco: str   # alimentacao|higiene|vestir|mobilidade|brincar|integracao_sensorial|organizacao_ambiente|grafomotora
    nivel_atual: str
    duracao_minutos: int = 15
    observacoes: Optional[str] = None


# =========================================================
# Psicologia — Schemas
# =========================================================

class AvaliacaoPsicologiaCreate(BaseModel):
    data_avaliacao: date
    regulacao_emocional: Optional[str] = None
    regulacao_emocional_obs: Optional[str] = None
    comportamento_adaptativo: Optional[str] = None
    comportamento_adaptativo_obs: Optional[str] = None
    habilidades_sociais: Optional[str] = None
    habilidades_sociais_obs: Optional[str] = None
    nivel_ansiedade: Optional[str] = None
    nivel_ansiedade_obs: Optional[str] = None
    humor_geral: Optional[str] = None
    humor_geral_obs: Optional[str] = None
    autoestima: Optional[str] = None
    autoestima_obs: Optional[str] = None
    comportamentos_desafiadores: Optional[str] = None
    frequencia_comportamentos: Optional[str] = None
    estrategias_enfrentamento: Optional[str] = None
    qualidade_sono: Optional[str] = None
    qualidade_sono_obs: Optional[str] = None
    relacao_alimentacao: Optional[str] = None
    relacao_alimentacao_obs: Optional[str] = None
    observacoes_gerais: Optional[str] = None


class GerarAtividadePsicologiaRequest(BaseModel):
    area_foco: str   # regulacao_emocional|habilidades_sociais|ansiedade|autoestima|sono|comportamentos_desafiadores
    nivel_atual: str
    duracao_minutos: int = 20
    observacoes: Optional[str] = None


# =========================================================
# ABA — Schemas
# =========================================================

class AvaliacaoABACreate(BaseModel):
    data_avaliacao: date
    nivel_verbal: Optional[str] = None
    nivel_verbal_obs: Optional[str] = None
    imitacao: Optional[str] = None
    imitacao_obs: Optional[str] = None
    contato_visual: Optional[str] = None
    contato_visual_obs: Optional[str] = None
    seguir_instrucoes: Optional[str] = None
    seguir_instrucoes_obs: Optional[str] = None
    habilidades_jogo: Optional[str] = None
    habilidades_jogo_obs: Optional[str] = None
    comportamentos_interferentes: Optional[str] = None
    intensidade_comportamentos: Optional[str] = None
    reforcadores_primarios: Optional[str] = None
    reforcadores_secundarios: Optional[str] = None
    taxa_acerto_geral: Optional[int] = None
    programas_andamento: Optional[str] = None
    observacoes_gerais: Optional[str] = None


class RegistroComportamentoABACreate(BaseModel):
    comportamento: str
    antecedente: Optional[str] = None
    consequencia: Optional[str] = None
    total_tentativas: int
    total_acertos: int
    tipo_auxilio: Optional[str] = None
    reforcador_utilizado: Optional[str] = None
    data_registro: date
    sessao_id: Optional[int] = None
    observacoes: Optional[str] = None


class GerarAtividadeABARequest(BaseModel):
    comportamento_alvo: str
    taxa_acerto_atual: float
    tipo_auxilio_atual: str
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


# =========================================================
# Psicopedagogia — Helpers de tendência
# =========================================================

_NIVEL_VALOR_LITERACIA = {
    "pre_silabico": 1,
    "silabico": 2,
    "silabico_alfabetico": 3,
    "alfabetico": 4,
    "fluente": 5,
}

_NIVEL_VALOR_COGNICAO = {
    "muito_baixa": 1,
    "baixa": 2,
    "adequada": 3,
    "adequado": 3,
    "boa": 4,
    "bom": 4,
    "avancado": 4,
}

_NIVEL_VALOR_LINGUAGEM = {
    "emergente": 1,
    "em_desenvolvimento": 2,
    "consolidado": 3,
}

_CAMPOS_LITERACIA = {"nivel_leitura", "nivel_escrita"}
_CAMPOS_COGNICAO = {"nivel_matematica", "atencao", "memoria", "raciocinio_logico"}


def _tendencia_habilidade_psico(campo: str, valores: list) -> str:
    if campo in _CAMPOS_LITERACIA:
        mapa = _NIVEL_VALOR_LITERACIA
    elif campo in _CAMPOS_COGNICAO:
        mapa = _NIVEL_VALOR_COGNICAO
    else:
        mapa = _NIVEL_VALOR_LINGUAGEM
    numeros = [mapa[v] for v in valores if v in mapa]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/psicopedagogia/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicopedagogia/avaliacao/", status_code=201)
def criar_avaliacao_psicopedagogia(
    paciente_id: int,
    dados: AvaliacaoPsicopedagogiaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoPsicopedagogia(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/psicopedagogia/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicopedagogia/avaliacao/")
def listar_avaliacoes_psicopedagogia(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoPsicopedagogia)
        .where(AvaliacaoPsicopedagogia.paciente_id == paciente_id)
        .order_by(AvaliacaoPsicopedagogia.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# GET /pacientes/{id}/psicopedagogia/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicopedagogia/evolucao/")
def evolucao_psicopedagogia(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacoes = session.exec(
        select(AvaliacaoPsicopedagogia)
        .where(AvaliacaoPsicopedagogia.paciente_id == paciente_id)
        .order_by(AvaliacaoPsicopedagogia.data_avaliacao.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES_PSICO = [
        "nivel_leitura",
        "nivel_escrita",
        "nivel_matematica",
        "atencao",
        "memoria",
        "raciocinio_logico",
        "linguagem_oral",
        "compreensao",
        "organizacao",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES_PSICO:
        historico = [
            {"data": str(a.data_avaliacao), "valor": getattr(a, hab)}
            for a in avaliacoes
            if getattr(a, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade_psico(hab, valores),
        }

    relatorio_ia = None
    if avaliacoes:
        resumo_avals = "\n".join(
            f"- {a.data_avaliacao}: "
            f"leitura={a.nivel_leitura or '?'}, "
            f"escrita={a.nivel_escrita or '?'}, "
            f"matematica={a.nivel_matematica or '?'}, "
            f"atencao={a.atencao or '?'}, "
            f"memoria={a.memoria or '?'}, "
            f"raciocinio={a.raciocinio_logico or '?'}, "
            f"linguagem={a.linguagem_oral or '?'}, "
            f"compreensao={a.compreensao or '?'}, "
            f"organizacao={a.organizacao or '?'}"
            for a in avaliacoes[-10:]
        )

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES_PSICO
        )

        prompt = f"""Você é um psicopedagogo analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Dados das últimas {len(avaliacoes[-10:])} avaliações:
{resumo_avals}

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
                logger.error(f"Groq psicopedagogia evolução: {e}")

    return {
        "total_avaliacoes": len(avaliacoes),
        "habilidades": habilidades,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/psicopedagogia/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicopedagogia/gerar-atividade/", status_code=201)
def gerar_atividade_psicopedagogia(
    paciente_id: int,
    dados: GerarAtividadePsicopedagogiaRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    area_label = dados.area_foco.replace("_", " ").title()
    parametros = {
        "titulo": f"Atividade de Psicopedagogia — {area_label}",
        "disciplina": "Psicopedagogia",
        "tipo_atividade": "psicopedagogia",
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


# =========================================================
# Fono — Helpers de tendência
# =========================================================

_NIVEL_VALOR_FONO_EXPRESSIVA = {
    "nao_verbal": 1,
    "sons": 2,
    "palavras_isoladas": 3,
    "duas_palavras": 4,
    "frases_simples": 5,
    "frases_complexas": 6,
}

_NIVEL_VALOR_FONO_GERAL = {
    "muito_comprometida": 1,
    "comprometida": 2,
    "levemente_comprometida": 3,
    "em_desenvolvimento": 3,
    "minima": 1,
    "basica": 2,
    "adequada": 4,
    "boa": 5,
}

_NIVEL_VALOR_VOCABULARIO_FONO = {
    "muito_reduzido": 1,
    "reduzido": 2,
    "adequado": 3,
    "amplo": 4,
}

_CAMPOS_FONO_EXPRESSIVA = {"linguagem_expressiva"}
_CAMPOS_FONO_VOCABULARIO = {"vocabulario"}


def _tendencia_habilidade_fono(campo: str, valores: list) -> str:
    if campo in _CAMPOS_FONO_EXPRESSIVA:
        mapa = _NIVEL_VALOR_FONO_EXPRESSIVA
    elif campo in _CAMPOS_FONO_VOCABULARIO:
        mapa = _NIVEL_VALOR_VOCABULARIO_FONO
    else:
        mapa = _NIVEL_VALOR_FONO_GERAL
    numeros = [mapa[v] for v in valores if v in mapa]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/fono/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/fono/avaliacao/", status_code=201)
def criar_avaliacao_fono(
    paciente_id: int,
    dados: AvaliacaoFonoCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoFono(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/fono/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/fono/avaliacao/")
def listar_avaliacoes_fono(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoFono)
        .where(AvaliacaoFono.paciente_id == paciente_id)
        .order_by(AvaliacaoFono.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# GET /pacientes/{id}/fono/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/fono/evolucao/")
def evolucao_fono(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacoes = session.exec(
        select(AvaliacaoFono)
        .where(AvaliacaoFono.paciente_id == paciente_id)
        .order_by(AvaliacaoFono.data_avaliacao.asc())  # type: ignore[attr-defined]
    ).all()

    sessoes = session.exec(
        select(SessaoClinica)
        .where(
            SessaoClinica.paciente_id == paciente_id,
            SessaoClinica.especialidade == "fono",
        )
        .order_by(SessaoClinica.data_sessao.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES_FONO = [
        "linguagem_expressiva",
        "linguagem_receptiva",
        "articulacao",
        "vocabulario",
        "fluencia",
        "pragmatica",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES_FONO:
        historico = [
            {"data": str(a.data_avaliacao), "valor": getattr(a, hab)}
            for a in avaliacoes
            if getattr(a, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade_fono(hab, valores),
        }

    usa_ca = avaliacoes[-1].usa_comunicacao_alternativa if avaliacoes else None

    relatorio_ia = None
    if avaliacoes or sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao}: funcionou={s.o_que_funcionou or 'não registrado'}"
            for s in sessoes[-10:]
        ) if sessoes else "Nenhuma sessão registrada ainda."

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES_FONO
        )

        prompt = f"""Você é um fonoaudiólogo analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Dados das últimas sessões de fonoaudiologia:
{resumo_sessoes}

Habilidades de comunicação atuais:
{habilidades_atuais}
- Usa comunicação alternativa: {"sim" if usa_ca else "não" if usa_ca is False else "não informado"}

Gere um relatório fonoaudiológico breve com:
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
                logger.error(f"Groq fono evolução: {e}")

    return {
        "total_sessoes": len(sessoes),
        "total_avaliacoes": len(avaliacoes),
        "habilidades": habilidades,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/fono/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/fono/gerar-atividade/", status_code=201)
def gerar_atividade_fono(
    paciente_id: int,
    dados: GerarAtividadeFonoRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    area_label = dados.area_foco.replace("_", " ").title()
    parametros = {
        "titulo": f"Atividade de Fonoaudiologia — {area_label}",
        "disciplina": "Fonoaudiologia",
        "tipo_atividade": "fono",
        "nivel_dificuldade": dados.nivel_atual,
        "duracao_minutos": dados.duracao_minutos,
        "descricao": (
            f"Área de foco: {area_label}. "
            f"Nível atual: {dados.nivel_atual}. "
            f"{dados.observacoes or ''}"
        ).strip(),
    }

    try:
        resultado_fono = gerar_atividade_clinica(
            paciente=paciente,
            especialista_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar atividade: {e}")

    return {
        "fonte": resultado_fono["fonte"],
        "atividade": resultado_fono["atividade"],
        "area_foco": dados.area_foco,
        "nivel_atual": dados.nivel_atual,
    }


# =========================================================
# TO — Helpers de tendência
# =========================================================

_NIVEL_VALOR_TO_AVD = {
    "dependente": 1,
    "assistida": 2,
    "supervisao": 3,
    "independente": 4,
}

_NIVEL_VALOR_TO_BRINCAR = {
    "nao_funcional": 1,
    "funcional_simples": 2,
    "simbolico": 3,
    "cooperativo": 4,
}

_NIVEL_VALOR_TO_SENSORIAL = {
    "muito_comprometida": 1,
    "comprometida": 2,
    "levemente_comprometida": 3,
    "adequada": 4,
}

_CAMPOS_TO_AVD = {"alimentacao", "higiene", "vestir", "mobilidade"}
_CAMPOS_TO_BRINCAR = {"brincar"}


def _tendencia_habilidade_to(campo: str, valores: list) -> str:
    if campo in _CAMPOS_TO_AVD:
        mapa = _NIVEL_VALOR_TO_AVD
    elif campo in _CAMPOS_TO_BRINCAR:
        mapa = _NIVEL_VALOR_TO_BRINCAR
    else:
        mapa = _NIVEL_VALOR_TO_SENSORIAL
    numeros = [mapa[v] for v in valores if v in mapa]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/to/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/to/avaliacao/", status_code=201)
def criar_avaliacao_to(
    paciente_id: int,
    dados: AvaliacaoTOCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoTO(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/to/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/to/avaliacao/")
def listar_avaliacoes_to(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoTO)
        .where(AvaliacaoTO.paciente_id == paciente_id)
        .order_by(AvaliacaoTO.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# GET /pacientes/{id}/to/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/to/evolucao/")
def evolucao_to(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacoes = session.exec(
        select(AvaliacaoTO)
        .where(AvaliacaoTO.paciente_id == paciente_id)
        .order_by(AvaliacaoTO.data_avaliacao.asc())  # type: ignore[attr-defined]
    ).all()

    sessoes = session.exec(
        select(SessaoClinica)
        .where(
            SessaoClinica.paciente_id == paciente_id,
            SessaoClinica.especialidade == "to",
        )
        .order_by(SessaoClinica.data_sessao.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES_TO = [
        "alimentacao",
        "higiene",
        "vestir",
        "mobilidade",
        "brincar",
        "integracao_sensorial",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES_TO:
        historico = [
            {"data": str(a.data_avaliacao), "valor": getattr(a, hab)}
            for a in avaliacoes
            if getattr(a, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade_to(hab, valores),
        }

    indice_autonomia_atual = avaliacoes[-1].indice_autonomia if avaliacoes else None

    relatorio_ia = None
    if avaliacoes or sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao}: funcionou={s.o_que_funcionou or 'não registrado'}"
            for s in sessoes[-10:]
        ) if sessoes else "Nenhuma sessão registrada ainda."

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES_TO
        )

        prompt = f"""Você é um terapeuta ocupacional analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Dados das últimas sessões de terapia ocupacional:
{resumo_sessoes}

Habilidades de autonomia atuais:
{habilidades_atuais}
- Índice de autonomia: {indice_autonomia_atual if indice_autonomia_atual is not None else 'não avaliado'}%

Gere um relatório de terapia ocupacional breve com:
1. Pontos de progresso observados
2. Áreas que precisam de atenção
3. Sugestões para as próximas sessões
4. Orientações práticas para a família implementar nas atividades da vida diária

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
                logger.error(f"Groq TO evolução: {e}")

    return {
        "total_sessoes": len(sessoes),
        "total_avaliacoes": len(avaliacoes),
        "indice_autonomia_atual": indice_autonomia_atual,
        "habilidades": habilidades,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/to/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/to/gerar-atividade/", status_code=201)
def gerar_atividade_to(
    paciente_id: int,
    dados: GerarAtividadeTORequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    area_label = dados.area_foco.replace("_", " ").title()
    parametros = {
        "titulo": f"Atividade de Terapia Ocupacional — {area_label}",
        "disciplina": "Terapia Ocupacional",
        "tipo_atividade": "to",
        "nivel_dificuldade": dados.nivel_atual,
        "duracao_minutos": dados.duracao_minutos,
        "descricao": (
            f"Área de foco: {area_label}. "
            f"Nível atual: {dados.nivel_atual}. "
            f"{dados.observacoes or ''}"
        ).strip(),
    }

    try:
        resultado_to = gerar_atividade_clinica(
            paciente=paciente,
            especialista_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar atividade: {e}")

    return {
        "fonte": resultado_to["fonte"],
        "atividade": resultado_to["atividade"],
        "area_foco": dados.area_foco,
        "nivel_atual": dados.nivel_atual,
    }


# =========================================================
# Psicologia — Helpers de tendência
# =========================================================

_NIVEL_VALOR_PSICOL_GERAL = {
    "muito_comprometida": 1,
    "comprometida": 2,
    "em_desenvolvimento": 3,
    "adequada": 4,
}

_NIVEL_VALOR_PSICOL_ANSIEDADE = {
    "muito_alto": 1,
    "alto": 2,
    "moderado": 3,
    "baixo": 4,
    "minimo": 5,
}

_NIVEL_VALOR_PSICOL_HUMOR = {
    "muito_negativo": 1,
    "negativo": 2,
    "neutro": 3,
    "positivo": 4,
    "muito_positivo": 5,
}

_NIVEL_VALOR_PSICOL_AUTOESTIMA = {
    "muito_baixa": 1,
    "baixa": 2,
    "adequada": 3,
    "boa": 4,
}

_NIVEL_VALOR_PSICOL_SONO = {
    "muito_ruim": 1,
    "ruim": 2,
    "regular": 3,
    "boa": 4,
}

_CAMPOS_PSICOL_ANSIEDADE = {"nivel_ansiedade"}
_CAMPOS_PSICOL_HUMOR = {"humor_geral"}
_CAMPOS_PSICOL_AUTOESTIMA = {"autoestima"}
_CAMPOS_PSICOL_SONO = {"qualidade_sono"}


def _tendencia_habilidade_psicol(campo: str, valores: list) -> str:
    if campo in _CAMPOS_PSICOL_ANSIEDADE:
        mapa = _NIVEL_VALOR_PSICOL_ANSIEDADE
    elif campo in _CAMPOS_PSICOL_HUMOR:
        mapa = _NIVEL_VALOR_PSICOL_HUMOR
    elif campo in _CAMPOS_PSICOL_AUTOESTIMA:
        mapa = _NIVEL_VALOR_PSICOL_AUTOESTIMA
    elif campo in _CAMPOS_PSICOL_SONO:
        mapa = _NIVEL_VALOR_PSICOL_SONO
    else:
        mapa = _NIVEL_VALOR_PSICOL_GERAL
    numeros = [mapa[v] for v in valores if v in mapa]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/psicologia/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicologia/avaliacao/", status_code=201)
def criar_avaliacao_psicologia(
    paciente_id: int,
    dados: AvaliacaoPsicologiaCreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoPsicologia(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/psicologia/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicologia/avaliacao/")
def listar_avaliacoes_psicologia(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoPsicologia)
        .where(AvaliacaoPsicologia.paciente_id == paciente_id)
        .order_by(AvaliacaoPsicologia.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# GET /pacientes/{id}/psicologia/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/psicologia/evolucao/")
def evolucao_psicologia(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacoes = session.exec(
        select(AvaliacaoPsicologia)
        .where(AvaliacaoPsicologia.paciente_id == paciente_id)
        .order_by(AvaliacaoPsicologia.data_avaliacao.asc())  # type: ignore[attr-defined]
    ).all()

    sessoes = session.exec(
        select(SessaoClinica)
        .where(
            SessaoClinica.paciente_id == paciente_id,
            SessaoClinica.especialidade == "psicologia",
        )
        .order_by(SessaoClinica.data_sessao.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES_PSICOL = [
        "regulacao_emocional",
        "habilidades_sociais",
        "nivel_ansiedade",
        "humor_geral",
        "autoestima",
        "qualidade_sono",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES_PSICOL:
        historico = [
            {"data": str(a.data_avaliacao), "valor": getattr(a, hab)}
            for a in avaliacoes
            if getattr(a, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade_psicol(hab, valores),
        }

    comportamentos_atual = avaliacoes[-1].comportamentos_desafiadores if avaliacoes else None
    frequencia_atual = avaliacoes[-1].frequencia_comportamentos if avaliacoes else None

    relatorio_ia = None
    if avaliacoes or sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao}: funcionou={s.o_que_funcionou or 'não registrado'}"
            for s in sessoes[-10:]
        ) if sessoes else "Nenhuma sessão registrada ainda."

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES_PSICOL
        )

        prompt = f"""Você é um psicólogo infantil analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Dados das últimas sessões de psicologia:
{resumo_sessoes}

Perfil emocional e comportamental atual:
{habilidades_atuais}
- Comportamentos desafiadores: {comportamentos_atual or 'não informado'}
- Frequência: {frequencia_atual or 'não informado'}

Gere um relatório psicológico breve com:
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
                logger.error(f"Groq psicologia evolução: {e}")

    return {
        "total_sessoes": len(sessoes),
        "total_avaliacoes": len(avaliacoes),
        "habilidades": habilidades,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/psicologia/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/psicologia/gerar-atividade/", status_code=201)
def gerar_atividade_psicologia(
    paciente_id: int,
    dados: GerarAtividadePsicologiaRequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    area_label = dados.area_foco.replace("_", " ").title()
    parametros = {
        "titulo": f"Atividade de Psicologia — {area_label}",
        "disciplina": "Psicologia",
        "tipo_atividade": "psicologia",
        "nivel_dificuldade": dados.nivel_atual,
        "duracao_minutos": dados.duracao_minutos,
        "descricao": (
            f"Área de foco: {area_label}. "
            f"Nível atual: {dados.nivel_atual}. "
            f"{dados.observacoes or ''}"
        ).strip(),
    }

    try:
        resultado_psicol = gerar_atividade_clinica(
            paciente=paciente,
            especialista_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar atividade: {e}")

    return {
        "fonte": resultado_psicol["fonte"],
        "atividade": resultado_psicol["atividade"],
        "area_foco": dados.area_foco,
        "nivel_atual": dados.nivel_atual,
    }


# =========================================================
# ABA — Helpers de tendência
# =========================================================

_NIVEL_VALOR_ABA_VERBAL = {
    "nao_verbal": 1,
    "ecoico": 2,
    "mando": 3,
    "tato": 4,
    "intraverbal": 5,
    "conversacional": 6,
}

_NIVEL_VALOR_ABA_IMITACAO = {
    "ausente": 1,
    "emergente": 2,
    "em_desenvolvimento": 3,
    "consolidada": 4,
}

_NIVEL_VALOR_ABA_CONTATO = {
    "ausente": 1,
    "minimo": 2,
    "ocasional": 3,
    "frequente": 4,
    "consistente": 5,
}

_NIVEL_VALOR_ABA_INSTRUCOES = {
    "1_passo": 1,
    "2_passos": 2,
    "3_passos": 3,
    "complexas": 4,
}

_CAMPOS_ABA_VERBAL = {"nivel_verbal"}
_CAMPOS_ABA_IMITACAO = {"imitacao"}
_CAMPOS_ABA_CONTATO = {"contato_visual"}
_CAMPOS_ABA_INSTRUCOES = {"seguir_instrucoes"}


def _tendencia_habilidade_aba(campo: str, valores: list) -> str:
    if campo in _CAMPOS_ABA_VERBAL:
        mapa = _NIVEL_VALOR_ABA_VERBAL
    elif campo in _CAMPOS_ABA_IMITACAO:
        mapa = _NIVEL_VALOR_ABA_IMITACAO
    elif campo in _CAMPOS_ABA_CONTATO:
        mapa = _NIVEL_VALOR_ABA_CONTATO
    elif campo in _CAMPOS_ABA_INSTRUCOES:
        mapa = _NIVEL_VALOR_ABA_INSTRUCOES
    else:
        mapa = _NIVEL_VALOR_ABA_IMITACAO  # fallback 4-níveis
    numeros = [mapa[v] for v in valores if v in mapa]
    if len(numeros) < 2:
        return "estavel"
    if numeros[-1] > numeros[0]:
        return "melhorando"
    if numeros[-1] < numeros[0]:
        return "precisa_atencao"
    return "estavel"


def _tendencia_taxa(taxas: list) -> str:
    if len(taxas) < 2:
        return "estavel"
    if taxas[-1] > taxas[0]:
        return "melhorando"
    if taxas[-1] < taxas[0]:
        return "precisa_atencao"
    return "estavel"


# =========================================================
# POST /pacientes/{id}/aba/avaliacao/
# =========================================================

@router.post("/pacientes/{paciente_id}/aba/avaliacao/", status_code=201)
def criar_avaliacao_aba(
    paciente_id: int,
    dados: AvaliacaoABACreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacao = AvaliacaoABA(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        **dados.model_dump(),
    )
    session.add(avaliacao)
    session.commit()
    session.refresh(avaliacao)
    return avaliacao


# =========================================================
# GET /pacientes/{id}/aba/avaliacao/
# =========================================================

@router.get("/pacientes/{paciente_id}/aba/avaliacao/")
def listar_avaliacoes_aba(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    return session.exec(
        select(AvaliacaoABA)
        .where(AvaliacaoABA.paciente_id == paciente_id)
        .order_by(AvaliacaoABA.data_avaliacao.desc())  # type: ignore[attr-defined]
    ).all()


# =========================================================
# POST /pacientes/{id}/aba/comportamentos/
# =========================================================

@router.post("/pacientes/{paciente_id}/aba/comportamentos/", status_code=201)
def registrar_comportamento_aba(
    paciente_id: int,
    dados: RegistroComportamentoABACreate,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    taxa = (
        round((dados.total_acertos / dados.total_tentativas) * 100, 1)
        if dados.total_tentativas > 0
        else 0.0
    )

    registro = RegistroComportamentoABA(
        paciente_id=paciente_id,
        especialista_id=current_user.id,
        taxa_acerto=taxa,
        **dados.model_dump(),
    )
    session.add(registro)
    session.commit()
    session.refresh(registro)
    return registro


# =========================================================
# GET /pacientes/{id}/aba/comportamentos/
# =========================================================

@router.get("/pacientes/{paciente_id}/aba/comportamentos/")
def listar_comportamentos_aba(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    _verificar_acesso_paciente(paciente_id, current_user, session)

    registros = session.exec(
        select(RegistroComportamentoABA)
        .where(RegistroComportamentoABA.paciente_id == paciente_id)
        .order_by(RegistroComportamentoABA.data_registro.asc())  # type: ignore[attr-defined]
    ).all()

    # agrupa por nome do comportamento
    agrupado: dict = {}
    for r in registros:
        nome = r.comportamento
        if nome not in agrupado:
            agrupado[nome] = []
        agrupado[nome].append({
            "data": str(r.data_registro),
            "taxa_acerto": r.taxa_acerto,
            "tipo_auxilio": r.tipo_auxilio,
            "total_tentativas": r.total_tentativas,
            "total_acertos": r.total_acertos,
        })

    resultado = []
    for nome, historico in agrupado.items():
        taxas = [h["taxa_acerto"] for h in historico if h["taxa_acerto"] is not None]
        resultado.append({
            "comportamento": nome,
            "taxa_acerto_atual": taxas[-1] if taxas else None,
            "total_registros": len(historico),
            "historico": historico,
            "tendencia": _tendencia_taxa(taxas),
        })

    return resultado


# =========================================================
# GET /pacientes/{id}/aba/evolucao/
# =========================================================

@router.get("/pacientes/{paciente_id}/aba/evolucao/")
def evolucao_aba(
    paciente_id: int,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    avaliacoes = session.exec(
        select(AvaliacaoABA)
        .where(AvaliacaoABA.paciente_id == paciente_id)
        .order_by(AvaliacaoABA.data_avaliacao.asc())  # type: ignore[attr-defined]
    ).all()

    sessoes = session.exec(
        select(SessaoClinica)
        .where(
            SessaoClinica.paciente_id == paciente_id,
            SessaoClinica.especialidade == "aba",
        )
        .order_by(SessaoClinica.data_sessao.asc())  # type: ignore[attr-defined]
    ).all()

    registros = session.exec(
        select(RegistroComportamentoABA)
        .where(RegistroComportamentoABA.paciente_id == paciente_id)
        .order_by(RegistroComportamentoABA.data_registro.asc())  # type: ignore[attr-defined]
    ).all()

    _HABILIDADES_ABA = [
        "nivel_verbal",
        "imitacao",
        "contato_visual",
        "seguir_instrucoes",
        "habilidades_jogo",
    ]

    habilidades: dict = {}
    for hab in _HABILIDADES_ABA:
        historico = [
            {"data": str(a.data_avaliacao), "valor": getattr(a, hab)}
            for a in avaliacoes
            if getattr(a, hab)
        ]
        valores = [h["valor"] for h in historico]
        habilidades[hab] = {
            "atual": valores[-1] if valores else None,
            "historico": historico,
            "tendencia": _tendencia_habilidade_aba(hab, valores),
        }

    taxa_acerto_atual = avaliacoes[-1].taxa_acerto_geral if avaliacoes else None

    # agrupa comportamentos
    agrupado: dict = {}
    for r in registros:
        nome = r.comportamento
        if nome not in agrupado:
            agrupado[nome] = []
        if r.taxa_acerto is not None:
            agrupado[nome].append(r.taxa_acerto)

    comportamentos_resumo = [
        {
            "comportamento": nome,
            "taxa_acerto_atual": taxas[-1] if taxas else None,
            "total_registros": len(taxas),
            "tendencia": _tendencia_taxa(taxas),
        }
        for nome, taxas in agrupado.items()
    ]

    relatorio_ia = None
    if avaliacoes or sessoes:
        resumo_sessoes = "\n".join(
            f"- {s.data_sessao}: funcionou={s.o_que_funcionou or 'não registrado'}"
            for s in sessoes[-10:]
        ) if sessoes else "Nenhuma sessão registrada ainda."

        habilidades_atuais = "\n".join(
            f"- {hab.replace('_', ' ').title()}: "
            f"{habilidades[hab]['atual'] or 'não avaliado'} "
            f"({habilidades[hab]['tendencia']})"
            for hab in _HABILIDADES_ABA
        )

        comportamentos_str = "\n".join(
            f"- {c['comportamento']}: {c['taxa_acerto_atual']}% ({c['tendencia']})"
            for c in comportamentos_resumo
        ) or "Nenhum comportamento registrado ainda."

        prompt = f"""Você é um terapeuta ABA analisando a evolução de {paciente.nome} ({paciente.idade or '?'} anos, {paciente.condicao or 'necessidade especial'} {paciente.grau or ''}).

Habilidades verbais e comportamentais atuais:
{habilidades_atuais}
- Taxa de acerto geral: {taxa_acerto_atual if taxa_acerto_atual is not None else 'não avaliado'}%

Comportamentos-alvo e taxas de acerto:
{comportamentos_str}

Dados das últimas sessões ABA:
{resumo_sessoes}

Gere um relatório ABA breve com:
1. Habilidades em consolidação
2. Comportamentos que precisam de mais intervenção
3. Sugestões de programas para próximas sessões
4. Orientações para a família generalizar os comportamentos aprendidos em casa

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
                logger.error(f"Groq ABA evolução: {e}")

    return {
        "total_sessoes": len(sessoes),
        "total_avaliacoes": len(avaliacoes),
        "taxa_acerto_atual": taxa_acerto_atual,
        "habilidades": habilidades,
        "comportamentos": comportamentos_resumo,
        "relatorio_ia": relatorio_ia,
    }


# =========================================================
# POST /pacientes/{id}/aba/gerar-atividade/
# =========================================================

@router.post("/pacientes/{paciente_id}/aba/gerar-atividade/", status_code=201)
def gerar_atividade_aba(
    paciente_id: int,
    dados: GerarAtividadeABARequest,
    session: Session = Depends(get_session),
    current_user: Usuario = Depends(get_current_user),
):
    _verificar_especialista(current_user)
    paciente = _verificar_acesso_paciente(paciente_id, current_user, session)

    parametros = {
        "titulo": f"Atividade ABA — {dados.comportamento_alvo}",
        "disciplina": "ABA",
        "tipo_atividade": "aba",
        "nivel_dificuldade": dados.tipo_auxilio_atual,
        "duracao_minutos": dados.duracao_minutos,
        "descricao": (
            f"Comportamento-alvo: {dados.comportamento_alvo}. "
            f"Taxa de acerto atual: {dados.taxa_acerto_atual}%. "
            f"Tipo de auxílio atual: {dados.tipo_auxilio_atual}. "
            f"{dados.observacoes or ''}"
        ).strip(),
    }

    try:
        resultado_aba = gerar_atividade_clinica(
            paciente=paciente,
            especialista_id=current_user.id,
            parametros=parametros,
            session=session,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar atividade: {e}")

    return {
        "fonte": resultado_aba["fonte"],
        "atividade": resultado_aba["atividade"],
        "comportamento_alvo": dados.comportamento_alvo,
        "taxa_acerto_atual": dados.taxa_acerto_atual,
    }
