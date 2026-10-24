# Sanctio: API + dashboard website in one image.
# 1) build the React website
FROM node:20-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) the API, which also serves the built website (app/main.py looks for ../frontend/dist)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8000
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /src/frontend/dist /srv/frontend/dist
RUN useradd --create-home sanctio
USER sanctio
EXPOSE 8000
# seed the demo business on first start only (no-op when the DEMO_* settings are absent)
CMD python -m scripts.seed_demo --if-missing; \
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"
