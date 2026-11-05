# Security requirements

## Contents

- [NIST SP 800-53](#nist-sp-800-53)
- [CISA SSDF](#cisa-ssdf)

## NIST SP 800-53

| Family | Present | Gap |
| --- | --- | --- |
| AC | Container uid 10001, no service account token, capabilities dropped. | HUD has no login. |
| AU | Cycle lines go to the terminal and the page. | No remote audit store. |
| CM | Dependency pins are in the Dockerfile. | `requirements.txt` pins differ from the image. The tag is not digest-pinned. |
| IA | None on the HUD. | |
| SA | Image is built locally and not pulled. | NOAA and CelesTrak are runtime feeds. |
| SC | Read-only root, no-new-privileges in `run-live.sh`. | hostPort 8080, no TLS. |
| SI | Fallback values exist when a feed misses. | Fallback data is not signed telemetry. |

## CISA SSDF

Requirements are the existing sandbox flags. Verification is a local image build and a cycle that writes the PNG. Response is to scale to 0 and keep the output directory. This is not an ATO.
