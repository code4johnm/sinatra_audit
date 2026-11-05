# Supply chain

## Contents

- [Image pins](#image-pins)
- [Feeds](#feeds)

## Image pins

Dockerfile installs numpy==2.2.6, scipy==1.15.3, sympy==1.14.0, matplotlib==3.10.3, requests==2.32.4, netCDF4==1.7.2. `requirements.txt` lists different pins and is not what the image installs. Base image `python:3.12-slim-bookworm` has no digest pin. Transitive wheels are not hashed.

## Feeds

NOAA solar-wind and CelesTrak are called by the existing interceptor. A miss uses built-in elements. No language-model API is added.
