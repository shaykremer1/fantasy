FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY app /app/app
COPY web /app/web
RUN useradd --create-home --uid 10001 fantasy && mkdir -p /app/.data && chown -R fantasy:fantasy /app
USER fantasy
EXPOSE 8000
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--public-read-only"]
