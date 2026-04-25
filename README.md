# new_all3_radar_bot

Clean rebuild of the All3 news monitoring stack with two separate products:

- News Radar Bot: disciplined collector/notifier focused on recall with sane filters
- Weekly Digest Bot: manual editorial digest generator focused on selection quality

## Principles

- Direct-source priority over wrappers
- Google News limited to a narrow competitor-check layer
- SQLite-first, explicit, inspectable storage
- Gemini used sparingly for Bot 1 summaries and borderline calls
- Claude used only for Bot 2 weekly selection and writing
- Freshness based on published date, not collected date by default

## Repository layout

- `src/all3_radar/`: application code
- `config/`: explicit source, competitor, and ranking inventories
- `tests/`: unit and integration tests
- `docs/`: architecture and operations notes
- `data/`: local runtime database path

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --no-build-isolation -e .[dev]
python -m all3_radar.app.admin_cli db init
python -m all3_radar.app.admin_cli sources list
python -m all3_radar.app.radar_cli run --dry-run
```
