# Daily Web Discovery

Daily web discovery is a report-only layer for finding off-source news candidates through Tavily search plus Claude review.

It is intentionally separate from the hourly radar pipeline:

- It does not send Telegram cards.
- It does not insert candidates into the main radar tables.
- It restores and reads the current radar database so it can skip URLs that already passed through the bot.
- It writes Markdown and JSON reports under `data/web-discovery/`.

## Run Locally

```powershell
$env:ANTHROPIC_API_KEY="..."
$env:TAVILY_API_KEY="..."
$env:DATABASE_PATH="data/all3_radar.db"
$env:WEB_DISCOVERY_MAX_SEARCH_USES="8"
python -m all3_radar.app.radar_cli discover-web
```

The command refuses to run if `DATABASE_PATH` does not exist, because discovery without history dedupe would produce misleading results.

## GitHub Actions

The workflow is `Daily Web Discovery`.

- Manual runs are available through `workflow_dispatch`.
- Scheduled runs are gated by the repository variable `WEB_DISCOVERY_ENABLED=true`.
- Reports are uploaded as `web-discovery-<run_id>` artifacts.

Recommended starting settings:

```text
WEB_DISCOVERY_ENABLED=false
WEB_DISCOVERY_MAX_SEARCH_USES=8
WEB_DISCOVERY_MAX_CANDIDATES=20
WEB_DISCOVERY_MAX_NEW_CANDIDATES=12
WEB_DISCOVERY_TIMEOUT_SECONDS=180
WEB_DISCOVERY_MAX_TOKENS=2500
WEB_DISCOVERY_TAVILY_SEARCH_DEPTH=basic
WEB_DISCOVERY_TAVILY_INCLUDE_RAW_CONTENT=true
```

Recommended secrets:

```text
ANTHROPIC_API_KEY
TAVILY_API_KEY
```

The default mode is:

- Tavily finds fresh candidate URLs within the freshness window.
- Claude reviews only the fetched results instead of searching the web itself.
- The bot still dedupes against the live radar database before anything is accepted for review.

The default freshness window is 2 days for daily discovery. This covers indexing delays and time zones without repeatedly dragging week-old evergreen material into daily runs.

## Query Packs

Editorial search briefs live in `config/web_discovery.yaml`.

Each query pack contains:

- `goal`: what this pack is trying to find.
- `include_signals`: concrete signals that make a story useful.
- `exclude_signals`: common false positives.
- `queries`: precise search strings.

This keeps discovery signal-based rather than broad-topic-based.

## Promotion Path

The safe rollout path is:

1. Report-only dry run.
2. Human review of artifacts for several days.
3. Optional DB ingest mode once quality is stable.
4. Optional Telegram send gate after migration to server/GitLab and persistent DB.
