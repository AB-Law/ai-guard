# Aegis — control tower for enterprise agents

Governance layer around enterprise agents: tool-call gateway, audit trail, and policy-driven process configs. Demo process: procurement review (with a second `onboarding_kyc` config proving the accelerator claim).

See [BUILD.md](./BUILD.md) for the phased build plan/progress tracker and [ARCHITECTURE.md](./ARCHITECTURE.md) for the design.

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

Ingest a new document live (no restart — indexed into the running agent's KB immediately):

```bash
curl -X POST http://127.0.0.1:8000/knowledge/documents -F "file=@path/to/new_policy.md"
```

Saved under `data/uploads/` and picked up automatically by `default_seed_paths()`, so the investigation assistant can also cite it once a case's audit trail references it. In the dashboard this is a sidebar **Knowledge base → Add document** upload — no curl needed.

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

# Live suite (requires OPENAI_API_KEY in .env) — pre-demo only
pytest -q -m live

# Coverage (guardrails + audit must stay >= 80%)
pytest -q --cov=guardrails --cov=audit --cov-report=term-missing
```

## Project layout

```
control-tower/
├── agent/            # LangGraph agent: retrieve -> scan_injection -> reason -> propose_tool -> gateway_check -> execute/interrupt -> finalize
├── guardrails/        # Injection guard, tool-call gateway, output verifier, risk scorer
├── audit/            # Hash-chained SQLite audit log + PII redaction
├── contracts/         # Shared Pydantic schemas (ToolCallRequest, GatewayDecision, AuditLogEntry)
├── knowledge/         # RAG over policy/vendor docs (Chroma)
├── configs/           # Per-process YAML (procurement_review, onboarding_kyc)
├── data/              # Seed docs, vendor master, audit.db (generated)
├── api/                # FastAPI surface
├── dashboard/          # Streamlit UI
├── investigation_assistant/  # RAG over the audit log ("why was this flagged")
├── scripts/            # run_scenario.py, demo_seed.py, verify_audit_chain.py, traffic_sim.py/traffic_lib.py
└── tests/              # unit / contract / integration / e2e + fixtures
```
