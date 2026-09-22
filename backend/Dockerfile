FROM python:3.11-slim

# Install system dependencies including ripgrep and git
RUN apt-get update && apt-get install -y \
    ripgrep \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for FastAPI
EXPOSE 8000

# Default command (can be overridden by docker-compose or render config)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
