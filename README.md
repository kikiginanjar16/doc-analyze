# Doc Analyzer (Summary-only) v1 - FastAPI

A simple document analysis API that accepts **image, PDF, DOCX, PPTX, TXT, MD** and returns a single **Markdown summary**.

- Output: **Markdown only**
- Uses OpenAI for summarization, and OpenAI Vision for image or scanned PDF pages
- Optional PostgreSQL persistence for each analysis run, including external application identifiers
- Optional `webhook_url` callback with retry on delivery failure

## Features

- Separate endpoints for upload and `file_url` input
- Auto-detect file type by extension or content type
- PDF: tries text extraction first, then falls back to Vision per page for scanned or low-text PDFs
- PPTX and DOCX: extracts text and summarizes
- TXT and MD: summarizes directly
- Stores analysis results in PostgreSQL when `DATABASE_URL` is configured
- Stores RAG chunks in PostgreSQL for persistent retrieval
- Accepts `application`, `reference_id`, `document_id`, and custom `prompt` for more dynamic integrations
- Supports simple RAG question answering on stored analysis results
- Sends webhook callbacks and retries failed deliveries

## Quickstart

### Python version

- Recommended: Python 3.11 to 3.13
- Avoid Python 3.14 for now because some dependency combinations may still emit compatibility warnings
- The included Docker image uses Python 3.11

### If you have multiple Python versions installed

```bash
# Windows
py -3.13 -m venv .venv

# macOS/Linux
python3.13 -m venv .venv
```

### 1) Create venv and install

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

If `python -m venv .venv` picks Python 3.14 on your machine, use the version-specific command above instead.

### 2) Configure env

Copy `.env.example` to `.env` and set at least:

```env
OPENAI_API_KEY=your_key_here
```

Optional:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/doc_analyzer
WEBHOOK_TIMEOUT_SECONDS=15
WEBHOOK_MAX_RETRIES=3
WEBHOOK_RETRY_BACKOFF_SECONDS=2
```

If you run with `docker compose`, you can omit `DATABASE_URL` and the app will default to the bundled PostgreSQL service at `db:5432`.

### 3) Run

```bash
uvicorn app.main:app --reload --port 8294
```

Open docs:

- http://localhost:8294/docs

## Usage

### Analyze by upload

```bash
curl -s -X POST "http://localhost:8294/analyze?max_pages=10&max_slides=20" \
  -H "accept: application/json" \
  -F "file=@sample.pdf" \
  -F "webhook_url=https://example.com/webhooks/doc-analyzer" \
  -F "application=crm-portal" \
  -F "reference_id=customer-42" \
  -F "document_id=invoice-2026-0001" \
  -F "prompt=Fokuskan ringkasan pada nominal, tanggal jatuh tempo, dan pihak terkait."
```

### Analyze by URL

```bash
curl -s -X POST "http://localhost:8294/analyze/url?max_pages=10&max_slides=20" \
  -H "Content-Type: application/json" \
  -d "{\"file_url\":\"https://example.com/sample.pdf\",\"filename\":\"sample.pdf\",\"webhook_url\":\"https://example.com/webhooks/doc-analyzer\",\"application\":\"crm-portal\",\"reference_id\":\"customer-42\",\"document_id\":\"invoice-2026-0001\",\"prompt\":\"Fokuskan ringkasan pada nominal, tanggal jatuh tempo, dan pihak terkait.\"}"
```

### Read stored analysis

```bash
curl -s "http://localhost:8294/analysis-runs/<analysis_id>"
```

### Ask with RAG

```bash
curl -s -X POST "http://localhost:8294/rag" \
  -H "Content-Type: application/json" \
  -d "{\"analysis_id\":\"<analysis_id>\",\"question\":\"Apa poin utama dan tenggat waktunya?\",\"top_k\":4}"
```

### Ask with RAG by reference_id

```bash
curl -s -X POST "http://localhost:8294/rag" \
  -H "Content-Type: application/json" \
  -d "{\"reference_id\":\"customer-42\",\"question\":\"Ringkas semua dokumen untuk customer ini dan sebutkan tenggat penting.\",\"top_k\":5,\"application\":\"crm-portal\"}"
```

## Response

```json
{
  "analysis_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "application": "crm-portal",
  "reference_id": "customer-42",
  "document_id": "invoice-2026-0001",
  "prompt": "Fokuskan ringkasan pada nominal, tanggal jatuh tempo, dan pihak terkait.",
  "markdown": "# Ringkasan Dokumen\n\n## Document Info\n...",
  "meta": {
    "detected_type": "pdf",
    "pages": 12,
    "used_vision": true,
    "application": "crm-portal",
    "reference_id": "customer-42",
    "document_id": "invoice-2026-0001",
    "prompt": "Fokuskan ringkasan pada nominal, tanggal jatuh tempo, dan pihak terkait."
  },
  "webhook": {
    "requested": true,
    "url": "https://example.com/webhooks/doc-analyzer",
    "status": "delivered",
    "attempts": 1,
    "last_error": null
  }
}
```

## Additional request fields

- `application`: nama aplikasi dari sistem user. Cocok untuk filter atau multi-tenant grouping.
- `reference_id`: identifier dari entitas di aplikasi user, misalnya customer, case, atau transaction id.
- `document_id`: identifier dokumen dari aplikasi user.
- `prompt`: instruksi tambahan dari user yang akan ditambahkan ke prompt summary agar hasil lebih dinamis.

## RAG response

```json
{
  "analysis_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "reference_id": "customer-42",
  "question": "Apa poin utama dan tenggat waktunya?",
  "answer": "Poin utama dokumen adalah ... Tenggat waktu yang disebut adalah ...",
  "retrieved_chunks": [
    {
      "rank": 1,
      "source_chunk": 2,
      "score": 4,
      "content": "## Timeline\n..."
    }
  ]
}
```

## RAG by reference_id response

```json
{
  "reference_id": "customer-42",
  "application": "crm-portal",
  "question": "Ringkas semua dokumen untuk customer ini dan sebutkan tenggat penting.",
  "answer": "Berdasarkan dokumen yang ditemukan, ...",
  "retrieved_chunks": [
    {
      "rank": 1,
      "analysis_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
      "document_id": "invoice-2026-0001",
      "source_name": "invoice.pdf",
      "source_chunk": 2,
      "score": 5,
      "content": "## Timeline\n..."
    }
  ]
}
```

## Notes

- For scanned PDFs, Vision is called per page up to `max_pages`
- If `DATABASE_URL` is not set, analysis still works but no records are stored
- When PostgreSQL is enabled, analysis output is chunked and saved into `analysis_chunks` for RAG
- Webhook delivery is synchronous and retried up to `WEBHOOK_MAX_RETRIES` times before the API returns
- `/analyze` is for multipart file uploads only
- `/analyze/url` is for JSON body only
- `/rag` accepts exactly one of `analysis_id` or `reference_id`
- For `reference_id` queries, `/rag` can use optional `application` to avoid mixing records from different apps
- Swagger UI (`/docs`) now exposes the additional fields and the RAG request schema

## Docker

The included `Dockerfile` uses Python 3.11:

```bash
docker build -t doc-analyzer .
docker run --rm -p 8294:8294 --env-file .env doc-analyzer
```

## Docker Compose

Run the API and PostgreSQL together:

```bash
docker compose up --build
```

Run in background:

```bash
docker compose up -d --build
```

Stop services:

```bash
docker compose down
```

Stop services and remove PostgreSQL data volume:

```bash
docker compose down -v
```

Defaults used by `docker-compose.yml`:

- API: `http://localhost:8294`
- PostgreSQL: `localhost:5432`
- Database: `doc_analyzer`
- User: `postgres`
- Password: `postgres`
