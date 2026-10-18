# Deploy DocuMind AI for $0 (no credit card)

This guide puts the app on the internet using **only free plans**, so you can put a live link on your
resume. It assumes you have never deployed anything: every term is explained, and every step says what to
click.

> **The golden rule: never enter a credit or debit card anywhere.** Every service below has a free plan
> that works without one. If a sign-up page asks for a card, **stop**, close the tab, and ask for help
> (see [If a service asks for a card](#if-a-service-asks-for-a-card)). Nothing in this guide can charge you
> unless *you* upgrade a plan, and none of the steps ask you to.

## The picture

```
 Visitor's browser ──► Vercel ............ the website (React), static files
        │
        └─ HTTPS, with your API key ─►  Render ............ the "backend": FastAPI + the indexing worker
                                           │        │        │
                                           ▼        ▼        ▼
                                    Supabase    Supabase   Cloudflare            Groq
                                    database    Storage    Workers AI            (writes the
                                    (text,      (the       (turns text           answers)
                                    vectors)    PDFs)      into vectors)
```

Words you'll meet:

| Word | Meaning |
|---|---|
| **Frontend** | The part people see in the browser (the React app). Hosted on **Vercel**. |
| **Backend / API** | The program that does the real work: storing files, searching, calling the AI. Hosted on **Render**. |
| **Deploy** | Copy your code to a company's computers so it runs on the internet instead of on your PC. |
| **Environment variable** | A named setting (like `GROQ_API_KEY`) given to a program from the outside. Secrets live here, never in your code or in git. |
| **API key** | A password-like string that identifies you to a service (Groq, Cloudflare…) or to *your own* API (the `dm_…` key). |
| **Docker / container** | A way to package a program with everything it needs so it runs the same everywhere. **You won't run Docker yourself**: Render builds it from [backend/Dockerfile](../backend/Dockerfile). See [docker-for-beginners.md](docker-for-beginners.md). |
| **Cold start** | A free server goes to sleep when nobody uses it; the first visit wakes it up, which takes about a minute. |

## The free stack, and its limits

| Service | Used for | Free plan limits | Card needed? |
|---|---|---|---|
| **GitHub** | Holds your code; Render and Vercel deploy from it | Unlimited public repositories | No |
| **Supabase** | Database + file storage | [2 free projects, 500 MB database, 1 GB storage, 5 GB egress](https://supabase.com/docs/guides/platform/billing-on-supabase). Free projects are [paused after about 7 days of low activity](https://supabase.com/docs/guides/platform/free-project-pausing) (you resume them with one click). | Not stated in its docs; it should not be needed. |
| **Render** | The backend | [750 free hours a month, 512 MB RAM, sleeps after 15 minutes idle, wipes its disk on restart](https://render.com/docs/free) | **Possibly**: see below. |
| **Vercel** | The website | The free "Hobby" plan (personal, non-commercial projects) | No (check when you sign up) |
| **Cloudflare Workers AI** | The bge-m3 embedding model | [10,000 neurons a day](https://developers.cloudflare.com/workers-ai/platform/pricing/): about 9 million tokens a day for bge-m3, enough for hundreds of documents. **When used up, calls fail; they never charge** on the free plan. | No, according to a [third-party source](https://www.mintlify.com/cheahjs/free-llm-api-resources/providers/free/cloudflare-workers-ai); verify when you sign up. |
| **Groq** | The language model | Free tier with rate limits (you already use it) | No |

What this means in practice: a few users and a few dozen documents are fine. Heavy use hits the limits, and
the app then shows an error message until the limit resets or you wait; **it never turns into a bill.**

## Before you start

1. The latest code must be on GitHub (`git push`). For free scheduled jobs (step 7) the repository should be **public**, which is also what you want for a portfolio.
2. Open a text file as a **scratch note** for values you'll collect. Treat them as passwords: never paste them into chat, an issue, or git.

## Step 1: Supabase (database + file storage)

1. **Create an account** at supabase.com (signing in with GitHub is fine) and a **New project**. Pick a region close to you and **write down the database password** (you can't read it again). A password without special characters is easier: otherwise you must URL-encode them later (`@` → `%40`, `/` → `%2F`, `:` → `%3A`).
2. **Storage → New bucket:** name it `documents` and keep it **private** (public switched off).
3. Open the **Connect** button at the top of the project page. It has tabs; you need two:
   - **Server tab**: copy **`SUPABASE_URL`** (like `https://abcdefgh.supabase.co`) and reveal-and-copy **`SUPABASE_SECRET_KEY`** (the `sb_secret_…` value: click the eye icon, then copy). The secret key bypasses all access rules, so it only ever goes into Render's environment and your own terminal. You don't need the `sb_publishable_…` key.
   - **Direct tab** (connection strings): choose the **Session pooler** method, port **5432**. Not "Direct connection" (it only works over IPv6, which Render doesn't use) and not "Transaction pooler". The string looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`. Replace the password placeholder with your password, then turn it into `DATABASE_URL` by changing the start to `postgresql+psycopg://` and adding `?sslmode=require` at the end.
4. You don't need to enable anything by hand: the app's database migrations create the `vector` extension and the tables, and turn on row-level security so Supabase's built-in REST API can't read your data.

## Step 2: Cloudflare Workers AI (free embeddings)

Embeddings turn text into numbers so the search can find similar meaning. Your PC does this with a GPU; the free
server has none, so Cloudflare does it, with the **same bge-m3 model** you use locally.

1. Create a free account at cloudflare.com (email and password; no card).
2. Find your **Account ID** (shown in the dashboard, for example in the right-hand column of the account home page).
3. Create an **API token**: *My Profile → API Tokens → Create Token*, using the **Workers AI** template (or a custom token with the *Workers AI* permission). Copy it once.
4. Your settings are:
   - `EMBEDDING_BASE_URL` = `https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1`
   - `EMBEDDING_API_KEY` = the token
   - `EMBEDDING_MODEL` = `@cf/baai/bge-m3` and `EMBEDDING_DIM` = `1024` (already in `render.yaml`)

The dashboard wording may differ slightly from these steps; the Account ID and a Workers AI token are all you need.

## Step 3: check your settings from your own PC (recommended)

Before Render is involved, run the self-test with the real values. It checks the database connection (and tells
you if you chose the wrong kind of connection string), uploads and deletes a tiny test file in your Supabase bucket,
calls the embedding API, and makes one small Groq call. It never prints a secret.

> **Tip on commands.** If your prompt starts with `(documind)`, the project's virtual environment is already
> active, and `py -m uv run …` will fail with *No module named uv*. In that case leave out the `py -m uv run`
> prefix (`documind doctor`, `documind create-user …`), or type `deactivate` first.

Set the values **in your own terminal** (never in chat), from the `backend` folder:

```bash
$env:DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
$env:STORAGE_BACKEND = "supabase"; $env:SUPABASE_URL = "https://<ref>.supabase.co"; $env:SUPABASE_SECRET_KEY = "sb_secret_..."
$env:EMBEDDER = "openai_compat"; $env:EMBEDDING_MODEL = "@cf/baai/bge-m3"
$env:EMBEDDING_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1"; $env:EMBEDDING_API_KEY = "..."
```

```bash
py -m uv run documind doctor
```

Expected: four lines starting with `[ OK]` and "All checks passed." Each failure prints a `->` hint (wrong
connection type, missing bucket, bad token, wrong vector size…). Fix those first: they're the same problems you'd
otherwise have to debug through Render's logs. Close the terminal afterwards.

## Step 4: Render (the backend)

1. Create an account at render.com, signing in with GitHub. **If it asks for a card, stop** (see below).
2. **New → Blueprint** → pick your repository. Render reads [render.yaml](../render.yaml); every service in it is on the free plan.
3. Fill in the secrets it asks for:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Session pooler string from step 1 |
   | `SUPABASE_URL` | the project URL |
   | `SUPABASE_SECRET_KEY` | the `sb_secret_…` key |
   | `EMBEDDING_BASE_URL` | the Cloudflare URL from step 2 |
   | `EMBEDDING_API_KEY` | the Cloudflare token |
   | `GROQ_API_KEY` | your Groq key |
   | `CORS_ORIGINS` | leave empty for now (step 6) |

4. Create it and watch the **Logs**. The first build takes a few minutes. Success looks like `Running upgrade … -> 0002` followed by `Uvicorn running`.
5. Open `https://<your-service>.onrender.com/health/ready`. Expected: `{"status":"ok","database":"up","embedder":"@cf/baai/bge-m3"}`. `/docs` shows the interactive API.

## Step 5: create your first user

There's no public sign-up: you create users with a command, against the production database, from your PC (in `backend/`). The variable overrides your local `.env` for that terminal only:

```bash
$env:DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

```bash
py -m uv run documind create-user you@example.com
```

Copy the `dm_…` key it prints (shown once). Close the terminal afterwards.

## Step 6: Vercel (the website)

1. Create an account at vercel.com with GitHub; choose the free **Hobby** plan. Don't enter a card.
2. **Add New → Project** → import the repository. Set **Root Directory** to `frontend`. Vercel detects Vite; [vercel.json](../frontend/vercel.json) adds security headers.
3. Add the environment variable `VITE_API_URL` = `https://<your-service>.onrender.com` (no trailing slash). It's read when the site is built, so changing it later means redeploying.
4. Deploy, then copy the site's address (for example `https://documind.vercel.app`).
5. Back in **Render → Environment**, set `CORS_ORIGINS` to that address (no trailing slash; several can be comma-separated). Render restarts the service. This is the rule that lets *your* website, and no other, call your API from a browser.

## Step 7: keep it awake enough (free)

[.github/workflows/keep-alive.yml](../.github/workflows/keep-alive.yml) calls your API once a day. That wakes
Render and touches the database, which should stop Supabase from pausing your project after a week without use.
In GitHub: *Settings → Secrets and variables → Actions → Variables → New repository variable*: `API_URL` =
`https://<your-service>.onrender.com`. Test it from the **Actions** tab with *Run workflow*.

## Step 8: smoke test

- [ ] Open your Vercel address and paste your `dm_…` key. The first request may take about a minute (Render waking up).
- [ ] Settings shows your Render address, status "Opérationnelle" and the embedding model name.
- [ ] Upload a small PDF. Progress runs through the stages to "Indexé", and a new file appears in Supabase → Storage → `documents`.
- [ ] Ask a question the document answers: the answer has a citation, and clicking it opens the page with the quote highlighted.
- [ ] Ask something the document doesn't cover: you get the amber "Je ne peux pas répondre" card.
- [ ] Delete the document: the file disappears from the bucket.

## When a free limit runs out

| What | What happens | What you do |
|---|---|---|
| Cloudflare 10,000 neurons/day | Uploads and questions fail with an embedding error until 00:00 UTC | Wait for the reset |
| Groq rate limit | Questions fail briefly with "rate limit" | Wait a minute |
| Render 750 hours/month | The service is suspended until next month | Don't keep it awake all day; it normally sleeps |
| Supabase 500 MB / 1 GB | Uploads fail | Delete old documents |
| Supabase paused (about 7 days idle) | The app can't reach the database | Supabase dashboard → *Restore/Resume project*; the keep-alive job helps prevent it |

## If a service asks for a card

Render's own support says it can ask for card details to **verify** an account (an authorization hold of about
$1 that is cancelled straight away), and some users report that a card is required. If any sign-up asks for one,
**do not enter it.** Stop and ask for help; here are the card-free ways forward:

- Try the free-plan signup again from a clean browser session, and make sure the service type shown is **Free**.
- Other free container hosts exist (for example Koyeb or Back4App), but their current terms are unverified here: check each one's pricing page for "no credit card" before using it, and don't assume. (Hugging Face Docker Spaces, which used to be a common free choice, now require a paid plan.)
- Demo from your own PC: run the app locally (as in [testing.md](testing.md)) and show it in an interview. A free Cloudflare Tunnel can give it a temporary public address.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Browser console: *blocked by CORS policy* | `CORS_ORIGINS` doesn't exactly match the page's address (scheme, no trailing slash, no path). Fix it in Render and wait for the restart. |
| UI says "API injoignable" for the first minute | Free instance waking up. Wait, then reload. |
| Render deploy fails on the migration with *Tenant or user not found* | Wrong pooler user: it must be `postgres.<project-ref>`, not plain `postgres`. |
| *connection timed out* to the database | You used the **Direct** connection (IPv6). Switch to the Session pooler string. |
| *password authentication failed* | Wrong password, or special characters not URL-encoded in `DATABASE_URL`. |
| Upload fails with `storage_error` | The bucket name or key is wrong, or the bucket doesn't exist. `documind doctor` shows the HTTP status. If it's 401/403 with an `sb_secret_…` key, try the **legacy `service_role` key** (Project Settings → API Keys → Legacy) as `SUPABASE_SECRET_KEY`. This behaviour is tested with fakes only, not against a live Supabase project. |
| Document stays "En attente" | The in-process worker isn't running: check `RUN_WORKER_IN_API=true` and the logs. |
| Document ends in `embedding_error` | Wrong Cloudflare token or Account ID in the URL, or the vectors aren't 1024-dimensional (the message says which). If the response format is the problem, set `EMBEDDING_API_STYLE=cloudflare` and drop the `/v1` from the base URL. The Cloudflare response format for bge-m3 couldn't be confirmed from its docs, which is why the app understands both. |
| `embedding_unavailable` | The daily allowance is used up, or a rate limit: wait. |
| Out-of-memory restarts while indexing a big PDF | The free instance has 512 MB. Lower `MAX_UPLOAD_BYTES`, or split the PDF. |

## Security checklist for a public deployment

- **The secret key and database password exist only in Render's environment (and your own terminal).** If either leaks, rotate it in Supabase.
- **No public sign-up;** whoever holds a `dm_…` key can use your free Groq and Cloudflare quota. Share keys carefully. There's no rate limiting yet (Phase 6 on the project plan).
- API keys live in the browser's `localStorage`: fine for a personal or demo deployment, not for a multi-user product. Proper login (for example Supabase Auth) would replace it.
- Uploaded documents and questions are sent to Cloudflare and Groq. Don't put confidential documents through them unless their terms suit you.

## Changing things later

- **A different embedding model or provider:** change `EMBEDDING_*`, redeploy, then **reindex** every document. The new model must output **1024** dimensions, because the column is `vector(1024)`. Vectors from different models can't be compared; every chunk records the model that made it, and search only looks at chunks from the current model.
- **Rolling back:** Render keeps previous deploys (Events → Rollback).
