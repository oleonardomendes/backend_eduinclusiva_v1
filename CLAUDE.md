# CLAUDE.md — EduInclusiva Backend

## Visão Geral
Plataforma educacional para alunos com necessidades educacionais especiais, aprovada por governo municipal.
Backend API REST construído com FastAPI + SQLModel + PostgreSQL.

---

## Stack

- **Framework:** FastAPI
- **ORM:** SQLModel
- **Banco de dados:** PostgreSQL via Supabase
- **Vetores:** Qdrant + sentence-transformers
- **IA:** OpenAI API
- **Auth:** PyJWT
- **PDF/OCR:** PyMuPDF + pytesseract
- **Hospedagem:** Render (Docker)

---

## Estrutura de Diretórios

```
WORKDIR/
├── app/          # modelos, schemas, config, db
├── routes/       # endpoints FastAPI
├── services/     # lógica de negócio
├── Dockerfile
└── requirements.txt
```

> ⚠️ `app/`, `routes/` e `services/` são IRMÃOS sob o WORKDIR Docker.

---

## Regras Críticas de Import

```python
# ✅ CORRETO
from app.models import Aluno
from app.database import get_session
from services.auth_service import criar_token
from routes.alunos import router

# ❌ NUNCA FAZER
from app.services.auth_service import ...
from app.routes.alunos import ...
```

---

## Banco de Dados — Supabase

- Usar sempre o **Transaction Pooler URL** na porta **6543** com IPv4
- A variável `DATABASE_URL` é obrigatória no Render — sem ela cai para SQLite efêmero
- Conexão: `postgresql+psycopg2://...`

### Modelo Aluno (campos relevantes)
```python
class Aluno(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    professor_id: Optional[int] = Field(foreign_key="usuario.id")
    escola: Optional[str]
    sala: Optional[str]
    # demais campos...
```

---

## Autenticação e Roles

### Roles do backend
| Role backend   | Descrição                        |
|----------------|----------------------------------|
| `professor`    | Vê apenas seus próprios alunos   |
| `secretaria`   | Vê todos os alunos               |
| `coordenadora` | Vê todos os alunos               |
| `familia`      | Acesso restrito ao próprio aluno |

- Auth via JWT guards nas rotas protegidas
- Professores filtrados por `professor_id`; coordenadoras e secretárias veem tudo

---

## CORS

- Configurado via `ALLOW_ORIGIN_REGEX` para aceitar origens do Vercel
- Nunca usar wildcard `*` em produção

---

## Deploy — Render

- Runtime: **Docker**
- Variáveis de ambiente obrigatórias:
  - `DATABASE_URL` (Transaction Pooler, porta 6543)
  - `SECRET_KEY`
  - `OPENAI_API_KEY`
  - `ALLOW_ORIGIN_REGEX`
- Erros comuns já resolvidos:
  - `email-validator` deve estar no `requirements.txt`
  - `PyJWT` deve estar no `requirements.txt` (não apenas `jwt`)
  - Indentação Python causa falha silenciosa no Render

---

## Comandos Úteis

```bash
# Rodar localmente
uvicorn app.main:app --reload

# Testar conexão com banco
python -c "from app.database import engine; print('OK')"

# Aplicar migration manual (Supabase)
# Usar ALTER TABLE direto no SQL Editor do Supabase
```

---

## Padrões de Código

- Sempre usar `Optional` nos campos que podem ser nulos
- Schemas separados para criação e leitura (ex: `AlunoCreate`, `AlunoRead`)
- Lógica de negócio em `services/`, não nas `routes/`
- Tratar erros com `HTTPException` com status codes corretos
- Nunca expor stack trace em produção
