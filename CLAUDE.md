# CLAUDE.md — Backend EduInclusiva

## Visão Geral
Backend da plataforma EduInclusiva — sistema de gestão educacional inclusiva para alunos com necessidades educacionais especiais (NEE), aprovado pela Prefeitura Municipal de São Paulo. Gera planos pedagógicos personalizados via IA (RAG + OpenAI).

## Stack Técnica
- **Framework:** FastAPI (Python 3.11)
- **ORM:** SQLModel + SQLAlchemy
- **Banco:** PostgreSQL via Supabase (Transaction Pooler, porta 6543)
- **IA:** OpenAI GPT-4o + RAG (Retrieval-Augmented Generation)
- **Vetores:** Qdrant + sentence-transformers (CPU-only no Render)
- **Auth:** PyJWT (HS256) + passlib[bcrypt]
- **PDF/OCR:** PyMuPDF (fitz) + pytesseract + Pillow
- **Deploy:** Render (Docker) — URL: https://backend-eduinclusiva-v1.onrender.com
- **Docs:** https://backend-eduinclusiva-v1.onrender.com/docs

## Estrutura de Pastas
```
/                          ← WORKDIR do Docker (/app)
├── app/
│   ├── main.py            ← FastAPI app, CORS, routers, startup
│   ├── database.py        ← engine, get_session, init_db (create_all)
│   ├── models.py          ← SQLModel table models
│   ├── crud.py            ← funções de acesso ao banco
│   └── schemas.py         ← Pydantic schemas (PlanoGeradoIA, etc)
├── routes/
│   ├── __init__.py        ← from . import alunos, planos, ai, auth
│   ├── auth.py            ← /v1/auth/login, /v1/auth/register, /v1/auth/me
│   ├── alunos.py          ← /v1/alunos CRUD completo
│   ├── planos.py          ← /v1/planos
│   ├── ai.py              ← /v1/ai/gerar_plano, /v1/ai/historico/{aluno_id}
│   └── ingest.py          ← /v1/pdf/ingest
├── services/
│   ├── rag_service.py     ← gerar_plano_adaptado() via OpenAI + RAG
│   ├── vector_store.py    ← Qdrant + SentenceTransformer
│   ├── pdf_ingest.py      ← PyMuPDF + pytesseract
│   └── utils.py           ← helpers JSON
├── Dockerfile
└── requirements.txt
```

## Regra Crítica de Imports
`app/`, `routes/` e `services/` são **irmãos** sob o WORKDIR `/app`.
```python
# ✅ CORRETO
from app.models import Usuario, Aluno
from app.database import get_session
from app.crud import get_alunos
from services.rag_service import gerar_plano_adaptado
from routes.auth import get_current_user

# ❌ NUNCA USAR
from app.services.rag_service import ...
from app.routes.auth import ...
```

## Models (app/models.py)
```python
class Usuario(SQLModel, table=True):
    id: Optional[int]
    nome: str
    email: str          # unique
    senha_hash: Optional[str]
    papel: str          # "professor", "secretaria", "coordenadora", "familia", "admin", "gestor"
    criado_em: datetime
    alunos: List["Aluno"]  # relacionamento reverso

class Aluno(SQLModel, table=True):
    id: Optional[int]
    nome: str
    idade: Optional[int]
    necessidade: Optional[str]   # ex: "Autismo leve", "Dislexia", "TDAH"
    observacoes: Optional[str]
    escola: Optional[str]        # nome da escola
    sala: Optional[str]          # ex: "Sala A - 2º Ano"
    professor_id: Optional[int]  # FK → usuario.id
    criado_em: datetime
    planos: List["Plano"]

class Plano(SQLModel, table=True):
    id: Optional[int]
    aluno_id: int        # FK → aluno.id
    titulo: str
    atividades: str      # JSON string
    recomendacoes: Optional[str]  # JSON string
    criado_em: datetime
```

## Endpoints Disponíveis

### Auth — /v1/auth
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | /register | Cadastra usuário, retorna JWT |
| POST | /login | Login, retorna JWT |
| GET | /me | Retorna usuário autenticado |

### Alunos — /v1/alunos
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | / | Lista alunos (professor vê só os seus) |
| GET | /{id} | Busca aluno por ID |
| POST | / | Cria aluno (professor_id automático) |
| PUT | /{id} | Atualiza aluno |
| DELETE | /{id} | Remove aluno |

### IA — /v1/ai
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | /gerar_plano | Gera plano adaptado via RAG/OpenAI |
| GET | /historico/{aluno_id} | Histórico de planos do aluno |

### Planos — /v1/planos
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | /{aluno_id} | Lista planos de um aluno |

### Ingestão — /v1
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | /pdf/ingest | Upload e indexação de PDF no Qdrant |

## Autenticação
Todas as rotas (exceto /auth/login e /auth/register) exigem JWT no header:
```
Authorization: Bearer <token>
```

O guard `get_current_user` está em `routes/auth.py` e é importado via:
```python
from routes.auth import get_current_user
```

## Hierarquia de Acesso
```
secretaria/coordenadora → vê TODOS os alunos
professor               → vê APENAS os seus alunos (professor_id == user.id)
familia                 → acesso separado (portal da família)
```

Verificação no código:
```python
ROLES_GESTAO = {"secretary", "secretaria", "coordinator", "coordenadora", "admin", "gestor"}

papel = (current_user.papel or "").lower()
if papel in ROLES_GESTAO:
    return crud.get_alunos(session)  # todos
return crud.get_alunos(session, professor_id=current_user.id)  # só os seus
```

## Banco de Dados (Supabase)
- **URL de conexão:** Transaction Pooler com IPv4 habilitado, porta 6543
- **Formato:** `postgresql://postgres.PROJECT_ID:PASSWORD@aws-0-us-west-2.pooler.supabase.com:6543/postgres`
- **Migrations:** NÃO usa Alembic. Usa `SQLModel.metadata.create_all(engine)` no startup.
- **IMPORTANTE:** `create_all` NÃO adiciona colunas novas em tabelas existentes. Para isso use `ALTER TABLE` diretamente no Supabase SQL Editor.

## Variáveis de Ambiente (Render)
```
DATABASE_URL         = postgresql://... (Supabase Transaction Pooler)
ALLOWED_ORIGINS      = (não usado — usa ALLOW_ORIGIN_REGEX)
ALLOW_ORIGIN_REGEX   = https://.*\.vercel\.app$
SECRET_KEY           = chave JWT (mínimo 32 bytes recomendado)
OPENAI_API_KEY       = sk-...
QDRANT_URL           = URL do Qdrant
QDRANT_API_KEY       = chave do Qdrant
```

## CORS
Configurado em `app/main.py` via variáveis de ambiente:
- `ALLOW_ORIGIN_REGEX` → regex para liberar origens (ex: `https://.*\.vercel\.app$`)
- `ALLOWED_ORIGINS` → lista separada por vírgula
- `ALLOW_ALL_ORIGINS=true` → apenas para debug

## Docker
```dockerfile
WORKDIR /app
# CMD usa forma shell para expandir $PORT
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Campos que AINDA NÃO EXISTEM no banco (TODO)
Estes campos estão no frontend mockado mas não têm coluna no banco:
- `Aluno.foto` / `Aluno.avatar` (URL da foto)
- `Aluno.matricula` (número de matrícula)
- `Aluno.data_nascimento`
- `Aluno.genero`
- `Aluno.endereco`
- `Aluno.telefone_contato`
- `Aluno.contato_emergencia` (nome + telefone + parentesco)
- `Aluno.informacoes_medicas` (diagnóstico, alergias, medicamentos)
- `Aluno.progresso` (percentual geral)
- Atividades avulsas (separadas de planos)
- Comunicações professor-família

## Padrão de Desenvolvimento
1. Sempre proteger rotas com `Depends(get_current_user)`
2. Verificar permissão antes de retornar dados de aluno
3. Nunca expor `senha_hash` em responses
4. Serializar JSON fields (atividades, recomendacoes) antes de salvar
5. Usar `session.exec(select(...))` — padrão SQLModel, não `session.query()`

## Erros Comuns e Soluções
| Erro | Causa | Solução |
|------|-------|---------|
| `ModuleNotFoundError: app.services` | Import path errado | Usar `from services.x` |
| `column X does not exist` | Coluna nova não criada | `ALTER TABLE` no Supabase |
| `Network is unreachable` (porta 5432) | Supabase bloqueia porta direta | Usar porta 6543 (pooler) |
| `IndentationError` | Decorator entre `@router` e `def` | Mover docstring para dentro da função |
| `email-validator not installed` | Pydantic EmailStr sem dependência | Adicionar `email-validator` no requirements.txt |
