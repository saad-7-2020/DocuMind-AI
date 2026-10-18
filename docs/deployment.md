# Deploying DocuMind AI: Vercel + Render + Supabase

```
 Browser ──► Vercel (React app, static)
    │
    └─ HTTPS + Authorization: Bearer dm_… ─►  Render web service (Docker)
                                                ├─ FastAPI  (/v1/…)
                                                └─ ingestion worker (a thread of the same process)
                                                      │            │             │
                                                      ▼            ▼             ▼
                                             Supabase Postgres  Supabase     Groq (LLM) +
                                             + pgvector         Storage      hosted embedding API
                                             (data, vectors)    (the files)
```

## What is different from running on your PC

| Local development | Deployed | Why |
|---|---|---|
| Embeddings: bge-m3 on your GPU | A **hosted embedding API** (`EMBEDDER=openai_compat`) | bge-m3 is a 2.3 GB model that wants a GPU; Render has no GPUs and its instances have 512 MB to 4 GB of RAM. |
| Files on local disk | **Supabase Storage** (private bucket) | A Render web service's disk is wiped on every restart, redeploy or spin-down. |
| Worker as its own process | Worker **thread inside the API** (`RUN_WORKER_IN_API=true`) | Render's free tier has no background workers. If the host stops the process mid-job, the stale lock is reclaimed on the next start. |
| Vite proxy (one origin) | Frontend and API on **different origins** | The API allows your Vercel address through `CORS_ORIGINS`; the frontend reads the API address from `VITE_API_URL`. |
| Postgres on `127.0.0.1` | Supabase **session pooler** | Supabase's direct connection is [IPv6-only unless you buy the IPv4 add-on](https://supabase.com/docs/guides/database/connecting-to-postgres); the session pooler works over IPv4. |

Vectors from different embedding models can't be compared. Every chunk records the model that produced it, and search only looks at chunks from the **current** model, so a production database simply starts fresh with the hosted model.

## Costs and limits to know before you start

- **Render free web service:** [spins down after 15 minutes without requests; the next request takes about a minute](https://render.com/docs/free). Filesystem is ephemeral, no persistent disk, no background workers. 750 free instance hours per month (enough for one service running all month). Paid instances: [Starter $7 (512 MB), Standard $25 (2 GB), Pro $85 (4 GB)](https://render.com/pricing.md). Check the current prices yourself.
- **Supabase free plan:** limits on database size and automatic pausing of inactive projects exist. **Check the current numbers on supabase.com/pricing** before relying on it. As a rough guide, one chunk costs about 10 KB (a 1024-float vector plus its index entry).
- **Jina (example embedding provider):** its [free tier is rate-limited to 100 requests/minute](https://jina.ai/embeddings/). The client retries on 429 and honors `Retry-After`. You can use any OpenAI-compatible provider; the model must produce **1024-dimensional** vectors.
- **Groq:** unchanged; it is the same API key you use locally.

## Before you start

1. The latest code must be on GitHub (`git push`). Render and Vercel both deploy from your repository.
2. Accounts: [Supabase](https://supabase.com), [Render](https://render.com), [Vercel](https://vercel.com), and an embedding provider (e.g. [Jina](https://jina.ai/embeddings/)).
3. Keep a scratch note for the values you'll collect. **Treat them as passwords: never paste them in chat, in issues, or into git.**

## Step 1: Supabase (database + file storage)

1. **New project.** Pick a region close to your users and **write down the database password** (you can't read it again). Prefer a password without special characters; otherwise you must URL-encode them later (`@` → `%40`, `/` → `%2F`, `:` → `%3A`).
2. **Storage → New bucket:** name `documents`, **keep it private** (public off).
3. Collect three things from the project's **Connect** panel (the button at the top of the project page). It has tabs; you need two of them:
   - **Server tab** (the one with the `.env` block): copy **`SUPABASE_URL`** (looks like `https://abcdefgh.supabase.co`) and reveal-and-copy **`SUPABASE_SECRET_KEY`** (the `sb_secret_…` value; click the eye icon, then the copy icon). The secret key bypasses all access rules, so it lives only in Render's environment and your own terminal. The `sb_publishable_…` key and the JWKS URL are not needed.
   - **Direct tab** (connection strings): choose the **Session pooler** method, port **5432**. Do **not** use "Direct connection" (IPv6-only) or "Transaction pooler" (no prepared statements). The string looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`, and the password is a placeholder that you replace with your database password. Turn it into `DATABASE_URL` by changing the start to `postgresql+psycopg://` and adding `?sslmode=require` at the end.
4. You don't need to enable extensions by hand: the migrations run `CREATE EXTENSION vector` (and `unaccent`, which Supabase provides, so French keyword search will ignore accents in Phase 3). Migration 0002 also turns on row-level security on every table, so Supabase's built-in REST API can't read your data.

## Step 1b: check your settings from your own PC (recommended)

Before Render is involved, run the self-test with the production values. It checks the database connection (and tells you if you picked the wrong kind of connection string), uploads, downloads and deletes a tiny test file in your Supabase bucket, calls the embedding API, and makes one small Groq call. It never prints a secret.

Set the values **in your own terminal** (never paste them into chat), from `backend/`:

```bash
$env:DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
$env:STORAGE_BACKEND = "supabase"; $env:SUPABASE_URL = "https://<ref>.supabase.co"; $env:SUPABASE_SECRET_KEY = "sb_secret_..."
$env:EMBEDDER = "openai_compat"; $env:EMBEDDING_API_KEY = "..."; $env:EMBEDDING_MODEL = "jina-embeddings-v3"
$env:EMBEDDING_QUERY_EXTRA = '{"task": "retrieval.query"}'; $env:EMBEDDING_DOCUMENT_EXTRA = '{"task": "retrieval.passage"}'
```

```bash
py -m uv run documind doctor
```

Expected: four lines starting with `[ OK]` and "All checks passed." Each failure prints a `->` hint (wrong connection type, missing bucket, bad key, wrong vector size…). Fix those first; they're the same problems you'd otherwise debug through Render's logs. (`--skip-embeddings` and `--skip-llm` leave out the calls that use provider quota.) Close the terminal afterwards.

## Step 2: Render (backend)

1. Render dashboard → **New → Blueprint** → select your repository. Render reads [render.yaml](../render.yaml).
2. Fill in the secrets it asks for:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Session pooler string from step 1 |
   | `SUPABASE_URL` | the project URL |
   | `SUPABASE_SECRET_KEY` | the `sb_secret_…` key |
   | `EMBEDDING_API_KEY` | your embedding provider key |
   | `GROQ_API_KEY` | your Groq key |
   | `CORS_ORIGINS` | leave empty for now (step 4) |

   Everything else is pre-filled in `render.yaml` (Jina as the example provider, free plan, Frankfurt region; change the region to match Supabase).
3. Create the service and watch the deploy logs. On every start the container runs `alembic upgrade head`, then starts the API. Success looks like `Running upgrade … -> 0002` followed by `Uvicorn running`.
4. Open `https://<your-service>.onrender.com/health/ready`. Expected: `{"status":"ok","database":"up","embedder":"jina-embeddings-v3"}`. `/docs` shows the interactive API.

## Step 3: create your first user

There's no public sign-up: users are created with a command, against the production database, from your PC (in `backend/`). The environment variable overrides your local `.env` for that one command:

```bash
$env:DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

```bash
py -m uv run documind create-user you@example.com
```

Copy the `dm_…` key it prints (shown once). Close that terminal afterwards so the production URL doesn't linger in your session.

## Step 4: Vercel (frontend)

1. Vercel → **Add New → Project** → import the repository.
2. **Root Directory: `frontend`**. Vercel detects Vite; [vercel.json](../frontend/vercel.json) sets the build and security headers.
3. **Environment Variables:** `VITE_API_URL` = `https://<your-service>.onrender.com` (no trailing slash). It's read at **build** time, so changing it later means redeploying.
4. Deploy. Copy the resulting address (e.g. `https://documind.vercel.app`).
5. Back in **Render → Environment**, set `CORS_ORIGINS` to that address (no trailing slash; comma-separate several, such as a custom domain). Render restarts the service.

## Step 5: smoke test

- [ ] Open the Vercel address, paste your `dm_…` key. The first request may take about a minute (Render waking up).
- [ ] Settings → "Adresse de l'API" shows your Render URL, status "Opérationnelle", embedding model name.
- [ ] Upload a small PDF. Progress runs through the stages and ends at "Indexé". In Supabase → Storage → `documents`, a new object appears.
- [ ] Ask a question the document answers: the answer carries a citation; clicking it opens the page with the quote highlighted.
- [ ] Ask something the document doesn't cover: you get the amber "Je ne peux pas répondre" card.
- [ ] Delete the document: the object disappears from the bucket.
- [ ] From the browser console, a request from another site fails with a CORS error (only your Vercel address is allowed).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Browser console: *blocked by CORS policy* | `CORS_ORIGINS` doesn't exactly match the page's address (scheme, no trailing slash, no path). Fix it in Render and wait for the restart. |
| UI says "API injoignable" for the first minute | Free instance waking up. Wait, then reload. |
| Render deploy fails on the migration with *Tenant or user not found* | Wrong pooler user: it must be `postgres.<project-ref>`, not plain `postgres`. |
| *connection timed out* / network unreachable to the database | You used the **direct** connection (IPv6). Switch to the Session pooler string. |
| *password authentication failed* | Wrong password, or special characters not URL-encoded in `DATABASE_URL`. |
| Upload fails with `storage_error` | Bucket name doesn't match `SUPABASE_BUCKET`, the bucket doesn't exist, or the key is wrong. `documind doctor` shows the HTTP status. If it's 401/403 with an `sb_secret_…` key, try the **legacy `service_role` key** (Project Settings → API Keys → Legacy) as `SUPABASE_SECRET_KEY`: the app sends new-style keys in the `apikey` header only, as Supabase documents, and retries with a bearer header if that's refused. This behaviour has been tested with fakes only, not yet against a live Supabase project. |
| Document stays "En attente" | The in-process worker isn't running: check `RUN_WORKER_IN_API=true` and the logs. |
| Document ends in `embedding_error` | Wrong provider key or model name, or the vectors aren't 1024-dimensional (the error message says which). |
| `embedding_unavailable` / `llm_rate_limited` | Provider rate limit: wait a minute; the client already retried. |
| Out-of-memory restarts while indexing a big PDF | The free instance has 512 MB. Lower `MAX_UPLOAD_BYTES`, or move to a larger plan. |

## Security checklist for a public deployment

- **The secret key and database password exist only in Render's environment (and your own terminal).** If either leaks, rotate it in Supabase.
- **No public sign-up;** whoever holds a `dm_…` key can use your Groq and embedding quota. Share keys carefully. There's no rate limiting yet (Phase 6 on the project plan).
- API keys live in the browser's `localStorage`, which is fine for a personal or demo deployment but not for a multi-user product. Proper login (e.g. Supabase Auth) would replace it.
- Uploaded documents and questions are sent to your embedding provider and to Groq. Don't put confidential documents through them unless their terms suit you.

## Changing things later

- **A different embedding model or provider:** change `EMBEDDING_*`, redeploy, then **reindex** every document (`POST /v1/documents/{id}/reindex`, or the refresh button in the UI). The new model must output **1024** dimensions, because the column is `vector(1024)`.
- **Staying awake:** upgrade the Render plan to Starter, or accept the cold start.
- **Rolling back:** Render keeps previous deploys (Events → Rollback). Migrations are forward-only in practice: `0002` can be undone with `alembic downgrade 0001`, but only from a shell that has the production `DATABASE_URL`.
