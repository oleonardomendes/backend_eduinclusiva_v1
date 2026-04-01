# CLAUDE.md — Backend EduInclusiva
> Última atualização: Abril 2026

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
│   └── schemas.py         ← Pydantic schemas (PlanoGeradoIA, AlunoUpdate, etc)
├── routes/
│   ├── __init__.py        ← from . import alunos, planos, ai, auth
│   ├── auth.py            ← /v1/auth/login, /v1/auth/register, /v1/auth/me
│   ├── alunos.py          ← /v1/alunos CRUD completo + /v1/alunos/{id}/metricas
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

### Usuario
```python
class Usuario(SQLModel, table=True):
    id: Optional[int]
    nome: str
    email: str          # unique
    senha_hash: Optional[str]
    papel: str          # "professor", "secretaria", "coordenadora", "familia", "admin", "gestor"
    criado_em: datetime
    alunos: List["Aluno"]  # relacionamento reverso
```

### Aluno (campos completos)
```python
class Aluno(AlunoBase, table=True):
    # Campos básicos
    id: Optional[int]
    nome: str
    idade: Optional[int]
    necessidade: Optional[str]    # "Autismo leve", "Dislexia", "TDAH"
    observacoes: Optional[str]
    escola: Optional[str]
    sala: Optional[str]           # "Sala A - 2º Ano"
    professor_id: Optional[int]   # FK → usuario.id
    criado_em: datetime

    # Campos de perfil (adicionados em Abril 2026)
    foto: Optional[str]           # URL da foto
    matricula: Optional[str]
    data_nascimento: Optional[date]
    genero: Optional[str]         # "Masculino", "Feminino", "Outro"
    telefone_contato: Optional[str]
    contato_emergencia_nome: Optional[str]
    contato_emergencia_telefone: Optional[str]
    contato_emergencia_parentesco: Optional[str]
    informacoes_medicas: Optional[str]  # JSON string

    # Campos acadêmicos (adicionados em Abril 2026)
    nivel_aprendizado: Optional[str]     # "Básico", "Intermediário", "Avançado"
    objetivos_aprendizado: Optional[str]
    alergias: Optional[str]
    medicamentos: Optional[str]
    endereco: Optional[str]
    horario_aulas: Optional[str]         # "Manhã (7h-12h)"
    progresso_geral: Optional[int]       # 0 a 100
```

### Plano
```python
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
| GET | /{id} | Busca aluno por ID + professor_nome |
| POST | / | Cria aluno (professor_id automático) |
| PUT | /{id} | Atualiza aluno (AlunoUpdate tipado) |
| DELETE | /{id} | Remove aluno |
| GET | /{id}/metricas | Retorna progresso_geral, nivel_aprendizado, ultima_avaliacao, total_planos |

### IA — /v1/ai
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | /gerar_plano | Gera plano adaptado via RAG/OpenAI |
| GET | /historico/{aluno_id} | Histórico de planos IA do aluno |

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

Guard de autenticação em `routes/auth.py`:
```python
from routes.auth import get_current_user
```

## Hierarquia de Acesso
```
secretaria/coordenadora → vê TODOS os alunos
professor               → vê APENAS os seus alunos (professor_id == user.id)
familia                 → acesso separado (portal da família)
```

```python
ROLES_GESTAO = {"secretary", "secretaria", "coordinator", "coordenadora", "admin", "gestor"}

papel = (current_user.papel or "").lower()
if papel in ROLES_GESTAO:
    return crud.get_alunos(session)
return crud.get_alunos(session, professor_id=current_user.id)
```

## Banco de Dados (Supabase)
- **URL:** Transaction Pooler com IPv4, porta 6543
- **Formato:** `postgresql://postgres.PROJECT_ID:PASSWORD@aws-0-us-west-2.pooler.supabase.com:6543/postgres`
- **Migrations:** NÃO usa Alembic. Usa `SQLModel.metadata.create_all(engine)` no startup.
- **⚠️ IMPORTANTE:** `create_all` NÃO adiciona colunas novas em tabelas existentes.
  Para novos campos sempre use `ALTER TABLE` no Supabase SQL Editor.

### SQL aplicado até agora
```sql
-- Abril 2026 — campos de perfil completo do aluno
ALTER TABLE aluno
  ADD COLUMN IF NOT EXISTS foto                          TEXT,
  ADD COLUMN IF NOT EXISTS matricula                     TEXT,
  ADD COLUMN IF NOT EXISTS data_nascimento               DATE,
  ADD COLUMN IF NOT EXISTS genero                        TEXT,
  ADD COLUMN IF NOT EXISTS telefone_contato              TEXT,
  ADD COLUMN IF NOT EXISTS contato_emergencia_nome       TEXT,
  ADD COLUMN IF NOT EXISTS contato_emergencia_telefone   TEXT,
  ADD COLUMN IF NOT EXISTS contato_emergencia_parentesco TEXT,
  ADD COLUMN IF NOT EXISTS informacoes_medicas           TEXT,
  ADD COLUMN IF NOT EXISTS nivel_aprendizado             TEXT,
  ADD COLUMN IF NOT EXISTS objetivos_aprendizado         TEXT,
  ADD COLUMN IF NOT EXISTS alergias                      TEXT,
  ADD COLUMN IF NOT EXISTS medicamentos                  TEXT,
  ADD COLUMN IF NOT EXISTS endereco                      TEXT,
  ADD COLUMN IF NOT EXISTS horario_aulas                 TEXT,
  ADD COLUMN IF NOT EXISTS progresso_geral               INTEGER;

-- professor_id e escola/sala (adicionados anteriormente)
ALTER TABLE aluno
  ADD COLUMN IF NOT EXISTS escola       TEXT,
  ADD COLUMN IF NOT EXISTS sala         TEXT,
  ADD COLUMN IF NOT EXISTS professor_id INTEGER REFERENCES usuario(id);

CREATE INDEX IF NOT EXISTS idx_aluno_professor_id ON aluno(professor_id);
```

## Variáveis de Ambiente (Render)
```
DATABASE_URL        = postgresql://... (Supabase Transaction Pooler porta 6543)
ALLOW_ORIGIN_REGEX  = https://.*\.vercel\.app$
SECRET_KEY          = chave JWT (mínimo 32 bytes)
OPENAI_API_KEY      = sk-...
QDRANT_URL          = URL do Qdrant
QDRANT_API_KEY      = chave do Qdrant
```

## CORS (app/main.py)
- `ALLOW_ORIGIN_REGEX` → libera todas as URLs do Vercel automaticamente
- `ALLOWED_ORIGINS` → lista separada por vírgula (alternativa)
- `ALLOW_ALL_ORIGINS=true` → apenas para debug local

## Docker
```dockerfile
WORKDIR /app
# forma shell para expandir $PORT
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## O que ainda NÃO existe no backend (TODO)
Campos/endpoints que o frontend precisa mas ainda não foram implementados:

| Campo/Endpoint | Usado em | Prioridade |
|----------------|----------|------------|
| `student.lastAssessment` / `ultima_avaliacao` real | student-profile | Alta |
| `GET /v1/escolas/` | secretary-dashboard | Alta |
| `GET /v1/metricas/escola/{id}` | secretary + coordinator | Alta |
| `GET /v1/turmas/` | coordinator-dashboard | Alta |
| `GET /v1/turmas/{id}/alunos` | coordinator-dashboard | Alta |
| `GET /v1/metricas/rede/` | secretary-dashboard | Alta |
| `GET /v1/alunos/?responsavel_id={id}` | parent-portal | Alta |
| `GET /v1/mensagens/` | comunicação em todas as páginas | Alta |
| `GET /v1/comunicados/` | parent-portal + coordinator | Média |
| `GET /v1/metricas/aluno/{id}/progresso` | progresso por disciplina | Média |
| `GET /v1/eventos/` | calendário | Baixa |
| `GET /v1/recursos/` | biblioteca educativa | Baixa |

## Usuário de Teste
```
Email: leo@eduinclusiva.com
Senha: Teste123!
Role:  professor
ID:    1
```

## Padrões de Desenvolvimento
1. Sempre proteger rotas com `Depends(get_current_user)`
2. Verificar permissão antes de retornar dados de aluno
3. Nunca expor `senha_hash` em responses
4. Serializar JSON fields (atividades, recomendacoes) antes de salvar
5. Usar `session.exec(select(...))` — padrão SQLModel, não `session.query()`
6. PUT usa schema `AlunoUpdate` com `.model_dump(exclude_unset=True)`

## Erros Comuns e Soluções
| Erro | Causa | Solução |
|------|-------|---------|
| `ModuleNotFoundError: app.services` | Import path errado | Usar `from services.x` |
| `column X does not exist` | Coluna nova não criada | `ALTER TABLE` no Supabase |
| `Network is unreachable` (porta 5432) | Supabase bloqueia porta direta | Usar porta 6543 (pooler) |
| `IndentationError` | Decorator entre `@router` e `def` | Mover docstring para dentro da função |
| `email-validator not installed` | Pydantic EmailStr sem dependência | Adicionar ao requirements.txt |
| JWT key too short warning | SECRET_KEY < 32 bytes | Usar chave com 32+ bytes |
