FROM python:3.12-slim

LABEL org.opencontainers.image.title="cleanupdockerhub" \
      org.opencontainers.image.description="Removes old Docker Hub image tags based on configurable retention policies" \
      org.opencontainers.image.source="https://github.com/your-username/cleanupdockerhub"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cleanupdockerhub.py .

CMD ["python", "cleanupdockerhub.py"]
