FROM python:3.13-slim

WORKDIR /app

# Install dependencies first (cache-friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY main.py .

# Runtime directory for checkpoints / thread registry
RUN mkdir -p /app/.runtime

ENV RUNTIME_ROOT=/app/.runtime
EXPOSE 8008

CMD ["uvicorn", "src.api.chat_app:app", "--host", "0.0.0.0", "--port", "8008"]
