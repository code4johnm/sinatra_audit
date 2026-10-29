# Sinatra diagrams

These files document the live interceptor. They do not change its behavior. The catalog entry points here. This directory holds the architecture drawings.

## 1. Role

The diagrams show how the private Sinatra container fetches public feeds, runs one intercept cycle, and writes a HUD image.

## 2. Project

- Name: Sinatra live interceptor
- Purpose: Loop `sintra_live_sky_catalog_interceptor.py` in a headless container.
- Tech stack: Python 3.12, Docker, Kubernetes manifests. No cluster is installed on this laptop.

## 3. Compliance

None stated in the repo.

## 4. Scope of work

One cycle fetches NOAA space weather and a CelesTrak catalog, builds a COSMIC-1 or synthetic background, runs the blind multi-scale engine, and saves `sintra_live_norad_intercept_hud.png`. Failed feeds use the built-in values.

## 5. Documentation and deliverables

| File | Drawing |
| --- | --- |
| [overview.mmd](overview.mmd) | End-to-end flow |
| [architecture.mmd](architecture.mmd) | Classes in the live script |
| [data-flow.mmd](data-flow.mmd) | One object, from OMM JSON to DebrisMetrics |
| [deployment.mmd](deployment.mmd) | Image, `launch.py`, and the Kubernetes manifests |

## 6. Architecture

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
classDiagram
  class LiveSpaceWeather {
    +source_status
    +bx_nt
    +by_nt
    +bz_nt
  }
  class LiveOrbitalTarget {
    +norad_id
    +altitude_km
    +true_wake_sigma_m
    +ephemeris_source
  }
  class COSMIC_TEC_Mission_Environment {
    +load_or_synthesize()
    +observe()
  }
  class RawClassicalDetector {
    +get_raw_measurement()
  }
  class IMMProxyTracker {
    +step()
  }
  class ParticleFilterTracker {
    +step()
  }
  class SINTRA_BlindMultiScale_Engine {
    +initialize()
    +_ricker_lsb_at_scale()
    +_detrend_local_linear()
    +_blind_scale_estimator()
    +step()
  }
  class DebrisMetrics {
    +sigma_star
    +lambda_potential
    +mass_profile_proxy
    +inferred_class
  }

  LiveSpaceWeather --> LiveOrbitalTarget : fetch_live_norad_catalog
  LiveOrbitalTarget --> COSMIC_TEC_Mission_Environment : run_live_sky_interceptor
  COSMIC_TEC_Mission_Environment --> RawClassicalDetector : observe
  RawClassicalDetector --> IMMProxyTracker : raw gate
  RawClassicalDetector --> ParticleFilterTracker : raw gate
  LiveOrbitalTarget --> SINTRA_BlindMultiScale_Engine : wake injection
  SINTRA_BlindMultiScale_Engine --> DebrisMetrics : estimate_debris_profile
```

```mermaid
flowchart TD
  omm["OMM JSON or built-in Keplerians"]
  leo["propagate_omm_to_leo_state"]
  wake["Wake width from altitude, inclination, and B-field"]
  obs["COSMIC_TEC_Mission_Environment.observe"]
  snr["Sub-zero SNR clutter on the sensor grid"]
  ricker["Ricker LSB precondition"]
  trend["Local linear detrend"]
  stack["Moving-frame waveform stack"]
  match["Multi-scale matched projection"]
  sigma["sigma_star"]
  jko["JKO update of current_jko_sigma"]
  metrics["DebrisMetrics"]

  omm --> leo
  leo --> wake
  wake --> obs
  obs --> snr
  snr --> ricker
  ricker --> trend
  trend --> stack
  stack --> match
  match --> sigma
  sigma --> jko
  jko --> metrics
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
