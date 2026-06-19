FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir -r /app/requirements.txt \
  && pip install --no-cache-dir /app

EXPOSE 8080

CMD ["uvicorn", "facturia_matching.main:app", "--host", "0.0.0.0", "--port", "8080"]
