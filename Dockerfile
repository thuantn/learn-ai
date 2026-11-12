FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY app app
COPY web web
COPY skills skills
COPY scripts/learnpkg.py scripts/learnpkg.py
COPY docs/lesson-format.md docs/lesson-format.md
COPY docs/practice-test-format.md docs/practice-test-format.md
USER 10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--no-proxy-headers", "--no-access-log"]
