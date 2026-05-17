# ARB AI Agent — Backend

FastAPI backend for the Architecture Review Board AI Agent. Handles review orchestration, domain agents, knowledge-base retrieval, LLM integration, and admin operations.

> **Extracted from:** [`vijaydixitffis/arb-ai-agent`](https://github.com/vijaydixitffis/arb-ai-agent) (monorepo baseline tagged `v1.0-stable`)

---

## Repository layout

```
arb-ai-backend/
├── backend/                  # Python FastAPI application
│   ├── main.py               # App entry point — mounts /api/v1 and /api/v2
│   ├── requirements.txt
│   └── app/
│       ├── api/
│       │   ├── router.py     # Top-level router (mounts v1 + v2)
│       │   ├── v1/           # FROZEN — do not modify; patches only
│       │   │   ├── routes.py
│       │   │   └── *.py      # Endpoint modules
│       │   └── v2/           # ACTIVE — new features and changed shapes go here
│       │       ├── routes.py
│       │       └── *.py
│       ├── agents/           # Domain review agents + orchestrator
│       ├── core/             # Config, security, DB connection
│       ├── db/               # SQLAlchemy models
│       ├── models/           # Pydantic request/response models
│       └── services/         # Business logic (LLM, admin, auth, artefacts)
├── supabase/                 # Supabase edge functions + migrations
│   ├── functions/
│   └── migrations/
├── openapi-v1.yaml           # Frozen v1 API contract (136 routes)
└── .github/workflows/ci.yml  # Lint → Test → Docker build check
```

---

## API versioning

| Prefix | Status | Rule |
|--------|--------|------|
| `/api/v1` | **Frozen** | Bug fixes and security patches only. Never change a response shape. |
| `/api/v2` | **Active** | New endpoints and evolved response shapes land here. |

Frontend selects the version via `VITE_API_VERSION` env var. The `stable-v1` frontend branch pins to v1; `new-ui-v1` targets v2.

---

## Prerequisites

- Python 3.12+
- PostgreSQL 15+
- (Optional) Google Gemini API key or OpenAI API key

---

## Local setup

```bash
# 1. Clone
git clone https://github.com/vijaydixitffis/arb-ai-backend.git
cd arb-ai-backend/backend

# 2. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment — copy and edit
cp .env.example .env

# 5. Run database migrations
psql -d $DATABASE_URL -f migrations/arb_ai_agent_complete_ddl.sql
psql -d $DATABASE_URL -f migrations/20260514_admin_phase0.sql

# 6. Start the server
uvicorn main:app --reload --port 8000
```

The API is then available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs` (Swagger) or `/redoc`.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | — | JWT signing key |
| `GEMINI_API_KEY` | one of these | — | Google Gemini API key |
| `OPENAI_API_KEY` | one of these | — | OpenAI API key |
| `LLM_PROVIDER` | | `gemini` | Active LLM provider (`gemini` / `openai` / `openrouter`) |
| `USE_MOCK_LLM` | | `false` | Bypass real LLM with fixture data (for CI / demo) |
| `GEMINI_MODEL` | | `gemini-2.5-flash-lite` | Gemini model ID |
| `OPENAI_MODEL` | | `gpt-4o` | OpenAI model ID |

All tuneable runtime parameters (LLM temperature, retry counts, KB limits) can be overridden at runtime via the `system_config` database table — the app reads DB values first and falls back to `.env`.

---

## Branch rules

| Branch | Purpose | Allowed |
|--------|---------|---------|
| `main` | Active development | Everything |
| `stable-v1` | Production snapshot | **Patches only** — security, data-loss, broken deploy fixes |

Patch workflow: branch off `stable-v1` → fix → PR back → cherry-pick to `main`. See [BRANCHES.md](../arb-ai-agent/BRANCHES.md) in the monorepo for the full strategy.

---

## Running tests

```bash
cd backend
USE_MOCK_LLM=true pytest tests/ -v
```

---

## Supabase (edge functions + migrations)

The `supabase/` folder contains Deno edge functions and SQL migrations for the Supabase-backed deployment mode.

```bash
# Deploy an edge function
supabase functions deploy admin-api

# Push migrations to remote
supabase db push
```

---

## License

MIT — see [LICENSE](LICENSE).
