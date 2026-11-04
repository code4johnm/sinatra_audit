# sinatra

## 1. Role

John M. Cook maintains this repository. It is the local container for the SINTRA live sky-catalog interceptor. GitHub serves it as `git@github.com:code4johnm/sinatra_audit.git`. The old `sinatra` name redirects there.

## 2. Project

- Name: sinatra
- Purpose: Loop a sky-catalog pass, print a terminal HUD, write a HUD image, and serve the same cycle on a web page.
- Tech stack: Python 3.12, numpy, scipy, sympy, matplotlib, requests, and netCDF4. The image base is `python:3.12-slim-bookworm`.

## 3. Compliance

None stated in the repo.

## 4. Scope of work

Build `sinatra-sandbox:local`, run one container, and read the HUD. The web page is unauthenticated and binds port 8080. Kubernetes manifests exist for the same image. The container is not the bus listener.

## 5. Documentation and deliverables

- `README.md`
- `diagrams/`
- `Dockerfile`, `Dockerfile.job`, `entrypoint.sh`, `launch.py`, `run-live.sh`
- `k8s/deployment.yaml`, `k8s/deployment-laptop.yaml`, and `k8s/service.yaml`
- The interceptor and HUD Python files at the repo root

`output/` is run output. Do not commit generated HUD images from a live loop.

## 6. Architecture

`launch.py` selects the Matplotlib Agg backend. The container command runs `sintra_live_sky_catalog_interceptor.py`, which loops forever. The same process serves `sintra_web_hud.py` on port 8080. The image user is uid 10001. The root filesystem is read-only and capabilities are dropped. `k8s/deployment.yaml` bind-mounts this checkout at `/opt/sinatra` and is held at 0 replicas. The laptop Deployment does the same mount and writes `/output` on the host. Working directory is `/output`. The bus listener is Deployment `yaml-listen`, not this pod. See `DEPLOY.md`.

## 7. Build procedures

```bash
docker build -t sinatra-sandbox:local .
```

`imagePullPolicy: Never` means the image has to be present on this machine before a pod can start.

## 8. Run instructions

```bash
./run-live.sh
```

A successful pass prints a cycle line, a catalog of seven objects, and a save line. The PNG is `output/sintra_live_norad_intercept_hud.png`. The Service publishes the page at `http://127.0.0.1:8080/` on this laptop. Set `SINTRA_HUD=0` to skip the page.

The output directory must be writable by the process uid. A fuse filesystem that ignores `chmod` fails `savefig` for uid 10001.

## 9. Configuration

`SINTRA_HUD_PORT` defaults to 8080. `MPLBACKEND=Agg` and `MPLCONFIGDIR` are set by `run-live.sh`. No API tokens are stored in this repo. Live NOAA and CelesTrak requests fall back to built-in values when those sites do not answer.

## 10. Testing

No test command found. `./run-live.sh` is the manual check. Confirm the PNG appears under `output/` and port 8080 answers.
