# Threat model

## Contents

- [Boundaries](#boundaries)
- [Abuse](#abuse)

## Boundaries

Operator, container uid 10001, outbound NOAA and CelesTrak, and the HUD listener. The root filesystem is read-only and capabilities are dropped. The output mount is the writable boundary.

## Abuse

Anyone who can open port 8080 sees the HUD. There is no login. A hostile response from a feed is handled by the existing timeout and fallback, not by a new parser. The laptop hostPort makes the page reachable on the host network.
