# Phase 2: Minimal end-to-end pipeline

Phase 2 builds the thinnest working version of the whole system. You can upload a French PDF or TXT, a
worker indexes it, and you can ask a question and get a French answer from Groq with citations that point
to the right document and page. Retrieval is **dense only**. Hybrid search, reranking, OCR, quote checking
and the full abstention gates come in Phase 3.

## What was built

```
upload ─► validate (magic bytes, size) ─► dedup (sha256) ─► blob + document + job (1 transaction) ─► 202
                                                                                │
worker ◄─ claim job (FOR UPDATE SKIP LOCKED) ◄──────────────────────────────────┘
   └─► extract (PyMuPDF / TXT) ─► clean ─► chunk (French sentences, 350 tok) ─► embed (bge-m3) ─► store

question ─► embed query ─► pgvector HNSW search (owner-scoped) ─► top-k sources S1..Sk
         ─► Groq gpt-oss-120b (strict JSON schema) ─► map S# → chunk/page ─► answer + citations
```

| Module | File(s) | Role |
|---|---|---|
| Config | `config.py`, `.env.example` | Every setting in one place, from env vars. |
| Schema | `migrations/versions/0001_initial_schema.py` | The full §8 schema as plain SQL, including the French FTS config (used in Phase 3). |
| Ingestion | `ingestion/validation.py`, `storage.py`, `extractors.py`, `cleaning.py`, `jobs.py` | Untrusted-input handling, content-addressed blobs, page extraction, cleaning, job queue. |
| Chunking | `chunking/sentences.py`, `chunker.py` | French sentence spans, token-bounded packing with overlap, exact offsets. |
| Embedding | `embedding/sentence_transformers.py`, `fake.py` | bge-m3 on GPU (fp16) or CPU; a deterministic hash embedder for tests. |
| Indexing | `indexing/service.py`, `worker/runner.py` | Runs the pipeline per job; retries, idempotency, delete. |
| Retrieval | `retrieval/dense.py` | One SQL query: owner/status filters plus vector ordering. |
| Generation | `generation/context.py`, `prompts.py`, `answer.py`, `llm/openai_compat.py` | Sources, French prompt, structured output, repair retry, citation mapping. |
| API | `api/…` | Upload/list/get/page/delete/reindex, jobs, query, health; problem+json errors; API-key auth. |

## Key decisions (and the RAG idea behind each)

1. **Chunks are exact slices of the document text.** The chunker works on character *spans*, never on
   copied strings, so `text[char_start:char_end] == chunk.text` always holds (a unit test checks it). Page
   numbers are then computed from offsets instead of guessed. This is what makes citations trustworthy, and
   it will let the UI highlight the exact passage later.

2. **Token counting uses the embedder's tokenizer.** bge-m3 uses the XLM-RoBERTa tokenizer, and French
   produces more tokens per word than English, so "350 tokens" is less text than it sounds. Counting with the
   model's own tokenizer means a chunk is never silently truncated at embedding time.

3. **Overlap is sentence-level.** The next chunk starts a few *whole sentences* back. This never cuts a
   sentence in half, but when a sentence is longer than the overlap budget there is no overlap at all. That's
   a real tradeoff, covered by a test, and Phase 4 will measure whether it matters.

4. **The fake embedder is a deliberate teaching tool.** `HashEmbedder` turns words into vector dimensions.
   It retrieves well when the question shares words with the passage and fails on synonyms. That's exactly the
   weakness of *keyword* search, so it's a useful mental model for why dense models exist. Tests use it so they
   run in about a second with no GPU and no download.

5. **Filters run inside the vector query.** `owner_id`, `status = 'ready'` and the optional
   `document_ids` are in the same SQL statement as `ORDER BY embedding <=> :q`. Another user's chunk can't
   enter the candidate list, and a document being deleted disappears from retrieval immediately. We enable
   pgvector's iterative HNSW scan so selective filters still return *k* rows (§5.1).

6. **Strict structured output instead of "please answer in JSON".** With `json_schema` + `strict: true`,
   Groq constrains decoding to our schema, so parse failures should be rare. We still validate with Pydantic
   and allow exactly one repair retry. The model answers with `S#` labels, and *our* code maps them to
   chunk/page. The model never sees a database ID, so it can't invent one. Citations to sources it wasn't
   given are dropped and counted.

7. **A Postgres job table, not BackgroundTasks.** Document, blob reference and job are committed together.
   Workers claim with `FOR UPDATE SKIP LOCKED`. Failures are typed: a password-protected PDF fails
   immediately (retrying can't help), while an unknown error (e.g. GPU out of memory) is retried with
   exponential backoff. A job left `running` by a crashed worker is reclaimed after `JOB_TIMEOUT_S`.
   Re-running a job replaces its pages and chunks in one transaction, and deterministic chunk IDs make
   re-indexing idempotent.

8. **Errors are problem+json with stable codes** (`duplicate`, `unsupported_file_type`, `pdf_encrypted`,
   …), and neither error messages nor logs contain document text or questions.

### Known limits (on purpose, for later phases)
- Dense-only retrieval: exact identifiers (article numbers, product codes) can be missed. *(Phase 3: hybrid.)*
- No quote verification and no score-threshold abstention yet: an answer can cite a real source with a
  paraphrased "quote". *(Phase 3.)*
- Image-only PDF pages produce no text; a fully scanned PDF fails with `no_text_found`. *(Phase 3: OCR.)*
- DOCX uploads are rejected with 415. *(Phase 3.)*
- `cost_usd` is `null`: no prices are configured, and we don't estimate. Token usage is real.
- The job timeout is enforced by reclaiming stale jobs, not by killing a running one.

## Run it

All commands are run from `backend/` in PowerShell. If `uv` isn't on your PATH, use `py -m uv` instead.

**Disk layout on this machine.** C: is nearly full, so everything heavy lives on **A:**:

| What | Where | How it's configured |
|---|---|---|
| Python virtualenv (PyTorch alone is ~5 GB) | `A:\documind\venv` | `backend\.venv` is a directory junction to it |
| uv download cache | `A:\documind\uv-cache` | `cache-dir` under `[tool.uv]` in `backend\pyproject.toml` |
| Hugging Face models (bge-m3 ~2.3 GB) | `A:\documind\models` | `MODEL_CACHE_DIR` in `backend\.env` |
| Docker Desktop disk image (Postgres data) | A: | Docker Desktop → Settings → Resources → Advanced → Disk image location |

On a fresh clone, recreate the junction before the first `uv sync` (from `backend/`):

```bash
New-Item -ItemType Junction -Path .venv -Target A:\documind\venv
```

**1. One-time setup**

```bash
py -m pip install --user uv
```

```bash
py -m uv sync --extra ml
```

```bash
copy .env.example .env
```

Then open `backend/.env` and set `GROQ_API_KEY=` to your key. The file is git-ignored; don't paste the key anywhere else.

**2. Database** (from the repo root; Postgres listens on host port **5433**, since 5432 is your local Postgres)

```bash
docker compose up -d db
```

```bash
py -m uv run alembic upgrade head
```

**3. Check the GPU**

```bash
py -m uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**4. Create a user (prints an API key once)**

```bash
py -m uv run documind create-user you@example.com
```

**5. Start the worker and the API** (two terminals). The first ingest downloads bge-m3 (~2.3 GB) once.

```bash
py -m uv run documind worker
```

```bash
py -m uv run documind api --reload
```

The interactive API docs are then at http://127.0.0.1:8000/docs.

**6. Try it** (PowerShell; replace the key and the file path)

```bash
$H = @{ Authorization = "Bearer dm_YOUR_KEY" }
```

```bash
curl.exe -s -H "Authorization: Bearer dm_YOUR_KEY" -F "file=@C:\chemin\vers\contrat.pdf" http://127.0.0.1:8000/v1/documents
```

```bash
Invoke-RestMethod -Headers $H http://127.0.0.1:8000/v1/jobs/JOB_ID
```

```bash
Invoke-RestMethod -Method Post -Headers $H -ContentType "application/json; charset=utf-8" -Body '{"question": "Quel est le préavis de résiliation ?", "debug": true}' http://127.0.0.1:8000/v1/query | ConvertTo-Json -Depth 6
```

`debug: true` shows the ranked chunks and which ones went into the prompt. Use it to understand *why* an
answer is what it is.

## Tests

```bash
py -m uv run pytest
```

- `tests/unit` (no database): sentence splitting, chunk offsets / token bounds / overlap / pages, cleaning,
  upload sniffing and size limit, the Groq client (request shape, 429 + Retry-After, bounded timeouts, no
  retry on 4xx), answer mapping / dropped citations / abstention / repair retry, prompt-injection escaping,
  log redaction.
- `tests/integration` (needs `docker compose up -d db`; uses the `documind_test` database, fakes only, no
  network): upload → worker → query over HTTP for PDF and TXT, correct page in citations, pagination,
  duplicate 409, renamed PNG 415, oversize 413, encrypted PDF fails without retry, 401, question limits,
  owner isolation (404s, no cross-user retrieval even with a document filter), document filter, delete (hidden
  immediately, then rows + blob removed, job stays pollable), transient failure retried with backoff,
  idempotent re-index (same chunk IDs), stale job reclaimed.

If the database isn't running, integration tests are **skipped** with a message telling you to start it.

## Acceptance checklist

- [ ] `docker compose up -d db` then `py -m uv run alembic upgrade head` creates the schema.
- [ ] `torch.cuda.is_available()` prints `True`, and the worker log shows `"device": "cuda"` on first ingest.
- [ ] `py -m uv run pytest` passes with the DB running (unit + integration, no network).
- [ ] Manual demo: upload a French PDF, the job reaches `succeeded`, a French question gets a French answer
      whose citation has the right `document_id` and page.

## Troubleshooting

- **"memory allocation of N bytes failed" when the worker loads bge-m3**: Windows ran out of *commit*
  memory (RAM + page file), not GPU memory. Loading needs ~3 GB of commit beyond `import torch` (the
  250k-token multilingual tokenizer alone takes ~1.2 GB). Fix: give Windows a page file on A: (System →
  About → Advanced system settings → Performance → Settings → Advanced → Virtual memory → A: "System managed
  size", then reboot), or close memory-heavy apps before starting the worker.
- **"There is not enough space on the disk"**: something heavy is landing on C:. Check that `backend\.venv`
  is still a junction (`(Get-Item .venv).LinkType` should print `Junction`) and that `MODEL_CACHE_DIR` is set.
- **Integration tests hang or skip with `OperationalError`**: Docker's engine isn't running. Docker Desktop
  must show "Engine running" before `docker compose up -d db`.
- **Port 5433 in use**: change the host port in `docker-compose.yml` and in `DATABASE_URL`/`TEST_DATABASE_URL`.
- **Groq 429**: the free tier has per-minute limits. The client waits for `Retry-After` (up to 30 s) and
  retries up to 3 times.
- **`llm_bad_output`**: if you switched to `llama-3.3-70b-versatile`, also set `LLM_STRUCTURED_MODE=json_object`.
