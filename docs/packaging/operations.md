# Operations

## Contents

- [Commands](#commands)
- [Pod](#pod)
- [Incidents](#incidents)

## Commands

```bash
cd /mnt/5TB/git/github/sinatra
docker build -t sinatra-sandbox:local .
./run-live.sh
```

The image name must stay `sinatra-sandbox:local` with `imagePullPolicy: Never`.

## Pod

Manifests already exist. They are not applied by this packaging.

```bash
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
```

The Service is ClusterIP and the pod uses hostPort 8080. The page is unauthenticated.

## Incidents

Scale the deployment to 0 or stop the container. The PNG in `output/` is the last cycle. Start `./run-live.sh` to resume. NOAA and CelesTrak misses already fall back inside the script.
