# Temporary GitLab state seed

This folder is a temporary bridge while the production runtime is moving from GitHub Actions to the working server.

- `radar-state-snapshot-26436397276.zip` contains the latest known-good `all3_radar.db` before the GitLab Package Registry state bridge was added.
- GitLab CI uses it only when the durable `radar-state` package has not been bootstrapped yet.
- Remove this folder after `all3_radar.db` is moved to persistent server storage.

This is not the long-term state architecture.
