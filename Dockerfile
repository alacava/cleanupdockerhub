FROM python:3.14-slim

LABEL org.opencontainers.image.title="cleanupdockerhub" \
      org.opencontainers.image.description="Removes old Docker Hub image tags based on configurable retention policies" \
      org.opencontainers.image.source="https://github.com/your-username/cleanupdockerhub"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
    && apt-get install -y --no-install-recommends infisical \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cleanupdockerhub.py .

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

CMD ["infisical", "run", "--projectId=2e353ca0-4aa4-4b9d-a703-9185529fba7f", "--env=dev", "--", "python", "cleanupdockerhub.py"]
