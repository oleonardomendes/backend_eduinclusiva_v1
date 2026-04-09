# services/ai_service.py
import os
import json
import re
import logging
from datetime import datetime

from groq import Groq
from sqlmodel import Session, select

from app.models import Aluno, Avaliacao, AtividadeGerada, AtividadeTemplate, Meta, Plano, FilhoPublico, AtividadeFamilia

logger = logging.getLogger("uvicorn")


# =========================================================
# Helpers internos
# =========================================================

def _bimestre_atual() -> tuple[int, int]:
    """Retorna (bimestre, ano) com base no mês atual."""
    now = datetime.now()
    bimestre = (now.month - 1) // 3 + 1  # Jan-Mar=1, Abr-Jun=2, Jul-Set=3, Out-Dez=4
    return bimestre, now.year


def _progresso_real(session: Session, aluno_id: int, ano: int) -> float:
    """Média dos campos progresso das avaliações do aluno no ano (ignora None)."""
    avaliacoes = session.exec(
        select(Avaliacao).where(
            Avaliacao.aluno_id == aluno_id,
            Avaliacao.ano == ano,
            Avaliacao.progresso.is_not(None),  # type: ignore[attr-defined]
        )
    ).all()
    if not avaliacoes:
        return 0.0
    return sum(a.progresso for a in avaliacoes) / len(avaliacoes)  # type: ignore[arg-type]


def _meta_bimestre(session: Session, professor_id: int, bimestre: int, ano: int) -> int:
    """Retorna meta_progresso do bimestre ou 70 como padrão."""
    meta = session.exec(
        select(Meta).where(
            Meta.professor_id == professor_id,
            Meta.bimestre == bimestre,
            Meta.ano == ano,
        )
    ).first()
    return meta.meta_progresso if meta else 70


def _titulos_planos_recentes(session: Session, aluno_id: int) -> list[str]:
    """Últimos 3 títulos de planos do aluno."""
    planos = session.exec(
        select(Plano)
        .where(Plano.aluno_id == aluno_id)
        .order_by(Plano.criado_em.desc())  # type: ignore[attr-defined]
        .limit(3)
    ).all()
    return [p.titulo for p in planos]


def _limpar_json_resposta(texto: str) -> str:
    """
    Prepara o texto do modelo para json.loads():
    1. Remove blocos ```json``` / ```
    2. Remove caracteres de controle inválidos (exceto \\n e \\t que são válidos em JSON)
    3. Substitui quebras de linha literais dentro de valores por \\n escapado
    """
    # 1. Remove marcadores de bloco de código
    texto = re.sub(r"```(?:json)?", "", texto).strip().rstrip("`").strip()
    # 2. Remove caracteres de controle inválidos (mantém \n=0x0a e \t=0x09)
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)
    # 3. Substitui quebras de linha literais dentro de strings por \n escapado
    #    Regex captura conteúdo entre aspas e normaliza newlines internos
    texto = re.sub(r'("(?:[^"\\]|\\.)*")', lambda m: m.group(0).replace("\n", "\\n"), texto)
    return texto


def _serializar_lista(valor) -> str | None:
    """Serializa lista para JSON string; retorna None se valor for None."""
    if valor is None:
        return None
    if isinstance(valor, list):
        return json.dumps(valor, ensure_ascii=False)
    return valor  # já é string


# =========================================================
# Camada 1 — Template pré-cadastrado
# =========================================================

def _buscar_template(
    session: Session,
    necessidade: str | None,
    nivel_dificuldade: str | None,
) -> dict | None:
    templates = session.exec(
        select(AtividadeTemplate).where(AtividadeTemplate.ativo == True)  # noqa: E712
    ).all()

    for t in templates:
        # Verifica compatibilidade de necessidade
        if t.necessidades_alvo:
            try:
                nees = json.loads(t.necessidades_alvo)
            except (json.JSONDecodeError, TypeError):
                nees = []
            if necessidade and necessidade not in nees:
                continue
        # Filtra por nível de dificuldade se informado
        if nivel_dificuldade and t.nivel_dificuldade and t.nivel_dificuldade != nivel_dificuldade:
            continue
        return t.model_dump()

    return None


# =========================================================
# Camada 2 — IA reutilizável
# =========================================================

def _buscar_ia_reutilizavel(
    session: Session,
    aluno: Aluno,
    parametros: dict,
) -> dict | None:
    """
    Busca atividade reutilizável de OUTRO aluno com scoring de compatibilidade.
    Só reutiliza se score >= 70.

    Score máximo = 100:
      +30  necessidade_atendida == aluno.necessidade
      +25  grau_necessidade compatível (via parametros_professor da atividade)
      +25  estilo_aprendizagem do aluno presente nas tags da atividade
      +20  nivel_dificuldade compatível (só conta se foi informado nos parametros)
    """
    candidatas = session.exec(
        select(AtividadeGerada)
        .where(
            AtividadeGerada.reutilizavel == True,  # noqa: E712
            AtividadeGerada.aluno_id != aluno.id,
        )
    ).all()

    nivel_dificuldade = parametros.get("nivel_dificuldade")
    melhor: AtividadeGerada | None = None
    melhor_score = -1

    for a in candidatas:
        score = 0

        # +30 — necessidade atendida
        if a.necessidade_atendida == aluno.necessidade:
            score += 30

        # +25 — grau da necessidade compatível (armazenado em parametros_professor)
        grau_aluno = getattr(aluno, "grau_necessidade", None)
        if grau_aluno and a.parametros_professor:
            try:
                params_orig = json.loads(a.parametros_professor)
                if params_orig.get("grau_necessidade") == grau_aluno:
                    score += 25
            except (json.JSONDecodeError, TypeError):
                pass

        # +25 — estilo de aprendizagem presente nas tags da atividade
        estilo_aluno = getattr(aluno, "estilo_aprendizagem", None)
        if estilo_aluno and a.tags:
            try:
                tags = json.loads(a.tags)
                if estilo_aluno in tags:
                    score += 25
            except (json.JSONDecodeError, TypeError):
                pass

        # +20 — nível de dificuldade compatível (só pontua se filtro foi informado)
        if nivel_dificuldade and a.dificuldade == nivel_dificuldade:
            score += 20

        if score >= 70 and score > melhor_score:
            melhor_score = score
            melhor = a

    if melhor:
        logger.info(
            f"Atividade reutilizável encontrada (score={melhor_score}): "
            f"'{melhor.titulo}' (id={melhor.id})"
        )
        return melhor.model_dump()
    return None


# =========================================================
# Camada 3 — Geração nova via Groq
# =========================================================

def _gerar_via_groq(
    session: Session,
    aluno: Aluno,
    professor_id: int,
    parametros: dict,
) -> dict:
    bimestre, ano = _bimestre_atual()
    progresso_real = round(_progresso_real(session, aluno.id, ano), 1)
    meta_progresso = _meta_bimestre(session, professor_id, bimestre, ano)

    titulos_recentes = _titulos_planos_recentes(session, aluno.id)
    historico = (
        "\n".join(f"- {t}" for t in titulos_recentes)
        if titulos_recentes
        else "Nenhuma atividade anterior"
    )

    gap = meta_progresso - progresso_real
    if gap > 5:
        situacao = "abaixo"
    elif gap < -5:
        situacao = "acima"
    else:
        situacao = "dentro"

    titulo = parametros.get("titulo") or "Atividade adaptada"
    disciplina = parametros.get("disciplina") or "Geral"
    tipo_atividade = parametros.get("tipo_atividade") or "Não especificado"
    nivel_dificuldade = parametros.get("nivel_dificuldade") or "Médio"
    duracao_minutos = parametros.get("duracao_minutos") or 30
    descricao = parametros.get("descricao") or "Não especificada"
    objetivos = parametros.get("objetivos") or "Não especificados"

    prompt = f"""Você é um especialista em educação inclusiva e pedagogia adaptada.

PERFIL DO ALUNO:
- Nome: {aluno.nome}
- Idade: {aluno.idade} anos
- Necessidade especial: {aluno.necessidade}
- Observações pedagógicas: {aluno.observacoes}
- Nível atual de aprendizado: {aluno.nivel_aprendizado}
- Série/Ano escolar: {aluno.sala or "não informado"}
- Idade: {aluno.idade} anos
- Referência curricular: a atividade deve ser compatível com o conteúdo esperado para o {aluno.sala or "ano escolar do aluno"}, adaptado para a necessidade especial do aluno.
- Objetivos de aprendizado: {aluno.objetivos_aprendizado}
- Progresso geral: {aluno.progresso_geral}%
- Estilo de aprendizagem: {aluno.estilo_aprendizagem}
- Grau da necessidade: {aluno.grau_necessidade}

SITUAÇÃO PEDAGÓGICA ATUAL:
- {bimestre}º bimestre de {ano}
- Meta de progresso: {meta_progresso}%
- Progresso real alcançado: {progresso_real}%
- Situação: {situacao} da meta em {abs(gap):.1f}%

PARÂMETROS DEFINIDOS PELO PROFESSOR PARA HOJE:
- Título desejado: {titulo}
- Disciplina: {disciplina}
- Tipo de atividade: {tipo_atividade}
- Nível de dificuldade: {nivel_dificuldade}
- Duração: {duracao_minutos} minutos
- Tema/descrição: {descricao}
- Objetivos específicos: {objetivos}

ATIVIDADES RECENTES (não repita):
{historico}

TAREFA:
Gere UMA atividade pedagógica adaptada respeitando os parâmetros do professor E o perfil do aluno.
- Se abaixo da meta: priorize recuperação e reforço
- Se dentro da meta: priorize consolidação
- Se acima da meta: priorize avanço e enriquecimento
Considere SEMPRE a necessidade especial do aluno em todas as seções.

Para instrucao_professor: explique como conduzir a atividade em sala usando materiais simples disponíveis na escola (lápis, borracha, caderno, tampinhas, palitos, etc). Seja prático com exemplos concretos.

Para instrucao_familia: explique como os pais podem fazer esta mesma atividade em casa usando objetos do dia a dia (colheres, botões, frutas, brinquedos, etc). Use linguagem simples e acessível.

Para conteudo_atividade: descreva o exercício detalhadamente como se fosse uma folha de atividade. Inclua exemplos práticos e espaços para resposta descritos em texto (ex: "Escreva o resultado aqui: ___").

Considere a série escolar ao definir o nível de complexidade do conteúdo. Uma criança no 2º ano trabalha números até 100, leitura de palavras simples e frases curtas. Uma criança no 3º ano já trabalha multiplicação simples, textos maiores, etc. Adapte o conteúdo curricular para a necessidade especial, mas mantenha a referência da série.

Adapte a atividade considerando o estilo de aprendizagem do aluno:
- Visual: use desenhos descritos em texto, cores, diagramas escritos
- Auditivo: inclua músicas, rimas, repetição oral
- Cinestésico: priorize movimento, manipulação de objetos, atividades práticas
- Visual-Cinestésico: combine elementos visuais com atividades manuais
- Misto: varie as abordagens

Considere também o grau da necessidade:
- Leve: adaptações mínimas, próximo ao currículo regular
- Moderado: adaptações significativas, mais tempo, materiais concretos
- Severo: adaptações extensas, foco em habilidades funcionais

Responda APENAS com JSON válido, sem markdown, sem texto extra:
{{
  "titulo": "string",
  "objetivo": "string",
  "duracao_minutos": number,
  "dificuldade": "Fácil|Médio|Difícil",
  "instrucao_professor": "string",
  "instrucao_familia": "string",
  "conteudo_atividade": "string",
  "materiais": ["string"],
  "passo_a_passo": ["string"],
  "adaptacoes": ["string"],
  "criterios_avaliacao": ["string"],
  "justificativa": "string",
  "tags": ["string"]
}}"""

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nas variáveis de ambiente.")

    client = Groq(api_key=api_key)
    logger.info(f"Gerando atividade via Groq para aluno {aluno.id} ({aluno.nome})")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    texto = response.choices[0].message.content

    raw = _limpar_json_resposta(texto)
    try:
        resultado = json.loads(raw)
    except json.JSONDecodeError:
        try:
            resultado = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Falha ao parsear JSON do Groq: {e}\nResposta bruta:\n{raw}")
            raise ValueError("Groq retornou resposta inválida (não é JSON)") from e

    now = datetime.now()
    atividade = AtividadeGerada(
        aluno_id=aluno.id,
        professor_id=professor_id,
        titulo=resultado["titulo"],
        objetivo=resultado.get("objetivo"),
        duracao_minutos=resultado.get("duracao_minutos"),
        dificuldade=resultado.get("dificuldade"),
        instrucao_professor=resultado.get("instrucao_professor"),
        instrucao_familia=resultado.get("instrucao_familia"),
        conteudo_atividade=resultado.get("conteudo_atividade"),
        materiais=_serializar_lista(resultado.get("materiais")),
        passo_a_passo=_serializar_lista(resultado.get("passo_a_passo")),
        adaptacoes=_serializar_lista(resultado.get("adaptacoes")),
        criterios_avaliacao=_serializar_lista(resultado.get("criterios_avaliacao")),
        tags=_serializar_lista(resultado.get("tags")),
        justificativa=resultado.get("justificativa"),
        bimestre=(now.month - 1) // 3 + 1,
        ano=now.year,
        disciplina=parametros.get("disciplina"),
        tipo_atividade=parametros.get("tipo_atividade"),
        reutilizavel=True,
        necessidade_atendida=aluno.necessidade,
        parametros_professor=json.dumps(parametros, ensure_ascii=False),
    )
    session.add(atividade)
    session.commit()
    session.refresh(atividade)

    logger.info(f"Atividade gerada e salva com sucesso: '{atividade.titulo}' (id={atividade.id})")
    return atividade.model_dump()


# =========================================================
# Função principal — busca em 3 camadas
# =========================================================

def buscar_ou_gerar_atividade(
    aluno_id: int,
    professor_id: int,
    parametros: dict,
    session: Session,
) -> dict:
    """
    Busca ou gera uma atividade pedagógica adaptada em 3 camadas:
      1. Template pré-cadastrado (AtividadeTemplate)
      2. Atividade IA reutilizável (AtividadeGerada de outro aluno)
      3. Geração nova via Groq

    Retorna {"fonte": "template"|"ia_reutilizada"|"ia_nova", "atividade": dict}
    """
    aluno = session.get(Aluno, aluno_id)
    if not aluno:
        raise ValueError(f"Aluno {aluno_id} não encontrado.")

    nivel_dificuldade = parametros.get("nivel_dificuldade")

    # ── Camada 1: template ────────────────────────────────────────────────
    template = _buscar_template(session, aluno.necessidade, nivel_dificuldade)
    if template:
        logger.info(f"Atividade encontrada via template para aluno {aluno_id}")
        return {"fonte": "template", "atividade": template}

    # ── Camada 2: IA reutilizável ─────────────────────────────────────────
    reutilizavel = _buscar_ia_reutilizavel(session, aluno, parametros)
    if reutilizavel:
        logger.info(f"Atividade IA reutilizada para aluno {aluno_id}")
        return {"fonte": "ia_reutilizada", "atividade": reutilizavel}

    # ── Camada 3: geração nova ────────────────────────────────────────────
    atividade_dict = _gerar_via_groq(session, aluno, professor_id, parametros)
    return {"fonte": "ia_nova", "atividade": atividade_dict}


# =========================================================
# Questionário de estilo de aprendizagem (portal família)
# =========================================================

def analisar_estilo_aprendizagem(
    respostas: list[dict],
    condicao: str | None,
    idade: int | None,
    grau: str | None,
) -> dict:
    """
    Analisa 8 respostas de um questionário e retorna:
      {"estilo": str, "grau": str, "relatorio": str}

    Cada item de `respostas` deve ter: {"pergunta": str, "resposta": str}
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nas variáveis de ambiente.")

    respostas_formatadas = "\n".join(
        f"{i+1}. Pergunta: {r.get('pergunta', '')}\n   Resposta: {r.get('resposta', '')}"
        for i, r in enumerate(respostas)
    )

    prompt = f"""Você é um especialista em neuropsicopedagogia e educação inclusiva.

Um responsável respondeu um questionário sobre o filho(a) para identificar o estilo de aprendizagem.

DADOS DA CRIANÇA:
- Condição/diagnóstico: {condicao or "Não informado"}
- Idade: {idade or "Não informada"} anos
- Grau estimado da necessidade: {grau or "Não informado"}

RESPOSTAS DO QUESTIONÁRIO:
{respostas_formatadas}

TAREFA:
Com base nas respostas, identifique:
1. O estilo de aprendizagem predominante (escolha UM: "Visual", "Auditivo", "Cinestésico", "Visual-Cinestésico" ou "Misto")
2. O grau estimado da necessidade especial (escolha UM: "Leve", "Moderado" ou "Severo")
3. Um relatório personalizado em português para o responsável (3 a 5 parágrafos) explicando:
   - O que o estilo de aprendizagem identificado significa
   - Como isso se manifesta no dia a dia da criança
   - Estratégias práticas para usar em casa considerando a condição e o estilo
   - Como estimular o desenvolvimento em casa de forma acolhedora

Responda APENAS com JSON válido:
{{
  "estilo": "string",
  "grau": "string",
  "relatorio": "string"
}}"""

    client = Groq(api_key=api_key)
    logger.info("Analisando estilo de aprendizagem via Groq (portal família)")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    texto = response.choices[0].message.content

    raw = _limpar_json_resposta(texto)
    try:
        resultado = json.loads(raw)
    except json.JSONDecodeError:
        try:
            resultado = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Falha ao parsear JSON do Groq (estilo): {e}\nResposta:\n{raw}")
            raise ValueError("Groq retornou resposta inválida (não é JSON)") from e

    return {
        "estilo": resultado.get("estilo", "Misto"),
        "grau": resultado.get("grau", "Moderado"),
        "relatorio": resultado.get("relatorio", ""),
    }


# =========================================================
# Geração de atividade para uso em casa (portal família)
# =========================================================

def gerar_atividade_familia(
    filho: "FilhoPublico",
    area: str,
    descricao_situacao: str,
    duracao_minutos: int,
    session: Session,
) -> dict:
    """
    Gera uma atividade para ser realizada em casa pelo responsável com o filho.
    Salva em AtividadeFamilia e retorna o dict da atividade.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nas variáveis de ambiente.")

    prompt = f"""Você é um especialista em educação inclusiva e atividades terapêutico-pedagógicas para uso em casa.

PERFIL DA CRIANÇA:
- Nome: {filho.nome}
- Idade: {filho.idade or "Não informada"} anos
- Condição/diagnóstico: {filho.condicao or "Não informada"}
- Estilo de aprendizagem: {filho.estilo_aprendizagem or "Não identificado"}
- Grau da necessidade: {filho.grau_necessidade or "Não informado"}

PEDIDO DO RESPONSÁVEL:
- Área de trabalho: {area}
- Situação/objetivo: {descricao_situacao}
- Tempo disponível: {duracao_minutos} minutos

TAREFA:
Crie UMA atividade prática e acolhedora para o responsável realizar em casa com a criança.
- Use apenas objetos comuns de casa (colheres, botões, frutas, caixas, papel, etc.)
- A linguagem deve ser simples, acessível e encorajadora para os pais
- Considere o estilo de aprendizagem da criança em todas as etapas
- Adapte para a condição e o grau da necessidade especial
- O foco é criar um momento de aprendizagem positivo e sem pressão

Adapte ao estilo de aprendizagem:
- Visual: use cartões coloridos, desenhos, cores, organização visual
- Auditivo: inclua música, rimas, narração em voz alta
- Cinestésico: priorize movimento, manipulação de objetos, atividades sensoriais
- Visual-Cinestésico: combine elementos visuais com atividades práticas
- Misto: varie as abordagens

Responda APENAS com JSON válido:
{{
  "titulo": "string",
  "objetivo": "string",
  "duracao_minutos": number,
  "instrucao_familia": "string (texto motivador explicando como conduzir)",
  "conteudo_atividade": "string (descrição detalhada da atividade)",
  "materiais": ["string"],
  "passo_a_passo": ["string"],
  "adaptacoes": ["string (dicas extras para facilitar)"]
}}"""

    client = Groq(api_key=api_key)
    logger.info(f"Gerando atividade família via Groq para filho {filho.id} ({filho.nome})")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    texto = response.choices[0].message.content

    raw = _limpar_json_resposta(texto)
    try:
        resultado = json.loads(raw)
    except json.JSONDecodeError:
        try:
            resultado = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Falha ao parsear JSON do Groq (família): {e}\nResposta:\n{raw}")
            raise ValueError("Groq retornou resposta inválida (não é JSON)") from e

    atividade = AtividadeFamilia(
        filho_id=filho.id,
        responsavel_id=filho.responsavel_id,
        titulo=resultado["titulo"],
        objetivo=resultado.get("objetivo"),
        duracao_minutos=resultado.get("duracao_minutos"),
        area=area,
        instrucao_familia=resultado.get("instrucao_familia"),
        conteudo_atividade=resultado.get("conteudo_atividade"),
        materiais=_serializar_lista(resultado.get("materiais")),
        passo_a_passo=_serializar_lista(resultado.get("passo_a_passo")),
        adaptacoes=_serializar_lista(resultado.get("adaptacoes")),
    )
    session.add(atividade)
    session.commit()
    session.refresh(atividade)

    logger.info(f"Atividade família salva: '{atividade.titulo}' (id={atividade.id})")
    return atividade.model_dump()


# =========================================================
# Alias para compatibilidade com routes/ai.py atual
# =========================================================

def gerar_atividade_adaptada(aluno_id: int, professor_id: int, session: Session) -> dict:
    """
    Alias de compatibilidade — chama buscar_ou_gerar_atividade com parâmetros vazios
    e retorna apenas o dict da atividade (sem o campo "fonte").
    Será substituído quando routes/ai.py for atualizado.
    """
    resultado = buscar_ou_gerar_atividade(aluno_id, professor_id, {}, session)
    return resultado["atividade"]
