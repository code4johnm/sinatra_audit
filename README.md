# SINTRA

Python simulations and HUD renders.

## Running in a container / on Kubernetes

The image runs one script headless (`MPLBACKEND=Agg`) as a non-root user and writes its PNG output to `/out`.
The default script is `sintra_live_mission_demo.py`. It finishes on its own (about 30 s) and needs no network.
Without `netCDF4` installed it uses its built-in synthetic Chapman background.

Build:

```sh
docker build -t sinatra:latest .
docker run --rm -v "$PWD/out:/out" sinatra:latest            # default script
docker run --rm -e SINTRA_SCRIPT=sintra_cia_redacted_demo.py sinatra:latest   # override
```

Load the local image into your cluster (the Job uses `imagePullPolicy: IfNotPresent`, so no registry is involved):

```sh
kind load docker-image sinatra:latest        # kind
minikube image load sinatra:latest           # minikube
```

Run it and read the output:

```sh
kubectl apply -f k8s/job.yaml
kubectl wait --for=condition=complete job/sinatra --timeout=10m
kubectl logs job/sinatra
kubectl delete job sinatra                   # or let ttlSecondsAfterFinished clean it up
```

`/out` is an `emptyDir`, so the PNG goes away with the pod. To keep it, swap in a PVC, or `kubectl cp` it out before the pod finishes.
The other scripts need `sympy` or live network, or loop forever (`sintra_live_sky_catalog_interceptor.py`), so they are not supported in the image as is.
