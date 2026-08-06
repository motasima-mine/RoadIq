FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# ACTIVE server is server.py (Flask) — app.py (Streamlit) is legacy/backup,
# not run in this image. server.py reads PORT from env (default 5002) and
# binds 0.0.0.0, which is what App Runner / most container platforms expect.
EXPOSE 5002

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5002/ || exit 1

ENTRYPOINT ["python", "server.py"]
