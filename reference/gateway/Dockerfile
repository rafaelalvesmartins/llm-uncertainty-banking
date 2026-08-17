FROM python:3.12-slim

WORKDIR /app

# Install lub + gateway deps
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir fastapi uvicorn[standard] psycopg2-binary prometheus-client

COPY reference/gateway/app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
