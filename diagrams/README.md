# Sinatra diagrams

These drawings document the live interceptor and the proof-script checks. They do not change runtime behavior.

Labels avoid slashes and parentheses. Mermaid treats a slash inside a node as a shape delimiter, which is why the previous copies failed to render.

## Files

| File | Drawing |
| --- | --- |
| [overview.mmd](overview.mmd) | One intercept cycle |
| [architecture.mmd](architecture.mmd) | Live-script components |
| [data-flow.mmd](data-flow.mmd) | One object, from catalog JSON to DebrisMetrics |
| [deployment.mmd](deployment.mmd) | Container image and Kubernetes manifests |
| [proof-claims.mmd](proof-claims.mmd) | What the proof script checks |

## Cycle

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

## Components

```mermaid
graph LR
  weather[LiveSpaceWeather]
  target[LiveOrbitalTarget]
  env[Mission environment]
  detector[Raw classical detector]
  imm[IMM proxy]
  pf[Particle filter]
  engine[Blind multi-scale engine]
  metrics[DebrisMetrics]

  weather --> target
  target --> env
  env --> detector
  detector --> imm
  detector --> pf
  target --> engine
  engine --> metrics
```

## Deployment

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
