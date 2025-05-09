FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Poetry
RUN pip install poetry==1.8.3 --no-cache-dir
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# 依赖安装（先复制 lock 文件利用 layer 缓存）
COPY pyproject.toml poetry.lock* ./
RUN poetry install --without cv --no-root && rm -rf $POETRY_CACHE_DIR

# 复制源码
COPY src/ ./src/
COPY data/ ./data/
RUN poetry install --without cv

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["poetry", "run", "uvicorn", "rhythmind.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
