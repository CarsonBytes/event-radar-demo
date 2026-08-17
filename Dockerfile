# Multi-stage build mirroring deploy/run-production.ps1's own two steps
# (build frontend, then run backend serving frontend/dist as static files
# from the same process -- see app/main.py's app.mount("/", ...)). Pattern
# copied from D:\adaptive_study_platform\Dockerfile, which is the verified
# reference for this machine's WSL2 Docker deployment -- see deploy/wsl-deploy.sh
# for how this actually gets built and run.
#
# Base images pinned to digest, not floating tags -- required for the
# pre-push hook (deploy/hook-deploy.sh) to be genuinely deterministic. A tag
# like `python:3.12-slim` can point at different bytes tomorrow than it does
# today; the digest can't. Pinned to what was actually resolved and verified
# working during this deployment's initial build (2026-08-12). To pick up a
# real upstream security update later, re-resolve deliberately with
# `docker pull <image>:<tag>` + `docker inspect --format '{{index .RepoDigests 0}}'`
# rather than letting it drift silently on every rebuild.
FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
WORKDIR /app

# Deps installed from pyproject.toml/uv.lock, not backend/requirements.txt --
# that file is kept only for a plain `pip install -r requirements.txt` local
# dev workflow (see README's "Running locally"); the native Windows/venv
# production deployment it used to serve is fully decommissioned (this
# Dockerfile is the only production path now). uv.lock pins exact resolved
# versions (incl. transitive deps) instead of pip's requirements.txt
# forwards-compat ranges. Copied before the rest of the app code so this
# layer only rebuilds when dependencies actually change, not on every code
# edit.
COPY backend/pyproject.toml backend/uv.lock ./
# This network has shown flaky/slow throughput to PyPI from inside WSL2
# before (the earlier pip install hit the same ReadTimeoutError against
# pythonhosted.org and needed a retry) -- a longer per-request timeout and
# more retries absorbs that instead of failing the whole build on one slow
# package.
ENV UV_HTTP_TIMEOUT=120
RUN uv sync --locked --no-install-project --no-dev

COPY backend/ .
RUN uv sync --locked --no-dev

# app/main.py resolves the frontend as BACKEND_DIR.parent / "frontend" / "dist"
# -- BACKEND_DIR is backend/'s own dir (this Dockerfile's WORKDIR, /app), so
# frontend/dist must land at /frontend/dist, one level above /app, to match
# that same relative layout without any code change for the container case.
COPY --from=frontend-build /frontend/dist /frontend/dist

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
