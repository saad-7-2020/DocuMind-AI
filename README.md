# DocuMind AI

A production-style Retrieval-Augmented Generation (RAG) platform: upload PDF, DOCX and TXT files (including
scanned PDFs), ask questions in natural language, and get answers grounded in your documents with verifiable
citations, or an explicit "insufficient evidence" response. Built as a learning and portfolio project, with a
reproducible evaluation framework.

**Status:** Phase 2 (minimal end-to-end pipeline) done: upload PDF/TXT → index with bge-m3 on GPU → dense retrieval → French answers from Groq with page-level citations. 60 tests pass. Next: Phase 3 (hybrid search, reranking, OCR, abstention).

- Architecture, data model, API contracts and phase plan: [docs/architecture.md](docs/architecture.md)
- Phase 2 guide (decisions, run commands, acceptance): [docs/phase-2.md](docs/phase-2.md)
- Frontend (React + TypeScript): `frontend/`, run with `npm --prefix frontend run dev`
- **How to test the app:** [docs/testing.md](docs/testing.md)
- **Deploy for $0, no card (Vercel + Supabase + Cloudflare + Groq):** [docs/deployment.md](docs/deployment.md), with [Docker explained](docs/docker-for-beginners.md)
