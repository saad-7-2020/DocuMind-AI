"""Vercel entrypoint: Vercel looks for a top-level `app` in this file (project root = backend/).

Production settings come from environment variables set in the Vercel project (see docs/deployment.md):
STORAGE_BACKEND=supabase, EMBEDDER=openai_compat, INLINE_JOBS=true, MAX_UPLOAD_BYTES=4000000, ...
`src/` is added to the import path so the `documind` package is importable whether or not the
platform installed the project itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from documind.api.app import create_app_from_env  # noqa: E402

app = create_app_from_env()
