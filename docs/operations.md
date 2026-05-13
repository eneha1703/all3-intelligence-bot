# Operations

## Local setup

```bash
python -m pip install --no-build-isolation -e .[dev]
python -m all3_radar.app.admin_cli db init
python -m all3_radar.app.admin_cli sources list
```

## Radar run

```bash
python -m all3_radar.app.radar_cli run --dry-run
```

## Windows-triggered GitHub run

If GitHub scheduled runs stay unreliable, trigger the scheduler workflow from Windows Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/trigger_news_radar_scheduler.ps1 -GithubToken YOUR_FINE_GRAINED_PAT
```

Recommended token:
- fine-grained PAT scoped to `egalimova-eng/all3_intelligence_radar`
- repository permission: `Actions: write`

## Digest run

```bash
python -m all3_radar.app.digest_cli build --week 2026-W17
```
