# Container image for production deployment. Runs the app with gunicorn,
# not the Flask dev server (python3 app.py) -- that server is single-
# threaded and explicitly documented by Flask as unsafe for real traffic.
#
# Build:  docker build -t ieltsband .
# Run:    docker run -p 8080:8080 --env-file .env.production ieltsband

FROM python:3.12-slim

WORKDIR /app

COPY requirements-prd.txt .
RUN pip install --no-cache-dir -r requirements-prd.txt

COPY . .

ENV FLASK_DEBUG=0
EXPOSE 10000
# 1 worker, 4 threads: fits Render's free-tier 0.1 CPU/512MB comfortably.
# Raise --workers if you move to a paid tier with more CPU. --timeout is
# generous for the first (uncached) render of a PDF page.
CMD exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120 app:app
