# Backend Dockerfile — for Render deployment
# Using Docker gives more control than Render's native Python buildpack

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./

# Copy dataset into the image
COPY sap-o2c-data/ ./sap-o2c-data/

# Build the SQLite database at build time (not runtime)
# This makes startup instant instead of waiting for ingestion
RUN python db.py --data-dir ./sap-o2c-data --db-path ./data/o2c.db

# Expose port (Render sets $PORT automatically)
EXPOSE 8000

# Start FastAPI
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
