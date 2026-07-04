# Invoice Archive AI

A self-hosted web app that ingests supplier invoices (PDF / image), uses a
multimodal LLM to **recognize the supplier and extract structured fields**, routes
low-confidence cases to a human, and archives + exports the results to renamed
files and Excel.

The interesting part isn't "call an LLM on an invoice" — it's everything around it:
supplier identification against a large master list, a **cost-aware two-stage matcher**
that only spends a second LLM call when the answer is genuinely ambiguous, per-supplier
prompt specialization, a human-in-the-loop correction loop that feeds a data flywheel,
per-call cost/latency telemetry, and a **reproducible evaluation harness with confidence
intervals**.

> Self-hosted and in production use in a real purchasing workflow.

- **Backend:** Python · FastAPI · SQLite · Google Gemini on Vertex AI (`google-genai`)
- **Frontend:** React · TypeScript · Vite · Tailwind
- **LLM ops:** Pydantic-validated structured output · per-call token/cost telemetry · LangSmith tracing · reproducible eval harness

![Core pipeline](docs/images/icqQ2.png)

---

## What it does

1. **Supplier preview (per upload).** One multimodal call classifies the document
   type (invoice / statement / PO / remittance …) and proposes vendor-name
   candidates. Candidates are fuzzy-matched (`rapidfuzz`) against the supplier master;
   near-ties trigger a second LLM call that picks from the shortlisted options only.
2. **Field extraction.** For confirmed invoices, fields are extracted with a
   **per-supplier prompt** — each supplier group can carry its own instructions and
   output schema; unknown suppliers fall back to a default schema.
3. **Human-in-the-loop.** Corrections are captured as labels and recycled into
   per-supplier few-shot examples *and* eval ground truth — a small data flywheel.
4. **Archive + export.** Confirmed invoices are renamed and exported alongside an
   Excel sheet with configurable columns.

## Getting started

### Credentials

The app calls Gemini on Vertex AI, so you need a Google Cloud service account:

1. Create a service account with **Vertex AI** access and download its JSON key.
2. Save the key at **`secrets/gemini-service-account.json`** — the app looks there by
   default, and the folder is git-ignored so it never gets committed.
3. Copy `.env.example` to `.env` and set `GOOGLE_CLOUD_LOCATION` (the project is read
   from the key automatically). Every key in `.env.example` is documented inline.

> Just want to look around? The Docker demo-data path below seeds a fully populated app
> with **no credentials required**.

### Docker (fastest — includes optional demo data)

The app ships as a single container (frontend built and served with the API on one
port). Use the launcher:

```bash
cp .env.example .env            # fill in the values (each key is documented in the file)
mkdir -p secrets exports        # your SA JSON goes at secrets/gemini-service-account.json
./start.sh                      # Windows: start.cmd
```

`start.sh` prompts **"Load demo data? [y/N]"**. Yes seeds a prebuilt snapshot (sample
invoices already recognized/confirmed + a supplier master), so you can explore a
populated app immediately — **no Google credentials needed just to look around**. The app
is served at http://localhost:8000.

### Backend (local dev)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Authentication resolution order (see [`backend/app/llm/gemini.py`](backend/app/llm/gemini.py)):

1. `GOOGLE_APPLICATION_CREDENTIALS` (service-account JSON) → Vertex AI *(recommended)*
2. Local ADC (`gcloud auth application-default login`) + `GOOGLE_CLOUD_PROJECT` → Vertex AI
3. `GEMINI_API_KEY` (AI Studio) → local dev only

### Frontend (local dev)

```bash
cd frontend
npm install
npm run dev        # proxies /api to http://127.0.0.1:8000
```

`app.main` also mounts `frontend/dist` at `/` when present, so a production build is
served from the same port as the API.

---

## Highlights

The part I usually highlight is that this is not just a thin wrapper around Gemini.
I built a full invoice workflow around the model. For supplier recognition, the first
LLM call gives me a few possible vendor names, then I match those against the supplier
master with `rapidfuzz`. If the top candidates are too close, I make one more cheap
LLM call and ask it to choose only from the shortlist. That keeps the system accurate
without spending extra tokens on easy cases.

For extraction, the schema is not hard-coded. Each supplier group can define its own
fields and prompt, and the backend builds a Pydantic response model at runtime. That
means the LLM output is structured, validated, and still flexible enough to keep
unexpected fields instead of throwing them away.

The other important piece is the feedback loop. When a user fixes a value during review,
I store both the model output and the corrected value. Those corrections can become
few-shot examples for that supplier and also ground truth for evaluation. I also log
token usage, cost, latency, supplier, stage, and prompt version for every call, so I can
debug quality and cost from actual production behavior instead of guessing.

On the reliability side, provider errors are classified and retried only when retrying
makes sense, with exponential backoff and jitter. The LLM client is behind a small
provider interface, so the production path uses native Gemini, but the app can also run
through a LiteLLM-backed client.

## Evaluation

The pipeline is measured with a headless, reproducible harness
([`evaluation/scripts/`](evaluation/scripts)). It runs the **production extraction
code path** — not a re-implementation — over a labeled set, normalizes values
(US/EU money formats, dates, ID whitespace), and reports per-field accuracy with a
**Wilson 95% confidence interval**. Fields with no ground-truth label are excluded
from their denominator rather than counted as failures.

**Public benchmark — [katanaml/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) (MIT), n = 100 synthetic invoices:**

On the public synthetic benchmark, the extraction results were very strong: invoice
number and total amount were correct on every labeled example, invoice date missed one
case out of 100, and 99 out of 100 invoices had all tracked fields correct. Supplier
identification also reached 100 out of 100 on this set against a supplier master of 418
vendors. I treat those numbers as a clean-data benchmark, not as a claim that real-world
scans are always perfect. For production-style documents, I compile separate metrics
from human review labels, because that data has messier scans and more near-duplicate
supplier names.

> _A private, real-world set (scanned documents, near-duplicate supplier names) is scored
> separately; those figures are compiled from production review labels via
> [`backend/evals/refresh_from_review_labels.py`](backend/evals/refresh_from_review_labels.py)._

### Reproduce

```bash
# Field-extraction eval on the committed 20-invoice demo set (no download needed)
python evaluation/scripts/run_demo_eval.py --data-dir evaluation/invoices-donut-demo

# Supplier-identification eval on the same set
python evaluation/scripts/run_supplier_eval.py --data-dir evaluation/invoices-donut-demo

# Full 100-invoice benchmark (fetches images + ground_truth.jsonl first)
python evaluation/scripts/fetch_dataset.py --split train --n 100 --out evaluation/scoring-set
python evaluation/scripts/run_demo_eval.py --data-dir evaluation/scoring-set
```

## Cost & latency

Measured from the built-in telemetry on `gemini-3.1-flash-lite` (Vertex AI paid tier,
$0.25 / $1.50 per 1M input/output tokens):

- **≈ $0.0013 per invoice, end-to-end** — supplier preview + field extraction. The
  conditional disambiguation call fires only on ambiguous names (0× on the clean
  synthetic set), so it adds nothing on the easy cases.
- **≈ $1.30 per 1,000 invoices** — effectively a rounding error at any realistic volume.
- **~2.8 s** average latency per extraction call.

Every call's token count, cost and latency is written to SQLite, so these numbers come
from real usage rather than an estimate.

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
  evals/          # manifest-driven eval runner, review-label -> golden-set builder
  tests/          # unit + integration tests
frontend/src/
  pending/ review/ confirmed/ rules/   # upload, HITL review, archive, config UIs
evaluation/
  invoices-donut-demo/   # committed 20-invoice demo set (runs with no download)
  scripts/               # headless eval harness (fetch, field eval, supplier eval)
Dockerfile               # multi-stage build: frontend + API in one image
docker-compose.yml       # single-container deploy + optional demo-data loader
```

## Project Notes

If I were explaining the project in an interview, I would describe it as a local,
single-tenant invoice automation system. The company keeps the uploaded invoices,
SQLite database, and exported files on its own machine, and only the model calls go out
to Vertex AI. That was intentional, because invoices can contain sensitive supplier and
pricing information.

The main engineering challenge was making the LLM useful inside a reliable workflow.
I had to handle supplier matching, per-supplier extraction rules, human correction,
cost tracking, retries, evals, and packaging. So the project became less about one
prompt and more about building the system around the prompt.

For testing, I covered the backend with unit and integration tests around the service
layer, LLM abstraction, API routes, and database migrations. Then I added a separate
evaluation harness that runs the real extraction path over labeled invoices, so I can
measure quality the same way the app actually runs. The public repo does not include
real supplier data or credentials; the demo data is synthetic and MIT-licensed.
