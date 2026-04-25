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

## Digest run

```bash
python -m all3_radar.app.digest_cli build --week 2026-W17
```
