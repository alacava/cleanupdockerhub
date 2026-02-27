FROM python:3.14-slim

LABEL org.opencontainers.image.title="cleanupdockerhub" \
      org.opencontainers.image.description="Removes old Docker Hub image tags based on configurable retention policies" \
      org.opencontainers.image.source="https://github.com/your-username/cleanupdockerhub"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cleanupdockerhub.py .

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

CMD ["python", "cleanupdockerhub.py"]
