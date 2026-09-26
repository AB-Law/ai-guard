# Aegis — control tower for enterprise agents

Governance layer around enterprise agents: tool-call gateway, audit trail, and policy-driven process configs. Demo process: procurement review (with a second `onboarding_kyc` config proving the accelerator claim).

See [BUILD.md](./BUILD.md) for the phased build plan/progress tracker and [ARCHITECTURE.md](./ARCHITECTURE.md) for the design. For governing calls from *your own* agent (LangChain or plain Python) without going through this app's case/process model, see [sdk/aiguard/README.md](sdk/aiguard/README.md).

## Setup

```bash
cd control-tower
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
copy .env.example .env   # add OPENAI_API_KEY only if you want live e2e / dashboard LLM calls
```

Everything below (API, dashboard, scenario runner, demo seed, tests) runs fully offline with **no API key** — LLM calls are mocked unless you opt into `@pytest.mark.live`.

## Run the API

```bash
uvicorn api.main:app --reload
```

Opens on `http://127.0.0.1:8000`. Interactive docs at `http://127.0.0.1:8000/docs`.

Key endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/cases` | Submit a case, starts the agent graph |
| `GET` | `/cases` | List cases |
| `GET` | `/cases/{case_id}` | Case status, scores, decision |
| `GET` | `/cases/{case_id}/audit` | Audit trail for a case |
| `GET` | `/audit/verify` | Hash-chain integrity check |
| `POST` | `/approvals/{call_id}` | Approve/reject an escalated case (resumes the graph) |
| `POST` | `/guard/evaluate` | Evaluate one tool call from an external agent (no `/cases`, no graph) — what the `aiguard` SDK calls |
| `GET` | `/guard/approvals/{call_id}` | Status of a `/guard/evaluate` call that escalated — dashboard (any) or the owning app's API key |
| `POST` | `/guard/approvals/{call_id}` | Approve/reject a `/guard/evaluate` escalation — owning app's API key only, dashboard is view-only for these |
| `POST` | `/applications` | Register an agent identity + API key (dashboard). Optional inventory metadata (owner, tools, declared MCP servers) |
| `GET` | `/applications` | List registered applications with inventory, `last_seen_at`, and derived health |
| `PATCH` | `/applications/{app_id}` | Update declared inventory metadata — dashboard (any) or owning app API key |
| `POST` | `/applications/heartbeat` | Stamp `last_seen_at` for the authenticated application (API key only; no caller-supplied `source_app`) |
| `POST` | `/applications/{app_id}/revoke` | Revoke an application's API key (dashboard) |
| `POST` | `/investigate` | Ask the investigation assistant a question over the audit log |
| `POST` | `/knowledge/documents` | Upload a `.md`/`.txt`/`.csv` doc — indexed into the live KB immediately, no restart |
| `GET` | `/traffic/recent` | Recent cases with per-stage pipeline status, for the live traffic view |
| `POST` | `/demo/seed` | Reset + load demo rehearsal cases into the live CaseStore |
| `POST` | `/demo/reset` | Wipe cases + audit rows (fresh checkpointer) |
| `GET` | `/health` | Liveness check |

Example — submit a clean procurement case:

```bash
curl -X POST http://127.0.0.1:8000/cases \
  -H "Content-Type: application/json" \
  -d "{\"process\": \"procurement_review\", \"request\": {\"vendor_id\": \"V-1001\", \"amount\": 2500, \"item\": \"Laptop docks x10\"}}"
```

Switch process/config by changing `"process"` to `"onboarding_kyc"` — no code changes needed.

Approve/reject an escalated case (use the `call_id` returned on an `escalate` decision):

```bash
curl -X POST http://127.0.0.1:8000/approvals/<call_id> \
  -H "Content-Type: application/json" \
  -d "{\"action\": \"approve\", \"actor\": \"jane@example.com\"}"
```

The API writes to `data/audit.db` by default (auto-created).

**Agent inventory** (Applications page / `/applications`): optional owner/team/description, framework/runtime, declared tools/capabilities, and declared MCP servers are self-reported metadata. `last_seen_at` and health (`online`/`stale`/`offline`/`never_seen`) come only from authenticated heartbeats or API-key traffic — the tower does not discover or scan hosts for MCP servers.

Ingest a new document live (no restart — indexed into the running agent's KB immediately):

```bash
curl -X POST http://127.0.0.1:8000/knowledge/documents \
  -F "file=@path/to/new_policy.md" \
  -F "process=procurement_review"
```

Saved under `data/uploads/<process>/` and picked up by that process's KB (and by `default_seed_paths()` for investigation). Other processes cannot retrieve it. In the dashboard this is a sidebar **Knowledge base → Add document** upload with a process selector — no curl needed.

## Run the dashboard

**Two terminals** — the dashboard talks to the live API (in-memory cases). Seeding the audit DB alone will not fill the UI.

Terminal 1 — API:

```bash
uvicorn api.main:app --reload
```

Terminal 2 — dashboard:

```bash
set AEGIS_API_URL=http://127.0.0.1:8000   # Windows (optional; this is the default)
streamlit run dashboard/app.py
```

Then either click **Load demo pack** in the sidebar, or:

```bash
python scripts/demo_seed.py --api http://127.0.0.1:8000
```

That loads clean → injection → unauthorized → escalate (escalate stays **pending approval**). Use the approval queue to Approve/Reject, inspect scores + timeline per case, and optionally Ask the investigation assistant (offline mock if no API key).

The **Live traffic** panel (auto-refreshing every 2s) shows every case moving through the guardrail pipeline — Retrieve → Scan → Gateway → Action → Approval — as a colored row, most recent first. Empty at first; fill it with the demo pack or a traffic burst.

## Generate load / traffic

Every generated case uses `mock_agent_plan`, so this exercises the real gateway, injection guard, risk scorer, and audit chain at volume with **no live LLM calls** (fast, free, safe to run live during judging):

```bash
# Sustained stream in its own terminal — feeds the Live traffic panel continuously
python scripts/traffic_sim.py --rate 3 --duration 60

# One-shot batch (no API calls; prints the generated bodies for inspection)
python -c "from scripts.traffic_lib import generate_batch; import json; print(json.dumps(generate_batch(5, seed=1), indent=2))"
```

Or click **Simulate traffic burst** in the dashboard sidebar to fire a synchronous batch (5–100 cases) and watch Live traffic fill up immediately.

## Storage backends

The default (no `DATABASE_URL` set) keeps case state and LangGraph's HITL checkpoint in memory — fast to start, but **that state is per-process**: a second uvicorn worker, a second replica, or a restart won't see it. `DATABASE_URL` picks a different tier:

| `DATABASE_URL` | Audit log | Case store + checkpoint | Survives restart? | Safe with >1 worker? |
|---|---|---|---|---|
| unset (default) | SQLite file | in-memory | audit only | no |
| `sqlite` | SQLite file | SQLite file | yes | no (single-writer file) |
| `postgresql://...` | Postgres | Postgres | yes | **yes** |

Run the full stack with Postgres and multiple API workers via Docker Compose:

```bash
docker compose up --build
```

Brings up `db` (Postgres, internal-only — no host port published by default), `api` (`uvicorn --workers 4`, `http://localhost:8000`), and `dashboard` (`http://localhost:8501`). Because case/checkpoint state now lives in Postgres instead of each worker's own memory, a request answered by one worker is visible to another — verified by `tests/e2e/test_storage_backends.py`, which submits a case on one `create_app()` instance and resumes its HITL approval on a completely separate one sharing the same backend.

Data persists in a named Docker volume (`aegis_pgdata`) across `docker compose down`/`up`; add `-v` to wipe it.

Local dev without Docker, still fully persisted:

```bash
pip install -e ".[scale]"   # psycopg + langgraph-checkpoint-sqlite/postgres
set DATABASE_URL=sqlite
uvicorn api.main:app --reload
```

Postgres-tier tests need a real Postgres and are skipped by default (mirrors the `@pytest.mark.live` pattern):

```bash
docker run -d -e POSTGRES_USER=aegis -e POSTGRES_PASSWORD=aegis -e POSTGRES_DB=aegis -p 5544:5432 postgres:16-alpine
AEGIS_TEST_POSTGRES_URL=postgresql://aegis:aegis@localhost:5544/aegis pytest -m postgres
```

## Run scenario fixtures (no API/dashboard needed)

```bash
python scripts/run_scenario.py --all          # run all fixtures in tests/fixtures/cases/
python scripts/run_scenario.py clean_po       # run one fixture by id
```

## Seed / rehearse the demo

```bash
# For the dashboard (API must be running) — preferred for demo day
python scripts/demo_seed.py --api http://127.0.0.1:8000
python scripts/demo_seed.py --api http://127.0.0.1:8000 --rehearse

# Offline audit-DB only (does NOT populate the Streamlit case list)
python scripts/demo_seed.py                   # reset data/audit.db and load all fixtures
python scripts/demo_seed.py --rehearse         # offline rehearsal sequence
python scripts/demo_seed.py --no-reset         # seed without wiping the existing DB
```

## Verify audit chain integrity (tamper check)

```bash
python scripts/verify_audit_chain.py                        # checks data/audit.db by default
python scripts/verify_audit_chain.py --db path\to\other.db
```

Exits non-zero and prints `FAIL: audit chain broken` if any entry was tampered with.

## Tests

Humans don't run tests to gate work (see [BUILD.md](./BUILD.md) §2.2) — but to verify the build locally:

```bash
# Full offline suite (default; no API key required)
pytest -q

# Layer by layer
pytest tests/unit tests/contract -q                              # Phase 1
pytest tests/unit tests/contract tests/integration -q            # Phase 2
pytest tests/unit tests/contract tests/integration tests/e2e -q -m "not live"   # Phase 3+

# Offline policy-entailment consistency gate (also part of default pytest / CI)
# 20 labeled cases × N=3 stubbed runs; fails if gold-label agreement < 95%
# or if POLICY_ENTAILMENT_RUBRIC.md is not injected as the system prompt.
pytest tests/eval/test_policy_entailment_consistency.py -q

# Live suite (requires OPENAI_API_KEY in .env) — pre-demo only; not used by CI
pytest -q -m live

# Coverage (guardrails + audit must stay >= 80%)
pytest -q --cov=guardrails --cov=audit --cov-report=term-missing
```

## Project layout

```
control-tower/
├── agent/            # LangGraph agent: retrieve -> scan_injection -> reason -> propose_tool -> gateway_check -> execute/interrupt -> finalize
├── guardrails/        # Injection guard, tool-call gateway, output verifier, risk scorer, policy entailment
│   └── POLICY_ENTAILMENT_RUBRIC.md  # Fixed system-prompt rubric (violation / borderline / compliant)
├── audit/            # Hash-chained audit log + configurable PII/secret redaction
├── docs/             # Operator docs (e.g. sensitive-data.md)
├── contracts/         # Shared Pydantic schemas (ToolCallRequest, GatewayDecision, AuditLogEntry)
├── knowledge/         # RAG over policy/vendor docs (Chroma)
├── configs/           # Per-process YAML (procurement_review, onboarding_kyc)
├── data/              # Seed docs, vendor master, audit.db (generated)
├── api/                # FastAPI surface
├── dashboard/          # Streamlit UI
├── investigation_assistant/  # RAG over the audit log ("why was this flagged")
├── scripts/            # run_scenario.py, demo_seed.py, verify_audit_chain.py, traffic_sim.py/traffic_lib.py
├── sdk/aiguard/        # separate installable package — see sdk/aiguard/README.md
├── Dockerfile, docker-compose.yml  # api + dashboard + Postgres, see "Storage backends"
└── tests/              # unit / contract / integration / e2e / eval + fixtures
```
