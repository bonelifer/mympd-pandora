FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pydora==2.3.1

WORKDIR /app
COPY stream.py station_management.py .
USER 65534:65534
ENV PYDORA_CFG=/config/pydora.cfg
EXPOSE 8080
ENTRYPOINT ["python", "-u", "stream.py"]
CMD ["--listen", "0.0.0.0"]
