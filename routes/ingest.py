# app/routes/ingest.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional
import os, shutil, uuid, logging
from services.pdf_ingest import prepare_document_for_index
from services.vector_store import get_vector_store

# 🔧 Inicializa o router
router = APIRouter(prefix="/pdf", tags=["Upload & Ingestão"])

# 📂 Diretório de upload temporário
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/eduinclusiva_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 🧠 Inicializa logger
logger = logging.getLogger("uvicorn")

@router.post("/upload")
async def upload_pdf(
    aluno_id: str = Form(..., description="ID do aluno dono do documento"),
    competencia: Optional[str] = Form(None, description="Competência ou habilidade trabalhada"),
    bimestre: Optional[str] = Form(None, description="Período bimestral (ex: 1º bimestre)"),
    titulo: Optional[str] = Form(None, description="Título ou nome do documento"),
    file: UploadFile = File(...)
):
    """
    📄 Faz upload de um PDF e envia o conteúdo para o indexador vetorial (RAG).
    
    - Salva o arquivo temporariamente em /tmp
    - Extrai o texto (via pdf_ingest)
    - Gera chunks e insere no vector store para buscas futuras
    
    Retorna:
    {
      "status": "ok",
      "aluno_id": "...",
      "documento": "nome_arquivo.pdf",
      "chunks_indexados": 12
    }
    """
    # ⚠️ Validação básica
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    if file.size == 0:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

    # 🧾 Gera nome único e salva o arquivo
    filename = f"{uuid.uuid4().hex}_{file.filename.replace(' ', '_')}"
    dest_path = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"📥 Arquivo salvo: {dest_path}")
    except Exception as e:
        logger.error(f"Erro ao salvar arquivo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar o arquivo: {e}")

    # 🧩 Metadados associados
    metadata = {
        "aluno_id": aluno_id,
        "competencia": competencia,
        "bimestre": bimestre,
        "titulo": titulo or file.filename,
        "path": dest_path
    }

    try:
        # 🔍 Extrai texto e gera chunks
        docs = prepare_document_for_index(dest_path, metadata)
        logger.info(f"🧠 Documento preparado — {len(docs)} chunks extraídos.")

        # 💾 Indexa no vector store
        store = get_vector_store()
        store.upsert_many(docs)

        logger.info(f"✅ Documento indexado com sucesso para aluno {aluno_id}.")
        return {
            "status": "ok",
            "aluno_id": aluno_id,
            "documento": filename,
            "chunks_indexados": len(docs),
            "metadata": metadata
        }

    except Exception as e:
        logger.error(f"❌ Erro durante a indexação: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar e indexar o PDF: {e}")
