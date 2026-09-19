FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY prompts ./prompts
COPY config ./config
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8000
CMD ["uvicorn", "nurture.main:app", "--host", "0.0.0.0", "--port", "8000"]
