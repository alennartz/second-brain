# Production deployment

The server runs as a systemd service that owns a Docker container built from
a pinned release image. Machine-specific values never enter git.

## Files

| File | Tracked | Purpose |
|---|---|---|
| `second-brain.service.in` | yes | Unit template with `{{NAME}}`, `{{IMAGE}}`, `{{PORT}}`, `{{ENV_FILE}}`, `{{DATA_DIR}}` placeholders |
| `deploy.env.example` | yes | Documented variables; copy to `deploy.env` and fill in |
| `deploy.env` | **no** | Actual machine values (image tag, port, paths). Gitignored |
| `install.sh` | yes | Renders the template, installs the unit, starts the service |

## Setup

1. Copy and fill in the machine config:

   ```bash
   cp deploy/deploy.env.example deploy/deploy.env
   ```

   Set `BRAIN_IMAGE` to a fully qualified reference with a pinned tag —
   the installer refuses `:latest`. Point `BRAIN_DEPLOY_ENV_FILE` at your
   app `.env` (API keys, `BRAIN_*` settings; gitignored) and
   `BRAIN_DEPLOY_DATA_DIR` at a persistent data directory.

2. Install and start:

   ```bash
   make deploy
   ```

## Operations

```bash
make deploy          # install or update (pulls the pinned image, restarts)
make deploy-status   # systemd status
make deploy-logs     # follow journalctl
make deploy-undeploy # stop, disable, remove the unit
```

## Upgrades

Set the new pinned tag in `deploy/deploy.env`, then run `make deploy`.
Rollback: set the previous tag and run `make deploy` again.

## Releasing an image

Build and push a tagged image from the repo root:

```bash
docker build -t ghcr.io/your-org/second-brain:v0.2.0 .
docker push ghcr.io/your-org/second-brain:v0.2.0
```
