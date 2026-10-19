# Deploy DocuMind AI for $0 (no credit card)

This guide puts the app on the internet using **only free plans**, so you can put a live link on your
resume. It assumes you have never deployed anything: every term is explained, and every step says what to
click.

> **The golden rule: never enter a credit or debit card anywhere.** Every service below has a free plan
> that works without one. If a sign-up page asks for a card, **stop**, close the tab, and ask for help.
> Nothing in this guide can charge you unless *you* upgrade a plan, and none of the steps ask you to.

## The picture

```
 Visitor's browser ──► Vercel project 1 ......... the website (React), static files
        │
        └─ HTTPS, with your API key ─► Vercel project 2 ......... the "backend": FastAPI as a serverless function
                                          │        │        │
                                          ▼        ▼        ▼
                                   Supabase    Supabase   Cloudflare            Groq
                                   database    Storage    Workers AI            (writes the
                                   (text,      (the       (turns text           answers)
                                   vectors)    PDFs)      into vectors)
```

Why Vercel for both parts? Render (the usual free host for a backend) [can ask for a payment card to verify
an account](https://community.render.com/t/free-but-credit-card-first/24630), and Vercel's free plan doesn't. A
Vercel account is needed for the website anyway, so this is also one account fewer.

Words you'll meet:

| Word | Meaning |
|---|---|
| **Frontend** | The part people see in the browser (the React app). |
| **Backend / API** | The program that does the real work: storing files, searching, calling the AI. |
| **Serverless function** | Your backend code, started by the host when a request arrives and stopped afterwards. You don't manage a server. |
| **Deploy** | Copy your code to a company's computers so it runs on the internet instead of on your PC. |
| **Environment variable** | A named setting (like `GROQ_API_KEY`) given to a program from the outside. Secrets live here, never in your code or in git. |
| **API key** | A password-like string that identifies you to a service (Groq, Cloudflare…) or to *your own* API (the `dm_…` key). |
| **Cold start** | After some idle time the first request starts the function from scratch, which takes a few seconds. |

## The free stack, and its limits

| Service | Used for | Free plan limits | Card needed? |
|---|---|---|---|
| **GitHub** | Holds your code; Vercel deploys from it | Unlimited public repositories | No |
| **Vercel (Hobby)** | The website **and** the backend | [Free, for personal non-commercial projects](https://vercel.com/docs/plans/hobby). Functions: [2 GB memory, up to 5 minutes per request, 4.5 MB request body](https://vercel.com/docs/functions/limitations). Included each month: 1,000,000 invocations and 4 CPU-hours of active compute; if you go over, [you wait until the month resets](https://vercel.com/docs/plans/hobby). | No (the docs mention a card only for upgrading) |
| **Supabase** | Database + file storage | [2 free projects, 500 MB database, 1 GB storage, 5 GB egress](https://supabase.com/docs/guides/platform/billing-on-supabase). Free projects are [paused after about 7 days of low activity](https://supabase.com/docs/guides/platform/free-project-pausing) (resume with one click). | Not stated; it should not be needed |
| **Cloudflare Workers AI** | The bge-m3 embedding model | [10,000 neurons a day](https://developers.cloudflare.com/workers-ai/platform/pricing/), about 9 million tokens for bge-m3. **When used up, calls fail; they never charge** on the free plan. | No, according to a [third-party source](https://www.mintlify.com/cheahjs/free-llm-api-resources/providers/free/cloudflare-workers-ai); verify when you sign up |
| **Groq** | The language model | Free tier with rate limits | No |

What this means: a few users and a few dozen documents are fine. Heavy use hits a limit and the app shows an
error until it resets; **it never turns into a bill.**

### Two limits that shape the app on Vercel

- **A file can be at most 4 MB.** Vercel rejects larger request bodies (4.5 MB), so the app is set to 4 MB and the website tells you so. Most text PDFs fit; scanned or image-heavy PDFs may not.
- **Indexing happens during the upload.** A serverless function can't keep a background worker alive, so the upload request itself indexes the document (about 5 seconds for a short PDF; the limit is 5 minutes). If something fails, the website's status check retries it.

## Before you start

1. The latest code must be on GitHub (`git push`). For the free scheduled job in step 8 the repository should be **public**, which is also what you want for a portfolio.
2. Open a text file as a **scratch note** for values you'll collect. Treat them as passwords: never paste them into chat, an issue, or git.

## Step 1: Supabase (database + file storage)

1. **Create an account** at supabase.com (signing in with GitHub is fine) and a **New project**. Pick a region close to you and **write down the database password** (you can't read it again). A password without special characters is easier: otherwise you must URL-encode them later (`&` → `%26`, `@` → `%40`, `/` → `%2F`, `:` → `%3A`).
2. **Storage → New bucket:** name it `documents` and keep it **private** (public switched off).
3. Open the **Connect** button at the top of the project page. It has tabs; you need two:
   - **Server tab**: copy **`SUPABASE_URL`** (like `https://abcdefgh.supabase.co`) and reveal-and-copy **`SUPABASE_SECRET_KEY`** (the `sb_secret_…` value: click the eye icon, then copy). The secret key bypasses all access rules, so it only ever goes into Vercel's environment settings and your own terminal. You don't need the `sb_publishable_…` key.
   - **Direct tab** (connection strings): choose the **Session pooler** method, port **5432**. Not "Direct connection" (it only works over IPv6, which neither your PC nor Vercel uses) and not "Transaction pooler". The string looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`. Replace the password placeholder with your password, then turn it into `DATABASE_URL` by changing the start to `postgresql+psycopg://` and adding `?sslmode=require` at the end.
4. You don't need to create tables by hand: the app's migrations do it (step 3).

## Step 2: Cloudflare Workers AI (free embeddings)

Embeddings turn text into numbers so the search can find similar meaning. Your PC does this with a GPU; a
serverless function has none, so Cloudflare does it, with the **same bge-m3 model** you use locally.

1. Create a free account at cloudflare.com (email and password; no card).
2. Find your **Account ID** (shown in the dashboard, for example in the right-hand column of the account home page).
3. Create an **API token**: *My Profile → API Tokens → Create Token*, using the **Workers AI** template (or a custom token with the *Workers AI* permission). Copy it once.
4. Your settings are:
   - `EMBEDDING_BASE_URL` = `https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1`
   - `EMBEDDING_API_KEY` = the token
   - `EMBEDDING_MODEL` = `@cf/baai/bge-m3` and `EMBEDDING_DIM` = `1024`

The dashboard wording may differ slightly; the Account ID and a Workers AI token are all you need.

## Step 3: check your settings and create the tables, from your own PC

> **Tip on commands.** If your prompt starts with `(documind)`, the project's virtual environment is already
> active, and `py -m uv run …` will fail with *No module named uv*. In that case leave out the `py -m uv run`
> prefix (`documind doctor`, `alembic upgrade head`), or type `deactivate` first.

Set the values **in your own terminal** (never in chat), from the `backend` folder:

```bash
$env:DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
$env:STORAGE_BACKEND = "supabase"; $env:SUPABASE_URL = "https://<ref>.supabase.co"; $env:SUPABASE_SECRET_KEY = "sb_secret_..."
$env:EMBEDDER = "openai_compat"; $env:EMBEDDING_MODEL = "@cf/baai/bge-m3"
$env:EMBEDDING_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1"; $env:EMBEDDING_API_KEY = "..."
```

The self-test checks the database connection (and tells you if you picked the wrong kind of connection string),
uploads and deletes a tiny test file in your bucket, calls the embedding API, and makes one small Groq call. It
never prints a secret.

```bash
py -m uv run documind doctor
```

Expected: four lines starting with `[ OK]` and "All checks passed." Each failure prints a `->` hint. Then create
the tables (this is safe to repeat; it only applies what's missing):

```bash
py -m uv run alembic upgrade head
```

> **Already verified once.** This exact stack (Supabase database + storage, Cloudflare bge-m3, Groq), loaded
> through the same `backend/index.py` file Vercel uses and in the same "index during the upload" mode, was
> rehearsed end to end on 2026-10-18: upload, indexing in about 5 seconds, a cited answer in about a second, a
> refusal on an unanswerable question, and deletion. What that rehearsal can't cover is Vercel itself.

Close the terminal afterwards so the secrets don't linger in your session.

## Step 4: Vercel project 1, the backend

1. Create an account at vercel.com with GitHub and choose the free **Hobby** plan. **Don't enter a card.**
2. **Add New → Project** → import your repository.
3. Set **Root Directory** to `backend`, and the project name to something like `documind-api`. Vercel detects FastAPI by itself. The files [backend/index.py](../backend/index.py) (the entry point), [backend/vercel.json](../backend/vercel.json) (Dublin region, 5-minute limit) and `.python-version` (3.13) are already prepared.
4. Open **Environment Variables** and add (the same value applies to all environments):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Session pooler string from step 1 |
   | `STORAGE_BACKEND` | `supabase` |
   | `SUPABASE_URL` | the project URL |
   | `SUPABASE_SECRET_KEY` | the `sb_secret_…` key |
   | `SUPABASE_BUCKET` | `documents` |
   | `STORAGE_DIR` | `/tmp/documind` |
   | `MAX_UPLOAD_BYTES` | `4000000` |
   | `EMBEDDER` | `openai_compat` |
   | `EMBEDDING_BASE_URL` | the Cloudflare URL from step 2 |
   | `EMBEDDING_API_KEY` | the Cloudflare token |
   | `EMBEDDING_MODEL` | `@cf/baai/bge-m3` |
   | `EMBEDDING_DIM` | `1024` |
   | `GROQ_API_KEY` | your Groq key |
   | `INLINE_JOBS` | `true` |
   | `DB_POOL_SIZE` | `2` |
   | `DB_MAX_OVERFLOW` | `2` |
   | `JOB_TIMEOUT_S` | `400` |
   | `LOG_LEVEL` | `INFO` |
   | `IP_HASH_SALT` | a long random text (for example 40 random characters; never reuse a password) |
   | `CRON_SECRET` | another long random text: Vercel sends it to the daily cleanup job that deletes expired demo accounts |
   | `CREATOR_NAME` | the name the assistant gives when asked who created it (default `Saad`) |

   Optional: `LLM_LIGHT_MODEL` (small model for rewriting follow-ups and describing documents, default
   `llama-3.1-8b-instant`), and the `DEMO_*` limits listed in [backend/.env.example](../backend/.env.example).

   Leave `CORS_ORIGINS` for step 7.
5. **Deploy.** When it finishes, open `https://<your-project>.vercel.app/health/ready`. Expected: `{"status":"ok","database":"up","embedder":"@cf/baai/bge-m3","max_upload_bytes":4000000}`. `/docs` shows the interactive API. If you see a Vercel *login page* instead, turn off **Vercel Authentication** for this project (Settings → Deployment Protection): an API called from a website can't log in.

## Step 5: create your first user

There's no public sign-up: you create users with a command, against the production database, from your PC (in
`backend/`). Set `DATABASE_URL` as in step 3 in that terminal, then:

```bash
py -m uv run documind create-user you@example.com
```

Copy the `dm_…` key it prints (shown once). Close the terminal afterwards.

## Step 6: Vercel project 2, the website

1. **Add New → Project** → import the **same** repository again.
2. Set **Root Directory** to `frontend` (project name for example `documind`). Vercel detects Vite; [frontend/vercel.json](../frontend/vercel.json) adds security headers.
3. Add the environment variable `VITE_API_URL` = the backend's address from step 4 (like `https://documind-api.vercel.app`, no trailing slash). It's read when the site is *built*, so changing it later means redeploying.
4. Deploy and copy the site's address (for example `https://documind.vercel.app`).

## Step 7: let the website talk to the backend

In the **backend** project: *Settings → Environment Variables* → add `CORS_ORIGINS` = the website's address
(no trailing slash; several can be comma-separated). Then **redeploy the backend** (*Deployments → ⋯ → Redeploy*):
Vercel applies a changed variable only to new deployments. This rule is what lets *your* website, and no other,
call your API from a browser.

## Step 8: keep the database awake (free)

[.github/workflows/keep-alive.yml](../.github/workflows/keep-alive.yml) calls your backend once a day. That
touches the Supabase database, which should stop Supabase from pausing your project after a week without use. In
GitHub: *Settings → Secrets and variables → Actions → Variables → New repository variable*: `API_URL` =
`https://<your-backend>.vercel.app`. Test it from the **Actions** tab with *Run workflow*.

## Step 8b: the demo accounts (recruiters)

The login screen has a **Try the demo** button. It creates a private account in one click, with no email and no
password: the visitor gets an access code like `docu-mindk43trs8q2m` and a direct link
(`https://<your-site>/#/u/docu-mindk43trs8q2m`) that opens their space. A demo account is limited (5 documents,
40 questions a day, 20 chats) and is deleted after 7 days without use, so a flood of visitors cannot fill your free
storage. A wrong code is throttled (10 failures per network per 15 minutes). The cleanup runs daily through the
`crons` entry in [backend/vercel.json](../backend/vercel.json) and also whenever a new demo is created; you can run
it by hand with `documind purge-demo`.

**Applying the new tables** (migration `0003`: chats, document descriptions, demo accounts) is required once,
**before** the new code answers any request. From `backend/`, with the production `DATABASE_URL` set as in step 3:

```bash
py -m uv run alembic upgrade head
```

## Step 9: smoke test

- [ ] Open the website address and paste your `dm_…` key, or click **Try the demo** and check the access code and direct link work (log out, then open the link).
- [ ] Settings shows your backend address, status "Opérationnelle" and the embedding model name.
- [ ] The upload zone says "4 Mo max". Upload a small PDF: it goes straight to "Indexé", and a new file appears in Supabase → Storage → `documents`.
- [ ] Ask a question the document answers: the answer has a citation, and clicking it opens the page with the quote highlighted.
- [ ] Ask something the document doesn't cover: you get the amber "Je ne peux pas répondre" card.
- [ ] Delete the document: the file disappears from the bucket.

## When a free limit runs out

| What | What happens | What you do |
|---|---|---|
| Cloudflare 10,000 neurons/day | Uploads and questions fail with an embedding error until 00:00 UTC | Wait for the reset |
| Groq rate limit | Questions fail briefly with "rate limit" | Wait a minute |
| Vercel monthly compute | Functions are blocked until the month resets | Wait; there is no charge |
| Supabase 500 MB / 1 GB | Uploads fail | Delete old documents |
| Supabase paused (about 7 days idle) | The app can't reach the database | Supabase dashboard → *Restore/Resume project*; the keep-alive job helps prevent it |

## If a service asks for a card

**Do not enter it.** Stop and ask for help. For reference: Render's own support says it can ask for card details
to verify an account (an authorization hold of about $1 that is cancelled straight away), which is why this guide
hosts the backend on Vercel instead. Other free container hosts exist, but their current terms are unverified here
(Koyeb is reported to require a card now; Hugging Face Docker Spaces need a paid plan). For a demo you can also run
the app on your own PC ([testing.md](testing.md)) and show it in an interview.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Browser console: *blocked by CORS policy* | `CORS_ORIGINS` doesn't exactly match the website's address (scheme, no trailing slash, no path), or you didn't redeploy the backend after setting it. |
| The backend returns an HTML login page | Vercel Authentication is on for the backend project: Settings → Deployment Protection → turn it off. |
| Upload fails with *413* / `FUNCTION_PAYLOAD_TOO_LARGE` | The file is over about 4.5 MB (Vercel's limit). Use a smaller file or split the PDF. |
| *504* / `FUNCTION_INVOCATION_TIMEOUT` | Indexing took more than 5 minutes (a very large document). Split it. |
| First request after a pause takes a few seconds | Cold start. Normal. |
| Build fails or `No module named …` | Check the project's **Root Directory** is `backend`, and look at the build log; the dependency list is [backend/pyproject.toml](../backend/pyproject.toml). |
| *Tenant or user not found* | Wrong pooler user: it must be `postgres.<project-ref>`, not plain `postgres`. |
| *connection timed out* to the database | You used the **Direct** connection (IPv6). Switch to the Session pooler string. |
| *password authentication failed* | Wrong password, or special characters not URL-encoded in `DATABASE_URL`. |
| Upload fails with `storage_error` | Bucket name or key wrong, or the bucket doesn't exist. `documind doctor` shows the HTTP status. (`sb_secret_…` keys were verified against a live project.) |
| Document ends in `embedding_error` | Wrong Cloudflare token or Account ID in the URL, or the vectors aren't 1024-dimensional (the message says which). Verified against a live account: the OpenAI-compatible endpoint (`…/ai/v1`) returns standard 1024-dimensional bge-m3 vectors. |
| `embedding_unavailable` | The daily allowance is used up, or a rate limit: wait. |
| Many *"too many connections"*-style database errors | Keep `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` small (2 and 2): every function instance holds its own pool. |

## Security checklist for a public deployment

- **The secret key and database password exist only in Vercel's environment settings (and your own terminal).** If either leaks, rotate it in Supabase.
- **No public sign-up;** whoever holds a `dm_…` key can use your free Groq and Cloudflare quota. Share keys carefully. There's no rate limiting yet (Phase 6 on the project plan). If a key leaks, replace it from your PC (set `DATABASE_URL` as in step 3): `documind list-keys` shows key prefixes and their status, `documind create-key you@example.com` issues a new key (shown once), and `documind revoke-key dm_Abc12` revokes the key starting with that prefix. A revoked key stops working at once.
- API keys live in the browser's `localStorage`: fine for a personal or demo deployment, not for a multi-user product. Proper login (for example Supabase Auth) would replace it.
- Uploaded documents and questions are sent to Cloudflare and Groq. Don't put confidential documents through them unless their terms suit you.

## Changing things later

- **A different embedding model or provider:** change `EMBEDDING_*`, redeploy, then **reindex** every document. The new model must output **1024** dimensions, because the column is `vector(1024)`. Vectors from different models can't be compared; every chunk records the model that made it, and search only looks at chunks from the current model.
- **New database migrations:** run `alembic upgrade head` from your PC with the production `DATABASE_URL`, as in step 3.
- **Rolling back:** Vercel keeps previous deployments (Deployments → ⋯ → Promote to Production).

## Appendix: the same backend on Render (optional)

If you ever have a payment card you're comfortable giving Render for verification (it should not charge a free
service), [render.yaml](../render.yaml) and [backend/Dockerfile](../backend/Dockerfile) describe a free Render web
service that runs the API with a background worker thread instead of inline indexing and allows larger uploads
(set `RUN_WORKER_IN_API=true`, leave `INLINE_JOBS` off). A free Render service [sleeps after 15 minutes without
requests and wipes its disk on restart](https://render.com/docs/free). The steps are the same as above, with
Render's *New → Blueprint* instead of Vercel project 1. This path is not needed for the project and isn't covered
in the smoke test.
