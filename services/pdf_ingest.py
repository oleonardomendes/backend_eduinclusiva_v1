# app/services/pdf_ingest.py
import fitz  # pymupdf
import io
import os
from typing import Dict, Any, Optional, List
from PIL import Image
import pytesseract
import uuid

def extract_text_from_pdf(path: str) -> str:
    """Extrai o texto de um PDF, com fallback OCR para páginas escaneadas."""
    doc = fitz.open(path)
    texts = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        text = page.get_text("text").strip()
        if text:
            texts.append(text)
        else:
            # Fallback OCR
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            try:
                img = Image.open(io.BytesIO(img_bytes))
                ocr_text = pytesseract.image_to_string(img, lang="por")
                if ocr_text:
                    texts.append(ocr_text)
            except Exception:
                pass
    doc.close()
    return "\n\n".join(texts)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """
    Divide o texto em chunks de tamanho fixo, com sobreposição.
    Ex: chunk_size=1200 caracteres, overlap=200.
    """
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start += chunk_size - overlap

    return chunks


def prepare_document_for_index(path: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Retorna uma lista de chunks prontos para indexar no vector store.
    Cada chunk contém:
    { id, text, metadata: {..., chunk_id, chunk_total} }
    """
    if metadata is None:
        metadata = {}

    text = extract_text_from_pdf(path)
    chunks = chunk_text(text)
    doc_id = str(uuid.uuid4())

    indexed_docs = []
    for i, chunk in enumerate(chunks):
        meta = metadata.copy()
        meta["doc_id"] = doc_id
        meta["chunk_id"] = i + 1
        meta["chunk_total"] = len(chunks)
        indexed_docs.append({"id": f"{doc_id}_{i+1}", "text": chunk, "metadata": meta})

    return indexed_docs
