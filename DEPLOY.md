# Deploy

The `sinatra` Deployment runs the SINTRA live interceptor from this repository. It does not run the bus listener.

## What the pod runs

| | |
| --- | --- |
| Workload | Deployment `sinatra`, namespace `default`, container `sinatra` |
| Code | `/mnt/5TB/git/sinatra_audit` mounted read-only at `/opt/sinatra` |
| Image | `sinatra-sandbox:local` (`imagePullPolicy: Never`) |
| Command | `python /opt/sinatra/launch.py /opt/sinatra/sintra_live_sky_catalog_interceptor.py` |
| Workdir | `/output` |
| User | uid/gid/fsGroup `10001`, non-root, no service-account token |
| Port | container port `8080` named `hud`, `hostPort: 8080` |
| Service | `sinatra` ClusterIP port `8080` to target port `hud` |
| Probe | HTTP GET `/api/health` on `hud` |

`launch.py` forces the Matplotlib Agg backend, starts `sintra_web_hud.py` on `SINTRA_HUD_PORT` (8080), then runs `sintra_live_sky_catalog_interceptor.py`. That script loops. The page is unauthenticated. With a replica running it is `http://127.0.0.1:8080/` on this laptop because of the hostPort.

The image is `python:3.12-slim-bookworm` plus numpy, scipy, sympy, matplotlib, requests, and netCDF4. It supplies the interpreter and those libraries. The pod command does not use the copies baked under the image's `/opt/sinatra` or `/opt/sandbox`. The hostPath mount hides the image copies. `PYTHONDONTWRITEBYTECODE=1` is set because that mount is read-only.

Mounts:

- `source`: hostPath `/mnt/5TB/git/sinatra_audit` (`Directory`) at `/opt/sinatra`, read-only
- `tmp`: emptyDir, medium Memory, 512Mi, at `/tmp` (`HOME` and `MPLCONFIGDIR`)
- `output`: emptyDir, 1Gi, at `/output` (HUD PNG)

Security on the container: read-only root filesystem, `allowPrivilegeEscalation: false`, all capabilities dropped, seccomp `RuntimeDefault`. Limits: 2 CPU, 4Gi memory. Requests: 100m CPU, 512Mi memory.

The manifest sets `replicas: 0`. Applying it does not start the interceptor. The loop calls NOAA and CelesTrak. Start it only when that is intended:

```bash
kubectl -n default scale deployment/sinatra --replicas=1
```

`k8s/deployment-laptop.yaml` is the older uid-1000 binding that writes the PNG to a host directory. It also mounts this checkout (`/mnt/5TB/git/sinatra_audit`), not `/mnt/5TB/git/sinatra`. The cluster object is `k8s/deployment.yaml`, not the laptop file.

## Apply

From this repo, against the local k3s context `default`:

```bash
kubectl diff -f /mnt/5TB/git/sinatra_audit/k8s/deployment.yaml -f /mnt/5TB/git/sinatra_audit/k8s/service.yaml
kubectl apply -f /mnt/5TB/git/sinatra_audit/k8s/deployment.yaml -f /mnt/5TB/git/sinatra_audit/k8s/service.yaml
```

That apply does not change Deployment `yaml-listen`.

The image must already be in the k3s containerd store as `docker.io/library/sinatra-sandbox:local`. Rebuild and import only when the Dockerfile or pinned Python packages change:

```bash
docker build -t sinatra-sandbox:local /mnt/5TB/git/sinatra_audit
docker save sinatra-sandbox:local | /home/user/bin/agent-sudo.sh /usr/local/bin/k3s ctr images import -
```

## Bus listener

The listener is not part of this pod and not part of this apply.

| | |
| --- | --- |
| Workload | Deployment `yaml-listen`, namespace `default` |
| Repo | `/mnt/5TB/git/bus-listener` |
| Manifest | `/mnt/5TB/git/bus-listener/k8s/deployment.yaml` |
| Image | `bus-listener:active` |
| Process | image entrypoint `/usr/local/bin/entrypoint.sh`, which execs `python3 /usr/local/bin/bus_listener.py` |
| Service | none. It polls; it does not serve HTTP |
| Replicas | left at 0 until a human starts it. Do not delete the Deployment |

Do not put the listener container, its docker socket, or its rclone secret into the `sinatra` pod.
