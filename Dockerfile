FROM python:3.14-slim

LABEL org.opencontainers.image.title="cleanupdockerhub" \
      org.opencontainers.image.description="Removes old Docker Hub image tags based on configurable retention policies" \
      org.opencontainers.image.source="https://github.com/your-username/cleanupdockerhub"

RUN apk add --no-cache bash wget \
    && wget -qO- 'https://artifacts-cli.infisical.com/setup.apk.sh' | sh \
    && apk add --no-cache infisical

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cleanupdockerhub.py .

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

CMD ["infisical", "run", "--projectId=TestProject", "--env=dev", "--", "python", "cleanupdockerhub.py"]
