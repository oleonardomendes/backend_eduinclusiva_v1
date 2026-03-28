# app/services/vector_store.py
import os
import numpy as np
from typing import List, Dict, Any, Optional

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

try:
    from qdrant_client import QdrantClient
    QDRANT_AVAILABLE = True
except Exception:
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.neighbors import NearestNeighbors
    SENTENCE_AVAILABLE = True
except Exception:
    SENTENCE_AVAILABLE = False


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Gera embeddings via OpenAI (preferencial) ou local (sentence-transformers)."""
    if OPENAI_API_KEY:
        import openai
        openai.api_key = OPENAI_API_KEY
        resp = openai.Embedding.create(
            model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            input=texts
        )
        return [d["embedding"] for d in resp["data"]]
    else:
        if not SENTENCE_AVAILABLE:
            raise RuntimeError("No embedding backend available. Install sentence-transformers or set OPENAI_API_KEY.")
        model = SentenceTransformer(os.getenv("SENTENCE_MODEL", "all-MiniLM-L6-v2"))
        return model.encode(texts, show_progress_bar=False).tolist()


class VectorStore:
    def __init__(self, collection_name: str = "eduinclusiva"):
        self.collection_name = collection_name
        if QDRANT_AVAILABLE and QDRANT_URL:
            self.client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            try:
                self.client.recreate_collection(
                    collection_name=self.collection_name,
                    vectors_config={"size": 1536, "distance": "Cosine"}
                )
            except Exception:
                pass
            self.backend = "qdrant"
        else:
            self.backend = "local"
            self.docs: List[Dict[str, Any]] = []
            self.embeddings = None
            self.nn = None

    def upsert_many(self, docs: List[Dict[str, Any]]):
        """Indexa vários documentos/chunks de uma vez."""
        texts = [d["text"] for d in docs]
        embeddings = embed_texts(texts)
        if self.backend == "qdrant":
            payloads = [d["metadata"] for d in docs]
            points = [{"id": d["id"], "vector": e, "payload": p} for d, e, p in zip(docs, embeddings, payloads)]
            self.client.upsert(collection_name=self.collection_name, points=points)
        else:
            for d, e in zip(docs, embeddings):
                d["embedding"] = e
            self.docs.extend(docs)
            self._rebuild_index()

    def _rebuild_index(self):
        if not self.docs:
            return
        X = np.array([d["embedding"] for d in self.docs])
        self.nn = NearestNeighbors(n_neighbors=min(10, len(self.docs)), metric="cosine")
        self.nn.fit(X)
        self.embeddings = X

    def query(self, query_text: str, top_k: int = 5, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Busca vetorial e retorna os top_k resultados mais similares."""
        q_emb = embed_texts([query_text])[0]
        if self.backend == "qdrant":
            results = self.client.search(collection_name=self.collection_name, query_vector=q_emb, limit=top_k, with_payload=True)
            return [{"id": str(r.id), "text": r.payload.get("text", ""), "metadata": r.payload, "score": float(r.score)} for r in results]
        else:
            if not self.nn:
                return []
            dist, idx = self.nn.kneighbors([q_emb], n_neighbors=min(top_k, len(self.docs)))
            out = []
            for d, i in zip(dist[0], idx[0]):
                doc = self.docs[i]
                if metadata_filter:
                    ok = all(doc["metadata"].get(k) == v for k, v in metadata_filter.items())
                    if not ok:
                        continue
                out.append({"id": doc["id"], "text": doc["text"], "metadata": doc["metadata"], "score": float(d)})
            return out


_store: Optional[VectorStore] = None
def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(collection_name=os.getenv("VECTOR_COLLECTION", "eduinclusiva"))
    return _store
