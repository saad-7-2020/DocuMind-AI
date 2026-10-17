# How to test DocuMind AI

There are three levels, from fastest to most realistic:

| Level | What it proves | Needs |
|---|---|---|
| **A. Automated tests** | The backend logic is correct (60 tests) | Docker (Postgres) |
| **B. UI in "fake" mode** | The whole app works end to end, offline and instantly | Docker |
| **C. UI with real AI** | Real French answers from Groq, real bge-m3 embeddings on your GPU | Docker + Groq key |

All commands are for **PowerShell**. Open a terminal in `C:\My_projects\IA\RAG`.

## 0. One-time setup

Node.js is portable on A:, so add it to PATH in each new terminal where you run the frontend:

```bash
$env:Path = "A:\documind\node;$env:Path"
```

(To make that permanent, add `A:\documind\node` to your user PATH in Windows Settings → "Edit environment variables for your account".)

Install the frontend dependencies once:

```bash
npm --prefix frontend install
```

Start the database. **Option 1: Docker** (Docker Desktop must show "Engine running"):

```bash
docker compose up -d db
```

**Option 2: without Docker** (Windows). Runs Postgres 16 + pgvector from a Python wheel, on the same port and with the same credentials, so nothing else changes. One-time install of the isolated environment:

```bash
py -m uv venv A:\documind\pgenv --python 3.13
```

```bash
py -m uv pip install --python A:\documind\pgenv\Scripts\python.exe pixeltable-pgserver==0.5.1
```

Then start it (creates the data folder and both databases on first run; use `stop` / `status` the same way):

```bash
powershell -ExecutionPolicy Bypass -File scripts\dev-db.ps1 start
```

> Why version 0.5.1 exactly: pgvector is compiled for the builder's CPU. Newer builds (0.6.0) use AVX-512 instructions, and on CPUs without them (e.g. Ryzen 5 5500) the server **crashes** with "illegal instruction" the moment a 1024-dimension vector is inserted. 0.5.1 was tested on that CPU. This build has no `unaccent` extension, so keyword search in Phase 3 won't ignore accents unless you use the Docker image.

Create the schema (needed once, and again after future migrations):

```bash
cd backend; py -m uv run alembic upgrade head; cd ..
```

## A. Automated tests (1 minute)

```bash
cd backend; py -m uv run pytest; cd ..
```

Expected: `60 passed`. They use the separate `documind_test` database and stand-ins for the embedding model and the LLM: no network, no GPU. The frontend has no automated tests yet (those come in Phase 5); this command checks that it compiles in strict TypeScript:

```bash
npm --prefix frontend run build
```

## B. UI in fake mode (no Groq key, instant)

"Fake mode" swaps the embedding model for a word-hashing stand-in and the LLM for one that answers with the first sentence of the best passage. Retrieval, citations, pages, uploads, deletion and the whole UI are real. Only the "intelligence" is simulated. It uses the **test database**, so your real data isn't touched.

You need **three terminals**, all in `C:\My_projects\IA\RAG\backend`, each starting with these lines:

```bash
$env:DATABASE_URL = "postgresql+psycopg://documind:documind@127.0.0.1:5433/documind_test"
```

```bash
$env:EMBEDDER = "fake"; $env:LLM_PROVIDER = "fake"
```

Then:

1. Terminal 1: create a user (copy the printed `dm_…` key):
   ```bash
   py -m uv run documind create-user demo@example.com
   ```
   then start the API:
   ```bash
   py -m uv run documind api
   ```
2. Terminal 2: the worker:
   ```bash
   py -m uv run documind worker
   ```
3. Terminal 3, from the repo root: the UI:
   ```bash
   npm --prefix frontend run dev
   ```

Open **http://localhost:5173** and paste the key.

> Running the backend test suite later empties the test database, including this demo user. Just create a new one.

## C. UI with the real models

Same as B, but **without** the fake variables, using your real database:

1. In `backend\.env`, set `GROQ_API_KEY=` to your key (the file is git-ignored).
2. Close memory-heavy apps first. The worker loads bge-m3 (≈2.5 GB of RAM while loading) the first time it indexes.
3. Terminal 1, in `backend`: `py -m uv run documind create-user you@example.com`, then `py -m uv run documind api`
4. Terminal 2, in `backend`: `py -m uv run documind worker`. Watch for `"device": "cuda"` on the first upload.
5. Terminal 3, from the repo root: `npm --prefix frontend run dev`, then open http://localhost:5173.

## What to try (checklist)

**Documents page**
- [ ] Drag and drop **several** files at once: each shows "Envoi… %" then the pipeline stages (Extraction → Découpage → Embeddings → Enregistrement) and finally "Indexé".
- [ ] Upload the same file twice: you get a "déjà importé" toast (HTTP 409, duplicate detection by SHA-256).
- [ ] Upload a `.png` renamed to `.pdf`: it's rejected (the type is detected from the content, not the name).
- [ ] Upload a password-protected PDF: it ends in **Échec** with the reason.
- [ ] Click a document name: the viewer shows metadata and the extracted text page by page.
- [ ] Delete a document: it disappears from answers **immediately**, then from the list.

**Assistant page**
- [ ] Ask a question whose answer is in a document. Check that the `[1]` chips and source cards point to the **right file and page**. Click one: the page opens with the quote **highlighted**.
- [ ] Ask something that is **not** in your documents (e.g. "Qui a gagné la Coupe du monde 2018 ?"). With the real model, you should get the amber **"Je ne peux pas répondre avec certitude"** card instead of an invented answer.
- [ ] Open the options chip: limit the search to one document, change top-k, enable **debug**. The "Diagnostic de recherche" panel shows every ranked passage, its similarity score, and whether it was sent to the model. This is the best way to understand *why* an answer is what it is.

**Settings page**
- [ ] Switch dark/light theme. Check the API status (database up, embedding model name).

**Access control (optional)**
- [ ] Create a second user, sign in with their key (Settings → Remplacer): they see **none** of the first user's documents, and their questions never cite them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI says "API injoignable" | The API isn't running on port 8000 (terminal 1). |
| Upload stays "En file d'attente" | The worker isn't running (terminal 2). |
| "Clé API manquante ou invalide" | The key belongs to another database (fake mode uses `documind_test`), or the test suite wiped it: create a new user. |
| `llm_error` on every question | `GROQ_API_KEY` is missing or wrong in `backend\.env`; restart the API after editing. |
| Worker crashes with "memory allocation … failed" | Not enough free memory: close apps, or activate the A: page file (see docs/phase-2.md). |
| `npm` / `node` not recognized | Run the PATH line from step 0 in that terminal. |
