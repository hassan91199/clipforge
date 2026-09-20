FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -hide_banner -h filter=drawtext > /dev/null

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY clipforge/ clipforge/
COPY scripts/ scripts/
COPY tests/ tests/
COPY pyproject.toml pyproject.toml
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["test"]
