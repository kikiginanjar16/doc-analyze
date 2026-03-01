# Doc Analyzer (Summary-only) v1 - FastAPI

A simple document analysis API that accepts **image, PDF, DOCX, PPTX, TXT, MD** and returns a single **Markdown summary**.

- Output: **Markdown only**
- Uses OpenAI for summarization, and OpenAI Vision for image or scanned PDF pages
- Optional PostgreSQL persistence for each analysis run
- Optional `webhook_url` callback with retry on delivery failure

## Features

- Separate endpoints for upload and `file_url` input
- Auto-detect file type by extension or content type
- PDF: tries text extraction first, then falls back to Vision per page for scanned or low-text PDFs
- PPTX and DOCX: extracts text and summarizes
- TXT and MD: summarizes directly
- Stores analysis results in PostgreSQL when `DATABASE_URL` is configured
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
uvicorn app.main:app --reload --port 8000
```

Open docs:

- http://localhost:8000/docs

## Usage

### Analyze by upload

```bash
curl -s -X POST "http://localhost:8000/analyze?max_pages=10&max_slides=20" \
  -H "accept: application/json" \
  -F "file=@sample.pdf" \
  -F "webhook_url=https://example.com/webhooks/doc-analyzer"
```

### Analyze by URL

```bash
curl -s -X POST "http://localhost:8000/analyze/url?max_pages=10&max_slides=20" \
  -H "Content-Type: application/json" \
  -d "{\"file_url\":\"https://example.com/sample.pdf\",\"filename\":\"sample.pdf\",\"webhook_url\":\"https://example.com/webhooks/doc-analyzer\"}"
```

### Read stored analysis

```bash
curl -s "http://localhost:8000/analysis-runs/<analysis_id>"
```

## Response

```json
{
  "analysis_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "markdown": "# Ringkasan Dokumen\n\n## Document Info\n...",
  "meta": {
    "detected_type": "pdf",
    "pages": 12,
    "used_vision": true
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

## Notes

- For scanned PDFs, Vision is called per page up to `max_pages`
- If `DATABASE_URL` is not set, analysis still works but no records are stored
- Webhook delivery is synchronous and retried up to `WEBHOOK_MAX_RETRIES` times before the API returns
- `/analyze` is for multipart file uploads only
- `/analyze/url` is for JSON body only

## Docker

The included `Dockerfile` uses Python 3.11:

```bash
docker build -t doc-analyzer .
docker run --rm -p 8000:8000 --env-file .env doc-analyzer
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

- API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Database: `doc_analyzer`
- User: `postgres`
- Password: `postgres`
