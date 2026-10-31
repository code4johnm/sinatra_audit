FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp \
    SINTRA_HUD_PORT=8080

RUN pip install \
    numpy==2.2.6 \
    scipy==1.15.3 \
    sympy==1.14.0 \
    matplotlib==3.10.3 \
    requests==2.32.4 \
    netCDF4==1.7.2 \
    && groupadd --gid 10001 sinatra \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin sinatra \
    && mkdir -p /opt/sinatra /opt/sandbox /output /tmp/mpl \
    && chown -R sinatra:sinatra /opt/sinatra /opt/sandbox /output /tmp

COPY launch.py /opt/sandbox/launch.py
COPY sintra_cia_redacted_demo.py \
     sintra_definitive_math_proof.py \
     sintra_live_mission_demo.py \
     sintra_live_sky_catalog_interceptor.py \
     sintra_web_hud.py \
     /opt/sinatra/

EXPOSE 8080

USER sinatra
WORKDIR /output

CMD ["python", "/opt/sandbox/launch.py", "/opt/sinatra/sintra_live_sky_catalog_interceptor.py"]
