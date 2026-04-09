# CLAUDE.md — Backend EduInclusiva
> Última atualização: Abril 2026 (revisado)

## Visão Geral
Backend da plataforma EduInclusiva — sistema de gestão educacional inclusiva para alunos com necessidades educacionais especiais (NEE), aprovado pela Prefeitura Municipal de São Paulo. Gera atividades pedagógicas personalizadas via IA (Groq + sistema de 3 camadas).

## Stack Técnica
- **Framework:** FastAPI (Python 3.11)
- **ORM:** SQLModel + SQLAlchemy
- **Banco:** PostgreSQL via Supabase (Transaction Pooler, porta 6543)
- **IA principal:** Groq (llama-3.3-70b-versatile) — geração de atividades
- **IA legada:** OpenAI GPT-4o + RAG (planos adaptados — mantido)
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
│   ├── __init__.py        ← from . import alunos, planos, ai, auth, metas, avaliacoes
│   ├── auth.py            ← /v1/auth/login, /v1/auth/register, /v1/auth/me
│   ├── alunos.py          ← /v1/alunos CRUD completo + /v1/alunos/{id}/metricas
│   ├── planos.py          ← /v1/planos
│   ├── ai.py              ← /v1/ai/* (planos, atividades, templates, conclusões)
│   ├── metas.py           ← /v1/metas CRUD
│   ├── avaliacoes.py      ← /v1/avaliacoes CRUD + /resumo/
│   └── ingest.py          ← /v1/pdf/ingest
├── services/
│   ├── ai_service.py      ← buscar_ou_gerar_atividade() via Groq (3 camadas)
│   ├── rag_service.py     ← gerar_plano_adaptado() via OpenAI + RAG (legado)
│   ├── vector_store.py    ← Qdrant + SentenceTransformer
│   ├── pdf_ingest.py      ← PyMuPDF + pytesseract
│   └── utils.py           ← helpers JSON
├── scripts/
│   └── seed.py            ← popula banco com dados de exemplo
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
from services.ai_service import buscar_ou_gerar_atividade
from services.rag_service import gerar_plano_adaptado
from routes.auth import get_current_user

# ❌ NUNCA USAR
from app.services.ai_service import ...
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

    # Campos de perfil pedagógico (adicionados em Abril 2026)
    estilo_aprendizagem: Optional[str]   # "Visual", "Auditivo", "Cinestésico", "Visual-Cinestésico", "Misto"
    grau_necessidade: Optional[str]      # "Leve", "Moderado", "Severo"
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

### Meta
```python
class Meta(SQLModel, table=True):
    id: Optional[int]
    professor_id: int    # FK → usuario.id
    sala: Optional[str]
    bimestre: int        # 1, 2, 3 ou 4
    ano: int
    meta_progresso: int  # 0 a 100
    descricao: Optional[str]
    criado_em: datetime
```

### Avaliacao
```python
class Avaliacao(SQLModel, table=True):
    id: Optional[int]
    aluno_id: int        # FK → aluno.id
    professor_id: int    # FK → usuario.id
    bimestre: int
    ano: int
    nota: float          # 0.0 a 10.0
    progresso: Optional[int]   # 0 a 100
    observacoes: Optional[str]
    criado_em: datetime
```

### AtividadeGerada
```python
class AtividadeGerada(SQLModel, table=True):
    id: Optional[int]
    aluno_id: int        # FK → aluno.id
    professor_id: int    # FK → usuario.id
    titulo: str
    objetivo: Optional[str]
    duracao_minutos: Optional[int]
    dificuldade: Optional[str]
    materiais: Optional[str]           # JSON list
    passo_a_passo: Optional[str]       # JSON list
    adaptacoes: Optional[str]          # JSON list
    criterios_avaliacao: Optional[str] # JSON list
    justificativa: Optional[str]
    bimestre: Optional[int]
    ano: Optional[int]
    disciplina: Optional[str]
    tipo_atividade: Optional[str]
    instrucao_professor: Optional[str]
    instrucao_familia: Optional[str]
    conteudo_atividade: Optional[str]
    tags: Optional[str]                # JSON list
    parametros_professor: Optional[str] # JSON dict
    reutilizavel: bool                 # default True
    necessidade_atendida: Optional[str]
    concluida: bool                    # default False
    concluida_em: Optional[datetime]
    criado_em: datetime
```

### AtividadeTemplate
```python
class AtividadeTemplate(SQLModel, table=True):
    # Biblioteca de atividades pré-cadastradas pelo professor/admin
    id: Optional[int]
    titulo: str
    descricao: Optional[str]
    disciplina: Optional[str]
    tipo_atividade: Optional[str]
    nivel_dificuldade: Optional[str]
    nivel_aprendizado: Optional[str]
    duracao_minutos: Optional[int]
    necessidades_alvo: Optional[str]   # JSON list de NEE compatíveis
    objetivo: Optional[str]
    instrucao_professor: Optional[str]
    instrucao_familia: Optional[str]
    conteudo_atividade: Optional[str]
    materiais: Optional[str]           # JSON list
    passo_a_passo: Optional[str]       # JSON list
    adaptacoes: Optional[str]          # JSON list
    criterios_avaliacao: Optional[str] # JSON list
    tags: Optional[str]                # JSON list
    ativo: bool                        # default True
    criado_em: datetime
```

### ConclusaoAtividade
```python
class ConclusaoAtividade(SQLModel, table=True):
    # Registro de conclusão com avaliação por competências
    id: Optional[int]
    atividade_id: int    # FK → atividadegerada.id
    aluno_id: int        # FK → aluno.id
    professor_id: int    # FK → usuario.id
    observacoes: Optional[str]
    nota_comunicacao: Optional[float]       # 0.0 a 10.0
    nota_coordenacao_motora: Optional[float]
    nota_cognicao: Optional[float]
    nota_socializacao: Optional[float]
    nota_autonomia: Optional[float]
    nota_linguagem: Optional[float]
    nota_geral: Optional[float]            # média calculada automaticamente
    competencias_trabalhadas: Optional[str] # JSON list
    concluido_em: datetime
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

### Metas — /v1/metas
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | / | Cria meta (professor_id automático do token) |
| GET | / | Lista metas do professor logado (?ano=&bimestre=) |
| PUT | /{id} | Atualiza meta (só o dono) |
| DELETE | /{id} | Remove meta (só o dono) |

### Avaliações — /v1/avaliacoes
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | / | Cria avaliação (professor_id automático) |
| GET | / | Lista avaliações (?aluno_id=&ano=&bimestre=) |
| GET | /resumo/ | Progresso médio por bimestre (?ano=) |
| PUT | /{id} | Atualiza avaliação (só o dono) |

### IA — /v1/ai
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | /gerar_plano | Gera plano adaptado via RAG/OpenAI (legado) |
| GET | /historico/{aluno_id} | Histórico de planos do aluno |
| POST | /gerar_atividade | Gera atividade via 3 camadas (Groq) |
| GET | /atividades/{aluno_id} | Lista atividades geradas do aluno |
| GET | /templates/ | Lista templates ativos (?necessidade=&nivel=) |
| POST | /templates/ | Cria template de atividade |
| PATCH | /atividades/{id}/concluir | Conclui atividade com notas por competência |
| GET | /atividades/{aluno_id}/conclusoes | Histórico de conclusões do aluno |

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

## Serviço de IA (services/ai_service.py)

**Provedor:** Groq — modelo `llama-3.3-70b-versatile`
**Variável:** `GROQ_API_KEY`
**Função principal:** `buscar_ou_gerar_atividade(aluno_id, professor_id, parametros, session)`

### Busca em 3 Camadas
```
Camada 1 — Template pré-cadastrado (AtividadeTemplate)
  → Verifica ativo=True, necessidade em necessidades_alvo, nivel_dificuldade
  → Se encontrar: retorna {"fonte": "template", "atividade": ...}

Camada 2 — IA reutilizável (AtividadeGerada de outro aluno)
  → Score de compatibilidade (mínimo 70 para reutilizar):
      +30  mesma necessidade_atendida
      +25  mesmo grau_necessidade (via parametros_professor)
      +25  estilo_aprendizagem do aluno presente nas tags
      +20  mesmo nivel_dificuldade (só se informado)
  → Se score >= 70: retorna {"fonte": "ia_reutilizada", "atividade": ...}

Camada 3 — Geração nova via Groq
  → Monta prompt com perfil completo + situação pedagógica + parâmetros
  → Salva como AtividadeGerada (reutilizavel=True)
  → Retorna {"fonte": "ia_nova", "atividade": ...}
```

### Contexto usado no prompt
- Perfil do aluno: nome, idade, necessidade, observacoes, nivel_aprendizado,
  objetivos_aprendizado, progresso_geral, sala, estilo_aprendizagem, grau_necessidade
- Série/ano escolar e referência curricular
- Situação pedagógica: bimestre atual, meta, progresso real médio, gap
- Histórico: últimos 3 títulos de planos do aluno
- Parâmetros do professor: titulo, disciplina, tipo_atividade, nivel_dificuldade,
  duracao_minutos, descricao, objetivos

### Conclusão de Atividade
`PATCH /v1/ai/atividades/{id}/concluir`
- Calcula `nota_geral` = média das competências preenchidas
- Atualiza `progresso_geral` do aluno:
  - `nota_geral >= 7.0` → +5% (máx 100)
  - `nota_geral >= 5.0` → +2% (máx 100)
  - `nota_geral < 5.0` → sem alteração
  - Sem nota (só concluiu) → +1%

## Banco de Dados (Supabase)
- **URL:** Transaction Pooler com IPv4, porta 6543
- **Formato:** `postgresql://postgres.PROJECT_ID:PASSWORD@aws-0-us-west-2.pooler.supabase.com:6543/postgres`
- **Migrations:** NÃO usa Alembic. Usa `SQLModel.metadata.create_all(engine)` no startup.
- **⚠️ IMPORTANTE:** `create_all` NÃO adiciona colunas novas em tabelas existentes.
  Para novos campos sempre use `ALTER TABLE` no Supabase SQL Editor.

### SQL aplicado até agora
```sql
-- Campos de perfil completo do aluno
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
  ADD COLUMN IF NOT EXISTS progresso_geral               INTEGER,
  ADD COLUMN IF NOT EXISTS estilo_aprendizagem           TEXT,
  ADD COLUMN IF NOT EXISTS grau_necessidade              TEXT;

-- professor_id e escola/sala
ALTER TABLE aluno
  ADD COLUMN IF NOT EXISTS escola       TEXT,
  ADD COLUMN IF NOT EXISTS sala         TEXT,
  ADD COLUMN IF NOT EXISTS professor_id INTEGER REFERENCES usuario(id);

CREATE INDEX IF NOT EXISTS idx_aluno_professor_id ON aluno(professor_id);

-- Nova tabela: metas pedagógicas
CREATE TABLE IF NOT EXISTS meta (
    id              SERIAL PRIMARY KEY,
    professor_id    INTEGER NOT NULL REFERENCES usuario(id),
    sala            TEXT,
    bimestre        INTEGER NOT NULL,
    ano             INTEGER NOT NULL,
    meta_progresso  INTEGER NOT NULL,
    descricao       TEXT,
    criado_em       TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_meta_professor_id ON meta(professor_id);

-- Nova tabela: avaliações
CREATE TABLE IF NOT EXISTS avaliacao (
    id           SERIAL PRIMARY KEY,
    aluno_id     INTEGER NOT NULL REFERENCES aluno(id),
    professor_id INTEGER NOT NULL REFERENCES usuario(id),
    bimestre     INTEGER NOT NULL,
    ano          INTEGER NOT NULL,
    nota         DOUBLE PRECISION NOT NULL,
    progresso    INTEGER,
    observacoes  TEXT,
    criado_em    TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_avaliacao_aluno_id     ON avaliacao(aluno_id);
CREATE INDEX IF NOT EXISTS idx_avaliacao_professor_id ON avaliacao(professor_id);

-- Nova tabela: atividades geradas por IA
CREATE TABLE IF NOT EXISTS atividadegerada (
    id                  SERIAL PRIMARY KEY,
    aluno_id            INTEGER NOT NULL REFERENCES aluno(id),
    professor_id        INTEGER NOT NULL REFERENCES usuario(id),
    titulo              TEXT NOT NULL,
    objetivo            TEXT,
    duracao_minutos     INTEGER,
    dificuldade         TEXT,
    materiais           TEXT,
    passo_a_passo       TEXT,
    adaptacoes          TEXT,
    criterios_avaliacao TEXT,
    justificativa       TEXT,
    bimestre            INTEGER,
    ano                 INTEGER,
    criado_em           TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_atividadegerada_aluno_id     ON atividadegerada(aluno_id);
CREATE INDEX IF NOT EXISTS idx_atividadegerada_professor_id ON atividadegerada(professor_id);

-- Colunas novas em atividadegerada (adicionadas em Abril 2026)
ALTER TABLE atividadegerada
  ADD COLUMN IF NOT EXISTS disciplina           TEXT,
  ADD COLUMN IF NOT EXISTS tipo_atividade       TEXT,
  ADD COLUMN IF NOT EXISTS instrucao_professor  TEXT,
  ADD COLUMN IF NOT EXISTS instrucao_familia    TEXT,
  ADD COLUMN IF NOT EXISTS conteudo_atividade   TEXT,
  ADD COLUMN IF NOT EXISTS tags                 TEXT,
  ADD COLUMN IF NOT EXISTS parametros_professor TEXT,
  ADD COLUMN IF NOT EXISTS reutilizavel         BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS necessidade_atendida TEXT,
  ADD COLUMN IF NOT EXISTS concluida            BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS concluida_em         TIMESTAMP WITHOUT TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_atividadegerada_reutilizavel        ON atividadegerada(reutilizavel);
CREATE INDEX IF NOT EXISTS idx_atividadegerada_necessidade_atendida ON atividadegerada(necessidade_atendida);
CREATE INDEX IF NOT EXISTS idx_atividadegerada_concluida            ON atividadegerada(concluida);

-- Nova tabela: templates de atividade
CREATE TABLE IF NOT EXISTS atividadetemplate (
    id                  SERIAL PRIMARY KEY,
    titulo              TEXT NOT NULL,
    descricao           TEXT,
    disciplina          TEXT,
    tipo_atividade      TEXT,
    nivel_dificuldade   TEXT,
    nivel_aprendizado   TEXT,
    duracao_minutos     INTEGER,
    necessidades_alvo   TEXT,
    objetivo            TEXT,
    instrucao_professor TEXT,
    instrucao_familia   TEXT,
    conteudo_atividade  TEXT,
    materiais           TEXT,
    passo_a_passo       TEXT,
    adaptacoes          TEXT,
    criterios_avaliacao TEXT,
    tags                TEXT,
    ativo               BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em           TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_atividadetemplate_ativo           ON atividadetemplate(ativo);
CREATE INDEX IF NOT EXISTS idx_atividadetemplate_nivel_dificuldade ON atividadetemplate(nivel_dificuldade);

-- Nova tabela: conclusões de atividades
CREATE TABLE IF NOT EXISTS conclusaoatividade (
    id                      SERIAL PRIMARY KEY,
    atividade_id            INTEGER NOT NULL REFERENCES atividadegerada(id),
    aluno_id                INTEGER NOT NULL REFERENCES aluno(id),
    professor_id            INTEGER NOT NULL REFERENCES usuario(id),
    observacoes             TEXT,
    nota_comunicacao        DOUBLE PRECISION,
    nota_coordenacao_motora DOUBLE PRECISION,
    nota_cognicao           DOUBLE PRECISION,
    nota_socializacao       DOUBLE PRECISION,
    nota_autonomia          DOUBLE PRECISION,
    nota_linguagem          DOUBLE PRECISION,
    nota_geral              DOUBLE PRECISION,
    competencias_trabalhadas TEXT,
    concluido_em            TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conclusaoatividade_atividade_id ON conclusaoatividade(atividade_id);
CREATE INDEX IF NOT EXISTS idx_conclusaoatividade_aluno_id     ON conclusaoatividade(aluno_id);
```

## Variáveis de Ambiente (Render)
```
DATABASE_URL        = postgresql://... (Supabase Transaction Pooler porta 6543)
ALLOW_ORIGIN_REGEX  = https://.*\.vercel\.app$
SECRET_KEY          = chave JWT (mínimo 32 bytes)
GROQ_API_KEY        = gsk_...
OPENAI_API_KEY      = sk-... (mantido para RAG legado)
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

## Dados de Teste

### Usuário Professor
```
Email: leo@eduinclusiva.com
Senha: Teste123!
Role:  professor
ID:    1
```

### Alunos Seed (scripts/seed.py)
| ID | Nome | Necessidade | Estilo | Grau | Ano | Progresso |
|----|------|-------------|--------|------|-----|-----------|
| 2 | João Pedro Silva | Autismo leve | Visual-Cinestésico | Leve | 2º Ano | 45% |
| 3 | Ana Clara Santos | Dislexia | Visual | Moderado | 2º Ano | 62% |
| 4 | Lucas Gabriel Oliveira | TDAH | Cinestésico | Moderado | 3º Ano | 58% |

Seed inclui: avaliações de B1 e B2/2026, metas por sala e bimestre, 3 planos de histórico por aluno.

Para rodar: `python scripts/seed.py` (carrega `.env` automaticamente)

## O que ainda NÃO existe no backend (TODO)
| Campo/Endpoint | Usado em | Prioridade |
|----------------|----------|------------|
| `GET /v1/escolas/` | secretary-dashboard | Alta |
| `GET /v1/metricas/escola/{id}` | secretary + coordinator | Alta |
| `GET /v1/turmas/` | coordinator-dashboard | Alta |
| `GET /v1/turmas/{id}/alunos` | coordinator-dashboard | Alta |
| `GET /v1/metricas/rede/` | secretary-dashboard | Alta |
| `GET /v1/alunos/?responsavel_id={id}` | parent-portal | Alta |
| `GET /v1/mensagens/` | comunicação em todas as páginas | Alta |
| `GET /v1/comunicados/` | parent-portal + coordinator | Média |
| `GET /v1/eventos/` | calendário | Baixa |
| `GET /v1/recursos/` | biblioteca educativa | Baixa |

## Padrões de Desenvolvimento
1. Sempre proteger rotas com `Depends(get_current_user)`
2. Verificar permissão antes de retornar dados de aluno
3. Nunca expor `senha_hash` em responses
4. Serializar JSON fields (atividades, recomendacoes, materiais, tags, etc) antes de salvar
5. Usar `session.exec(select(...))` — padrão SQLModel, não `session.query()`
6. PUT usa schema `AlunoUpdate` com `.model_dump(exclude_unset=True)`
7. Campos lista (materiais, tags, etc) são `TEXT` no banco — serializar com `json.dumps()`, deserializar com `json.loads()` no response
8. `buscar_ou_gerar_atividade` retorna `{"fonte": str, "atividade": dict}` — nunca retorna o model diretamente

## Erros Comuns e Soluções
| Erro | Causa | Solução |
|------|-------|---------|
| `ModuleNotFoundError: app.services` | Import path errado | Usar `from services.x` |
| `column X does not exist` | Coluna nova não criada | `ALTER TABLE` no Supabase |
| `Network is unreachable` (porta 5432) | Supabase bloqueia porta direta | Usar porta 6543 (pooler) |
| `IndentationError` | Decorator entre `@router` e `def` | Mover docstring para dentro da função |
| `email-validator not installed` | Pydantic EmailStr sem dependência | Adicionar ao requirements.txt |
| JWT key too short warning | SECRET_KEY < 32 bytes | Usar chave com 32+ bytes |
| Groq JSON parse error | Caracteres de controle no response | `_limpar_json_resposta()` em ai_service.py já trata |
| `ia_reutilizada` nunca dispara | Score < 70 ou mesmo aluno_id | Gere atividade p/ outro aluno com mesma necessidade primeiro |
