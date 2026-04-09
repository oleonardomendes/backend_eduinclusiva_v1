# routes/publico.py
"""
Endpoints públicos (sem autenticação) — preview de recursos para demonstração.
"""
import os
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from groq import Groq
from services.ai_service import _limpar_json_resposta

router = APIRouter()
logger = logging.getLogger("uvicorn")


# =========================================================
# Schema
# =========================================================

class PreviewRequest(BaseModel):
    nome: str
    idade: Optional[int] = None
    condicao: Optional[str] = None
    area: str = "Leitura"
    duracao_minutos: int = 15


# =========================================================
# POST /preview-atividade — prévia pública (sem auth)
# =========================================================

@router.post("/preview-atividade")
def preview_atividade(body: PreviewRequest):
    """
    Gera uma prévia parcial de atividade sem autenticação.
    Retorna título, objetivo e os primeiros passos — ideal para demonstração da plataforma.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Serviço de IA indisponível no momento."
        )

    prompt = f"""Você é um especialista em educação inclusiva.

Crie UMA atividade curta e simples para ser realizada em casa.

CRIANÇA:
- Nome: {body.nome}
- Idade: {body.idade or "Não informada"} anos
- Condição: {body.condicao or "Não informada"}
- Área: {body.area}
- Duração: {body.duracao_minutos} minutos

Responda APENAS com JSON válido:
{{
  "titulo": "string",
  "objetivo": "string",
  "passo_a_passo": ["string (apenas 3 passos)"],
  "materiais": ["string (até 3 itens comuns)"]
}}"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        texto = response.choices[0].message.content
        raw = _limpar_json_resposta(texto)
        resultado = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Falha ao gerar prévia. Tente novamente.")
    except Exception as e:
        logger.error(f"Erro no preview-atividade: {e}")
        raise HTTPException(status_code=500, detail="Serviço temporariamente indisponível.")

    return {
        "preview": True,
        "titulo": resultado.get("titulo"),
        "objetivo": resultado.get("objetivo"),
        "passo_a_passo": (resultado.get("passo_a_passo") or [])[:3],
        "materiais": resultado.get("materiais"),
        "aviso": (
            "Esta é uma prévia gratuita. "
            "Cadastre-se para gerar atividades completas personalizadas para seu filho."
        ),
    }
