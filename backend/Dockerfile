FROM python:3.12-slim

WORKDIR /app

# Install deps first (better layer caching)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy agent/ alongside (ai_agent imports from ../agent relative to project root)
COPY agent/ /app/agent/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
