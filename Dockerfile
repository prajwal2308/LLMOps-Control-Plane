# Stage 3: Containerize the LLMOps Control Plane with Docker + uv
FROM python:3.12-slim

# Copy the fast uv binary directly from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Prevent Python from writing .pyc files & compile bytecode via uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# Copy dependency definition files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync (uses lockfile for deterministic build)
RUN uv sync --frozen --no-install-project --no-cache

# Copy application source code
COPY . .

# Expose FastAPI application port
EXPOSE 8000

# Run Uvicorn server bound to 0.0.0.0 for external container access
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
