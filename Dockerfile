FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -hide_banner -h filter=drawtext > /dev/null

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY clipforge/ clipforge/
COPY scripts/ scripts/
COPY tests/ tests/

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "unittest", "discover", "-s", "tests"]
