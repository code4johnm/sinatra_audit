# Configuration

## Contents

- [Environment](#environment)
- [CLI](#cli)

## Environment

`SINTRA_HUD_PORT` defaults to 8080. `SINTRA_HUD=0` skips the page. The image sets `MPLBACKEND=Agg`.

## CLI

```bash
./run-live.sh
```

That script is the headless and the dashboard entry. It publishes the HUD on port 8080.
