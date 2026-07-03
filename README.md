# Invoice Archive AI

A local-first web app that ingests supplier invoices (PDF / image), uses a
multimodal LLM to **recognize the supplier and extract structured fields**, routes
low-confidence cases to a human, and archives + exports the results to renamed
files and Excel.

The interesting part isn't "call an LLM on an invoice" — it's everything around it:
supplier identification against a large master list, per-supplier prompt
specialization, a human-in-the-loop correction loop, cost/latency telemetry, and a
**reproducible evaluation harness with confidence intervals**.

- **Backend:** Python · FastAPI · SQLite · Google Gemini on Vertex AI (`google-genai`)
- **Frontend:** React · TypeScript · Vite · Tailwind
- **LLM ops:** Pydantic-validated structured output · LangSmith tracing · per-call token/cost telemetry

---

## What it does

```
upload ─▶ supplier preview ─▶ [confident?] ─▶ field extraction ─▶ human review ─▶ archive + export
             (LLM + fuzzy match)     │no                              (HITL)
                                     ▼
                            manual supplier confirm
```

1. **Supplier preview (per upload).** One multimodal call classifies the document
   type (invoice / statement / PO / remittance …) and proposes vendor-name
   candidates. Candidates are fuzzy-matched (`rapidfuzz`) against the supplier master;
   near-ties trigger a second LLM call that picks from the shortlisted options only.
2. **Field extraction.** For confirmed invoices, fields are extracted with a
   **per-supplier prompt** (each supplier group can carry its own instructions and
   output schema); unknown suppliers fall back to a default schema.
3. **Human-in-the-loop.** Corrections are captured as labels and can be recycled into
   per-supplier few-shot examples and eval ground truth — a small data flywheel.
4. **Archive + export.** Confirmed invoices are renamed and exported alongside an
   Excel sheet with configurable columns.

## AI-engineering highlights

| Area | What's implemented |
|---|---|
| Structured output | Response schema built per prompt config; parsed + validated with Pydantic |
| Supplier identification | LLM candidates → `rapidfuzz` composite scoring (token-set/sort + core-token overlap, generic-word penalties) → LLM disambiguation on ties |
| Prompt specialization | Per-supplier "tag / scheme" prompts + field schemas, editable in the UI, importable/exportable as JSON |
| Reliability | Rate-limit-aware retries with exponential backoff + jitter on the preview stage |
| Observability | Per-call token usage + cost logged to SQLite; optional LangSmith tracing |
| Evaluation | Headless field-extraction and supplier-identification evals with Wilson confidence intervals (see below) |
| Provider abstraction | `LLMClient` interface with a native Gemini client and a LiteLLM-backed client |

---

## Evaluation

The pipeline is measured with a headless, reproducible harness
([`evaluation/scripts/`](evaluation/scripts)). It runs the **production extraction
code path** (not a re-implementation) over a labeled set, normalizes values
(US/EU money formats, dates, ID whitespace), and reports per-field accuracy with a
**Wilson 95% confidence interval**. Fields with no ground-truth label are excluded
from their denominator rather than counted as failures.

**Public benchmark — [katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) (MIT), n = 100 synthetic invoices:**

| Task | Metric | Accuracy | 95% CI |
|---|---|---|---|
| Field extraction | `invoice_number` | 100% (99/99) | [96.3%, 100%] |
| | `invoice_date` | 99% (99/100) | [94.6%, 99.8%] |
| | `total_amount` | 100% (99/99) | [96.3%, 100%] |
| | all fields correct | 99% (99/100) | [94.6%, 99.8%] |
| Supplier identification | correct `vendor_code` (master of 418) | 100% (100/100) | [96.3%, 100%] |

> **Caveat:** synthetic invoices are clean and their supplier names are distinct, so
> these numbers are optimistic — supplier matching, in particular, faces little
> disambiguation pressure here. On real-world data (scanned documents, near-duplicate
> supplier names) the numbers are lower; those are measured on a private internal set
> and reported separately.
>
> _Internal set: **`<fill in: field / supplier accuracy on N invoices, M suppliers>`**._

### Reproduce

```bash
# 1. Fetch a labeled subset (images + ground_truth.jsonl)
python evaluation/scripts/fetch_dataset.py --split train --n 100 --out evaluation/scoring-set

# 2. Field-extraction eval
python evaluation/scripts/run_demo_eval.py --data-dir evaluation/scoring-set

# 3. Supplier-identification eval (with distractor suppliers in the master)
python evaluation/scripts/fetch_dataset.py --split train --n 425 --labels-only \
    --out evaluation/scoring-set/_distractors
python evaluation/scripts/run_supplier_eval.py --data-dir evaluation/scoring-set \
    --extra-sellers evaluation/scoring-set/_distractors/ground_truth.jsonl
```

A committed 20-invoice demo set lives in
[`evaluation/invoices-donut-demo/`](evaluation/invoices-donut-demo) so the evals run
without downloading anything.

---

## Getting started

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Copy `.env.example` to `.env` and point it at your own Google Cloud service account.
Authentication resolution order (see [`backend/app/llm/gemini.py`](backend/app/llm/gemini.py)):

1. `GOOGLE_APPLICATION_CREDENTIALS` (service-account JSON) → Vertex AI *(recommended)*
2. Local ADC (`gcloud auth application-default login`) + `GOOGLE_CLOUD_PROJECT` → Vertex AI
3. `GEMINI_API_KEY` (AI Studio) → local dev only

> With a service account the project is read from the key's `project_id`, so
> `GOOGLE_CLOUD_PROJECT` is optional (set it only to override). `GOOGLE_CLOUD_LOCATION`
> is still required — it's not in the key, and Gemini 3 uses the `global` endpoint.
> The service-account JSON never belongs in git (`.gitignore` excludes real keys under
> `secrets/` and `*-service-account.json`).

### Frontend

```bash
cd frontend
npm install
npm run dev        # proxies /api to http://127.0.0.1:8000
```

`app.main` also mounts `frontend/dist` at `/` when present, so a production build is
served from the same port as the API. `backend/package_release.py` bundles the whole
thing into a single Windows executable via PyInstaller for non-technical users.

### Docker

The app ships as a single container (frontend built and served with the API on one
port). Use the launcher, which asks whether to load demo data:

```bash
cp .env.example .env            # set GOOGLE_CLOUD_LOCATION (project comes from the SA key)
mkdir -p secrets exports        # drop your SA JSON at secrets/gemini-service-account.json
./start.sh                      # Windows: start.cmd
```

`start.sh` prompts **"Load demo data? [y/N]"**. Yes seeds a prebuilt snapshot (sample
invoices already recognized/confirmed + a supplier master) into the data volume, so
you can explore a populated app immediately — **no Google credentials needed just to
look around**. No starts empty.

Equivalent manual commands: `docker compose --profile demo-data run --rm demo-data`
(seed), then `docker compose up --build` (→ http://localhost:8000). The SQLite DB and
uploads persist in the named `invoice_data` volume; `./secrets` is read-only,
`./exports` holds output, and a `/api/health` healthcheck is wired in. The snapshot is
regenerated offline (no LLM calls) with `python scripts/build_demo_snapshot.py`.

---

## Repository layout

```
backend/
  app/
    llm/          # provider clients, schema builder, pricing, telemetry, tracing
    services/     # invoice_extractor, supplier_matcher, supplier_preview_extractor,
                  # auto_archive, exporter, few_shot, response validation
    main.py       # FastAPI app + routes
    database.py   # SQLite schema + migrations
  evals/          # manifest-driven eval runner
  tests/          # unit + integration tests
frontend/src/
  pending/ review/ confirmed/ rules/   # upload, HITL review, archive, config UIs
evaluation/
  invoices-donut-demo/   # committed 20-invoice demo set
  scripts/               # headless eval harness (fetch, field eval, supplier eval)
Dockerfile               # multi-stage build: frontend + API in one image
docker-compose.yml       # single-container deploy + optional demo-data loader
start.sh / start.cmd     # launcher that prompts to load demo data
demo-data/               # prebuilt offline snapshot (seed DB + sample invoices)
scripts/                 # build_demo_snapshot.py
tests/                   # compose/container smoke tests
```

## Notes

- Local-first and single-user by design: invoices, the SQLite DB, and uploads stay on
  the machine (`data/`, git-ignored).
- No real supplier data or credentials are included in this repository; the sample
  data is synthetic and MIT-licensed.
