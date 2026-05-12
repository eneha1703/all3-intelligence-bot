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

## Remote radar trigger

If GitHub scheduled runs become unreliable, trigger the same workflow externally with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dispatch_news_radar.ps1 -GithubToken YOUR_GITHUB_PAT
```

The token needs `repo` access for the target repository and triggers the `repository_dispatch` event type `news-radar`.

## Digest run

```bash
python -m all3_radar.app.digest_cli build --week 2026-W17
```
