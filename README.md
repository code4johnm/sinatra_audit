# Sinatra

Separate copy of the SINTRA live interceptor, packaged as a local container. The process does not listen on a port. It loops the sky-catalog script and writes a HUD image.

Remote: `git@github.com:code4johnm/sinatra_audit.git`.

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

## Expected output

Each pass prints a cycle line, a catalog of seven objects, and a save line for the HUD PNG. The script then starts the next cycle. The PNG is overwritten each pass.

Live feeds often fall back. NOAA's solar-wind URL can 404, and the script then prints its built-in field values while still saying the stream is live. CelesTrak has a 2.5 second timeout, and a miss uses the built-in Keplerian elements. With no local `cosmic_data` files, the background is the synthetic Chapman curve.

## Architecture

`launch.py` forces the Matplotlib Agg backend and returns immediately from `show()`, so the loop is not blocked by a window. The container command runs `sintra_live_sky_catalog_interceptor.py`. That script's `__main__` calls `run_live_sky_interceptor()` forever and closes figures between cycles.

The image is `python:3.12-slim-bookworm` plus numpy, scipy, sympy, matplotlib, requests, and netCDF4. The user inside the image is uid 10001.

`k8s/deployment.yaml` runs one replica as that uid, with a read-only root filesystem, every capability dropped, and emptyDir volumes on `/tmp` and `/output`. `k8s/service.yaml` is headless. Port 9 is discard and is not served.

## Diagrams

Sources are in [diagrams/](diagrams/README.md). The copies below use `graph` and labels without slashes or parentheses, which is what GitHub Mermaid actually renders. A slash inside a node label is parsed as a shape, so those diagrams were failing.

```mermaid
graph TD
  noaa[NOAA space-weather JSON]
  cele[CelesTrak NORAD catalog]
  cosmic[Local cosmic_data or synthetic Chapman curve]
  sw[LiveSpaceWeather]
  fallback[Built-in IMF values]
  prop[Propagate OMM to a LEO state]
  kep[Built-in Keplerian elements]
  tgt[LiveOrbitalTarget]
  env[Mission environment]
  inject[Altitude and B-field wake]
  clutter[Injected clutter on a long grid]
  engine[Blind multi-scale engine]
  stack[Moving-frame stack]
  sigma[Width estimate]
  jko[Width relaxation]
  debris[DebrisMetrics]
  hud[HUD PNG]

  noaa --> sw
  noaa -.-> fallback
  fallback --> sw
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
graph TD
  docker[Dockerfile]
  image[Image sinatra-sandbox local]
  user[User 10001 read-only root]
  launch[launch.py sets Agg and skips show]
  script[Sky-catalog interceptor]
  loop[Continuous cycle]
  png[HUD PNG on the output volume]
  dep[Kubernetes Deployment]
  svc[Headless Service unused port 9]
  jobfile[Dockerfile.job]
  jobimg[Image sinatra latest]
  job[Kubernetes Job one shot]
  outvol[PNG on the out volume]

  docker --> image
  image --> user
  user --> launch
  launch --> script
  script --> loop
  loop --> png
  dep --> image
  svc --> dep
  jobfile --> jobimg
  jobimg --> job
  job --> outvol
```

```mermaid
graph TD
  code[Proof script]
  id1[Cold-fluid forced KdV]
  id2[Gardner flow of stated H]
  id3[Chart convexity of E]
  id4[Gain-tensor spectrum]
  id5[Ricker moments 0 and 1]
  id6[Scalar left inverse]
  sim[Monte Carlo report]
  audit[Math proof audit]

  code --> id1
  code --> id2
  code --> id3
  code --> id4
  code --> id5
  code --> id6
  code --> sim
  id1 --> audit
  sim --> audit
```

The proof script checks identities. It does not prove sub-zero-SNR custody. See [sinatra_math_proof_audit.md](sinatra_math_proof_audit.md).

## Network

The container does not listen. It uses outbound HTTP on port 80 and HTTPS on port 443 for the public data feeds. If those requests fail, the script uses its built-in values and still writes the HUD image. Git traffic for this repo is SSH on port 22. The host port list is `~/.local/share/network-baseline.md`.

## Operational notes

Stop a local container with `docker stop sinatra-live`. An exited container still holds that name until it is removed.

Do not force-push. Do not add secrets or `.mil` material.

The HUD and the three checked-in PNG files are pictures of the script's output, not a service endpoint.

## Batch Job (one run, then exit)

`Dockerfile.job` builds a second image that runs one script once, headless (`MPLBACKEND=Agg`), as uid 10001, and writes its PNG to `/out`.
The default is `sintra_live_mission_demo.py`. It finishes on its own in about 30 seconds and needs no network: without `netCDF4` it uses the synthetic Chapman background.
To pick another script, set `SINTRA_SCRIPT=<file.py>` or pass the file name as the first argument. Those scripts need `sympy`, which this image leaves out, and the interceptor loops forever.

```bash
docker build -f Dockerfile.job -t sinatra:latest .
docker run --rm -v "$PWD/out:/out" sinatra:latest
```

Load the image into a local cluster. The Job uses `imagePullPolicy: IfNotPresent`, so no registry is involved.

```bash
kind load docker-image sinatra:latest     # kind
minikube image load sinatra:latest        # minikube
```

Run it and read the logs:

```bash
kubectl apply -f k8s/job.yaml
kubectl wait --for=condition=complete job/sinatra --timeout=10m
kubectl logs job/sinatra
```

`/out` is an `emptyDir`, so the PNG is deleted along with the pod, and `ttlSecondsAfterFinished: 3600` removes the Job an hour after it finishes.
