FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${FLASK_PORT:-8000} --workers ${GUNICORN_WORKERS:-2} app:app"]
