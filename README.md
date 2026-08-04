# Event Radar — Open Data Demo

An AI-powered event discovery assistant: tell it what you're into, in your own words, and it surfaces upcoming, ongoing, and just-past Hong Kong events that actually match — ranked and explained by an LLM, refined over time by your feedback.

**Live demo:** [events-demo.carsonng.com](https://events-demo.carsonng.com)

This is the public demo build of a larger personal project. It's deliberately scoped to a single data source — see [Data source & license](#data-source--license) below for why.

---

## What this demonstrates

- **Two-stage ranking, not "throw everything at the LLM."** A cheap keyword/category filter narrows the catalog down to a shortlist before the LLM ever sees it. Only the shortlist gets the expensive structured-output rerank call that scores fit (0–100) and writes a one-sentence, specific reason for the match.
- **The LLM layer fails without taking the app down with it.** Interest parsing and reranking both degrade to a naive fallback (keyword splitting, stage-1-only ranking) on rate limits, network errors, or auth failures, instead of a 500.
- **A personalization loop that actually closes.** Thumbs up/down on an event nudges category/keyword weights in your interest profile, which feed back into ranking on the next refresh.
- **Deterministic extraction first, an LLM only where structure genuinely runs out.** Where a source page embeds structured data, it's parsed directly — free, instant, no model judgment needed. An LLM fallback only kicks in for genuinely unstructured free text, and is deliberately scoped (a short excerpt, not a full page) to control both cost and hallucination risk.
- **Observability on the AI layer itself.** Every LLM call logs tokens/latency/estimated cost; every ingest run logs fetch/new/updated counts. Surfaced in-app, not buried in logs.

## Data source & license

Every event shown here comes from **[DATA.GOV.HK](https://data.gov.hk)**, Hong Kong's official open data portal — specifically its URBTIX open-data feed, published by the **Leisure and Cultural Services Department (LCSD)**.

This matters: DATA.GOV.HK's [Terms of Use](https://data.gov.hk/en/terms-and-conditions) grant explicit, written permission to use this data for both commercial and non-commercial purposes, free of charge, conditional on attribution and acknowledging the Government's intellectual property rights. That's a fundamentally different situation from most public websites, which display data without granting any reuse license at all.

This repository intentionally contains **only** the URBTIX connector. A larger private version of this project also aggregates a few other Hong Kong event sources — those aren't included here, on purpose: this public repo shouldn't carry code for fetching data from sites that haven't granted an explicit reuse license, regardless of whether it's actually invoked at runtime.

No guarantee is made as to the accuracy, completeness, or timeliness of the data shown — DATA.GOV.HK and LCSD's original data always take precedence.

## Architecture

FastAPI backend (`backend/`) + React/TypeScript frontend (`frontend/`), single process in production — the API is mounted under `/api/*` and the built frontend is served from the same process, so deployment is one port, no CORS setup needed.

```
backend/app/
  connectors/urbtix.py   — the only data source in this build
  ranking.py              — stage-1 keyword/semantic filter + stage-2 LLM rerank
  ingest_job.py            — scheduled fetch/dedupe/rerank orchestration
  venue_llm.py             — deterministic-first, LLM-fallback venue extraction
                              (present but inert here — its fallback sources
                              are the connectors this repo doesn't include)
  ask.py                   — natural-language Q&A over the ranked catalog
frontend/src/               — React app, bilingual (Traditional Chinese / English)
```

## Running locally

```bash
# backend
cd backend
python -m venv venv
venv/Scripts/activate  # or source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env   # fill in an OpenAI-compatible API key; set DEMO_MODE=1
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```

`DEMO_MODE=1` is required — the only connector present is urbtix, and the app is built to fail loudly (an ImportError, not a silent misconfiguration) if it isn't set, since the code for anything else genuinely isn't here.

## Tests

```bash
cd backend
DEMO_MODE=1 pytest
```

---

*This is a personal portfolio and technical demonstration project, developed strictly for non-commercial purposes.*
