# app/routes/ai.py
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session
from typing import Dict
from app.database import get_session
from app.schemas import PlanoGeradoIA, PlanoCreate, PlanoRead
from app.services.rag_service import gerar_plano_adaptado
from app.crud import create_plano
import json

router = APIRouter()

@router.post("/gerar_plano", response_model=PlanoGeradoIA)
async def gerar_plano_ia(
    payload: Dict,
    session: Session = Depends(get_session)
):
    """
    Endpoint para gerar plano adaptado via IA.
    
    Exemplo de entrada (JSON):
    {
        "aluno_id": 1,
        "descricao_aluno": "Criança de 9 anos com dislexia leve, dificuldades em leitura e escrita.",
        "conteudo": "Leitura de textos narrativos",
        "materia": "Português",
        "competencia": "Leitura e interpretação de textos"
    }
    
    Saída (JSON):
    {
        "titulo": "Plano adaptado - Leitura e Interpretação",
        "atividades": [...],
        "recomendacoes": [...]
    }
    """
    aluno_id = payload.get("aluno_id")
    descricao_aluno = payload.get("descricao_aluno")
    conteudo = payload.get("conteudo")
    materia = payload.get("materia")
    competencia = payload.get("competencia")

    if not aluno_id or not descricao_aluno or not conteudo:
        raise HTTPException(status_code=400, detail="Campos obrigatórios ausentes (aluno_id, descricao_aluno, conteudo).")

    try:
        # Gera o plano via RAG/LLM
        plano_data = await gerar_plano_adaptado(
            aluno_id=aluno_id,
            descricao_aluno=descricao_aluno,
            conteudo=conteudo,
            materia=materia,
            competencia=competencia
        )

        # Garantir formato consistente
        titulo = plano_data.get("titulo", f"Plano adaptado - {conteudo}")
        atividades = plano_data.get("atividades", [])
        recomendacoes = plano_data.get("recomendacoes", [])

        # Salvar no banco (para histórico do aluno)
        plano_db = PlanoCreate(
            aluno_id=aluno_id,
            titulo=titulo,
            atividades=json.dumps(atividades, ensure_ascii=False),
            recomendacoes=json.dumps(recomendacoes, ensure_ascii=False)
        )
        plano_criado = create_plano(session, plano_db)

        return PlanoGeradoIA(
            titulo=titulo,
            atividades=atividades,
            recomendacoes=recomendacoes
        )

    except Exception as e:
        print(f"Erro ao gerar plano via IA: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar plano: {str(e)}")

        @router.get("/historico/{aluno_id}", response_model=list[PlanoRead])
        def listar_planos_gerados_por_aluno(aluno_id: int, session: Session = Depends(get_session)):
    """
    Retorna o histórico de planos (incluindo os gerados por IA)
    vinculados a um aluno específico.

    Exemplo de uso:
      GET /v1/ai/historico/1

    Resposta:
    [
      {
        "id": 1,
        "aluno_id": 1,
        "titulo": "Plano adaptado - Matemática",
        "atividades": [...],
        "recomendacoes": [...],
        "criado_em": "2025-11-07T14:00:00"
      },
      ...
    ]
    """
    try:
        planos = session.query(
            # ORM compatível com SQLModel
            # usa o modelo Plano definido em models.py
        ).filter_by(aluno_id=aluno_id).order_by("criado_em").all()

        if not planos:
            raise HTTPException(status_code=404, detail="Nenhum plano encontrado para este aluno.")

        # Converter atividades/recomendações de JSON para dict/lista
        for plano in planos:
            try:
                if isinstance(plano.atividades, str):
                    import json
                    plano.atividades = json.loads(plano.atividades)
                if isinstance(plano.recomendacoes, str):
                    plano.recomendacoes = json.loads(plano.recomendacoes)
            except Exception:
                pass

        return planos

    except Exception as e:
        print(f"Erro ao buscar histórico de planos: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar histórico de planos.")

