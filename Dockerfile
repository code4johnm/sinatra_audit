FROM python:3.12-slim

ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    SINTRA_SCRIPT=sintra_live_mission_demo.py

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py entrypoint.sh ./
RUN useradd --create-home --uid 10001 sintra \
    && mkdir -p /out && chown sintra:sintra /out \
    && chmod +x /app/entrypoint.sh

USER 10001
VOLUME ["/out"]
ENTRYPOINT ["/app/entrypoint.sh"]
