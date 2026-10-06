FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY src ./src
COPY settings.toml ./
ENV PORT=8000
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "semcache.app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
