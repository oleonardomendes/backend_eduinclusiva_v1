# EduInclusiva - Backend (FastAPI)
This is a PoC backend for the EduInclusiva project.
## Quick start (local)
1. Copy `.env.example` to `.env` and adjust variables.
2. Install dependencies:
   ```
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run:
   ```
   uvicorn app.main:app --reload
   ```
4. API docs available at http://localhost:8000/docs
## Notes
- By default the DB is sqlite (`./eduinclusiva.db`) for quick testing.
- To use OpenAI for AI generation set `OPENAI_API_KEY` in `.env`.



Observação: pytesseract requer que o Tesseract OCR esteja instalado no servidor (Linux: sudo apt-get install tesseract-ocr). Se não quiser instalar, o fluxo usará apenas PyMuPDF para texto extraído; o OCR é fallback.

Se você pretende usar Qdrant (recomendado em escala), precisa ter um endpoint Qdrant (cloud ou self-hosted) e definir QDRANT_URL e QDRANT_API_KEY no .env.



vector_store.py

Observações importantes sobre vector_store.py:

Se você configurar QDRANT_URL e tiver qdrant-client instalado, ele usará Qdrant (recomendado).

Caso contrário, o fallback usa sentence-transformers e NearestNeighbors (funciona bem para PoC e pequenas cargas).

embed_texts usa OpenAI Embeddings se OPENAI_API_KEY está definido; caso contrário, usa sentence-transformers.
