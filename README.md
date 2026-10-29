# Sinatra

Private copy of the SINTRA live interceptor, packaged as a local container. The process does not listen on a port. It loops the sky-catalog script and writes a HUD image.

Remote: `git@github.com:code4johnm/sinatra.git` (private).

## How to run

Build the image from this directory:

```bash
docker build -t sinatra-sandbox:local .
```

Run it:

```bash
docker run --rm --name sinatra-live \
  --user 10001:10001 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 128 --memory 4g --memory-swap 4g --cpus 2 \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=512m \
  -v "$PWD/output:/output" \
  -e MPLBACKEND=Agg -e MPLCONFIGDIR=/tmp/mpl -e HOME=/tmp \
  -w /output sinatra-sandbox:local
```

Create `output/` first. The container writes `sintra_live_norad_intercept_hud.png` there.

Kubernetes manifests are in `k8s/`. They expect the image name `sinatra-sandbox:local` on the same machine (`imagePullPolicy: Never`).

```bash
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
```

There is no cluster on this laptop yet. `kubectl apply` does nothing until kubelet is installed.

## Expected output

Each pass prints a cycle line, a catalog of seven objects, and a save line for the HUD PNG. The script then starts the next cycle. The PNG is overwritten each pass.

Live feeds often fall back. NOAA's solar-wind URL can 404, and the script then prints its built-in field values while still saying the stream is live. CelesTrak has a 2.5 second timeout, and a miss uses the built-in Keplerian elements. With no local `cosmic_data` files, the background is the synthetic Chapman curve.

## Architecture

`launch.py` forces the Matplotlib Agg backend and returns immediately from `show()`, so the loop is not blocked by a window. The container command runs `sintra_live_sky_catalog_interceptor.py`. That script's `__main__` calls `run_live_sky_interceptor()` forever and closes figures between cycles.

The image is `python:3.12-slim-bookworm` plus numpy, scipy, sympy, matplotlib, requests, and netCDF4. The user inside the image is uid 10001.

`k8s/deployment.yaml` runs one replica as that uid, with a read-only root filesystem, every capability dropped, and emptyDir volumes on `/tmp` and `/output`. `k8s/service.yaml` is headless. Port 9 is discard and is not served.

## Diagrams

The drawings live in [diagrams/](diagrams/README.md). Each `.mmd` file is the source. GitHub renders the copies below.

```mermaid
flowchart TD
  noaa["NOAA SWPC mag and plasma JSON"]
  cele["CelesTrak NORAD GP JSON"]
  cosmic["Local cosmic_data or synthetic Chapman curve"]
  sw["LiveSpaceWeather"]
  swfb["Built-in IMF values"]
  prop["propagate_omm_to_leo_state"]
  kep["Built-in Keplerian elements"]
  tgt["LiveOrbitalTarget"]
  env["COSMIC_TEC_Mission_Environment"]
  inject["Altitude and B-field soliton wake"]
  clutter["Sub-zero SNR clutter"]
  engine["SINTRA_BlindMultiScale_Engine"]
  stack["Coherent moving-frame stack"]
  sigma["sigma_star estimate"]
  jko["JKO sigma relaxation"]
  debris["estimate_debris_profile to DebrisMetrics"]
  hud["sintra_live_norad_intercept_hud.png"]

  noaa --> sw
  noaa -.-> swfb
  swfb --> sw
  cele --> prop
  cele -.-> kep
  kep --> prop
  sw --> prop
  prop --> tgt
  cosmic --> env
  tgt --> inject
  env --> inject
  inject --> clutter
  clutter --> engine
  engine --> stack
  stack --> sigma
  sigma --> jko
  jko --> debris
  debris --> hud
```

```mermaid
flowchart TD
  docker["Dockerfile"]
  image["Image sinatra-sandbox:local"]
  user["User 10001, read-only root, no published ports"]
  launch["launch.py sets Agg and skips show"]
  script["sintra_live_sky_catalog_interceptor.py"]
  loop["Continuous cycle loop"]
  png["HUD PNG on /output"]
  dep["k8s/deployment.yaml"]
  svc["k8s/service.yaml headless, port 9 unused"]
  host["No cluster on this laptop"]

  docker --> image
  image --> user
  user --> launch
  launch --> script
  script --> loop
  loop --> png
  dep --> image
  svc --> dep
  host --> dep
```

## Network

The container does not listen. It uses outbound HTTP on port 80 and HTTPS on port 443 for the public data feeds. If those requests fail, the script uses its built-in values and still writes the HUD image. Git traffic for this repo is SSH on port 22. The host port list is `~/.local/share/network-baseline.md`.

## Operational notes

Stop a local container with `docker stop sinatra-live`. An exited container still holds that name until it is removed.

The repo stays private. Do not force-push. Do not add secrets or `.mil` material.

The HUD and the three checked-in PNG files are pictures of the script's output, not a service endpoint.
