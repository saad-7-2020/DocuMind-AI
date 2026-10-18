# Docker, explained for this project

You don't need to install or run Docker to deploy DocuMind AI: **Render builds and runs the container for
you.** This page explains what it's doing, so you can understand the build logs and talk about it in
interviews.

## The idea in four sentences

A program works on your PC because of everything around it: the Python version, the installed libraries, the
folders. A **Docker image** is a frozen snapshot of the program *plus* all of that. A **container** is a running
copy of an image. The same image behaves the same on your PC, on Render, or anywhere, which ends "it works on my
machine".

## Our Dockerfile, line by line

[backend/Dockerfile](../backend/Dockerfile) is the recipe Render follows. Each instruction adds a **layer**; Docker
reuses unchanged layers, which makes rebuilds fast.

| Instruction | What it does here |
|---|---|
| `FROM python:3.13-slim` | Start from a small Linux with Python 3.13 already installed. |
| `ENV …` | Sets environment variables (don't write `.pyc` files, flush logs immediately, where `uv` puts the virtualenv). |
| `RUN pip install uv==…` | Installs `uv`, the fast Python package installer, used to install our libraries. |
| `WORKDIR /app` | Sets the working folder inside the image. |
| `COPY pyproject.toml uv.lock ./` then `COPY src ./src` | Copies the dependency list and the code in. **Dependencies come first** so this expensive layer is reused when only code changes. |
| `RUN uv sync --frozen --no-dev` | Installs exactly the versions in `uv.lock`, without test tools and without PyTorch (production uses Cloudflare for embeddings, which keeps the image small enough for a 512 MB server). |
| `COPY alembic.ini` / `COPY migrations` | The database migration files, run at every start. |
| `RUN useradd … USER app` | Runs the program as a normal user, not as root: if it were ever compromised, it can do less. |
| `CMD ["sh", "-c", "alembic upgrade head && exec uvicorn …"]` | What runs when the container starts: first update the database schema, then start the web server on the port Render gives us in `$PORT`. |

`backend/.dockerignore` lists what is *not* copied into the image (your virtualenv, tests, and above all your
`.env` file with secrets).

## How this connects to Render

1. You push code to GitHub.
2. Render sees the push, reads `render.yaml`, and runs the Dockerfile to build an image (this is the **build log**).
3. Render starts a container from it (the **deploy log**), sets the environment variables you filled in, and checks
   `/health/live` to see that it answers.
4. If it fails, the log says where: a missing library fails the build; a wrong database URL fails the start-up.

## If you want to practise Docker yourself (optional)

Docker Desktop has been unreliable on this PC, so it isn't needed for the project. When you want to learn it
hands-on, the free [Play with Docker](https://labs.play-with-docker.com) browser sandbox needs no installation. A
good exercise: write a Dockerfile for a tiny FastAPI "hello" app, build it, run it, and compare it to ours.
