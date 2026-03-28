# app/services/rag_service.py
import os
import json
import re
from typing import Dict, Any, List
from app.services.vector_store import get_vector_store

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# ============================================================
# 🔹 HELPER: Monta o prompt de RAG
# ============================================================
def build_rag_prompt(prof_input: Dict[str, Any], docs: List[Dict[str, Any]]) -> str:
    """
    prof_input: dados do professor (matéria, competência, descrição do aluno etc.)
    docs: lista de chunks retornados do vector store
    """
    header = (
        "Você é um assistente pedagógico especializado em educação inclusiva. "
        "Gere um plano didático individualizado e acessível para alunos com necessidades especiais."
    )

    aluno = prof_input.get("descricao_aluno", "")
    contexto = (
        f"Matéria: {prof_input.get('materia','')}\n"
        f"Competência: {prof_input.get('competencia','')}\n"
        f"Conteúdo solicitado: {prof_input.get('conteudo','')}\n\n"
        f"Perfil do aluno: {aluno}\n\n"
    )

    contexto += "Histórico relevante do aluno (trechos recuperados dos documentos indexados):\n"
    for i, d in enumerate(docs):
        snippet = d.get("text", "")
        if len(snippet) > 1000:
            snippet = snippet[:1000] + " ... (truncado)"
        meta = d.get("metadata", {})
        contexto += f"--- Documento {i+1} [bimestre: {meta.get('bimestre','?')} | competência: {meta.get('competencia','?')}]\n{snippet}\n\n"

    instrucoes = (
        "Com base nesse histórico, gere um plano de aula adaptado em formato JSON com os campos:\n"
        "titulo, atividades (lista com tipo, descricao, duracao_minutos), recomendacoes.\n"
        "As atividades devem ser práticas, curtas, inclusivas e adequadas ao nível e necessidade do aluno.\n"
        "Não inclua explicações fora do JSON — retorne apenas o JSON válido."
    )

    return f"{header}\n\n{contexto}\n{instrucoes}"


# ============================================================
# 🔹 FUNÇÃO PRINCIPAL: Gera plano adaptado com RAG
# ============================================================
async def gerar_plano_adaptado(
    aluno_id: int,
    descricao_aluno: str,
    conteudo: str,
    materia: str = None,
    competencia: str = None,
    top_k: int = 5
) -> Dict[str, Any]:
    """
    Gera um plano adaptado de acordo com o histórico indexado do aluno (RAG).
    Busca os top_k trechos mais relevantes do histórico (chunked PDFs),
    constrói o prompt e gera um plano com IA (OpenAI) ou fallback determinístico.
    """
    store = get_vector_store()
    professor_input = {
        "descricao_aluno": descricao_aluno,
        "conteudo": conteudo,
        "materia": materia or "",
        "competencia": competencia or "",
    }

    # 1️⃣ Recuperar trechos relevantes via vector search (filtrando pelo aluno)
    filter_meta = {"aluno_id": str(aluno_id)} if aluno_id is not None else None
    docs = store.query(conteudo or descricao_aluno, top_k=top_k, metadata_filter=filter_meta)

    # 2️⃣ Montar prompt contextual
    prompt = build_rag_prompt(professor_input, docs)

    # 3️⃣ Se houver OpenAI API, gerar plano via LLM
    if OPENAI_API_KEY:
        try:
            import openai
            openai.api_key = OPENAI_API_KEY

            messages = [
                {"role": "system", "content": "Você é um assistente pedagógico técnico, empático e objetivo."},
                {"role": "user", "content": prompt},
            ]

            resp = openai.ChatCompletion.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.25,
                max_tokens=900,
            )

            text = resp["choices"][0]["message"]["content"].strip()

            # 🔎 Extrair JSON do texto
            try:
                parsed = json.loads(text)
                return parsed
            except Exception:
                m = re.search(r"\{.*\}", text, re.S)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except Exception:
                        pass

                # Fallback: gera uma resposta simples se JSON falhar
                return {
                    "titulo": "Plano adaptado (IA)",
                    "atividades": [
                        {"tipo": "leitura", "descricao": text[:300], "duracao_minutos": 20}
                    ],
                    "recomendacoes": ["Revisar manualmente antes do uso"],
                }

        except Exception as e:
            print("⚠️ Erro ao usar OpenAI:", e)

    # 4️⃣ Fallback determinístico se IA não disponível
    atividades = []
    for d in docs[:min(3, len(docs))]:
        txt = d.get("text", "")[:400]
        atividades.append({
            "tipo": "exercicio_baseado_em_historico",
            "descricao": f"Baseado no texto: {txt}",
            "duracao_minutos": 10,
        })

    if not atividades:
        atividades = [
            {"tipo": "leitura_guiada", "descricao": "Leitura assistida de frases curtas com apoio visual", "duracao_minutos": 15},
            {"tipo": "jogo_memoria", "descricao": "Atividade de associação entre palavras e imagens", "duracao_minutos": 10},
        ]

    plano = {
        "titulo": f"Plano adaptado - {conteudo}" if conteudo else "Plano adaptado",
        "atividades": atividades,
        "recomendacoes": [
            "Usar recursos visuais e auditivos",
            "Acompanhar com feedback contínuo do professor",
        ],
    }

    return plano


# ============================================================
# 🔹 COMPATIBILIDADE LEGADA
# ============================================================
async def gerar_plano_adaptado_compat(aluno_id, descricao_aluno, conteudo):
    """Mantém compatibilidade com chamadas antigas."""
    return await gerar_plano_adaptado(aluno_id, descricao_aluno, conteudo)
