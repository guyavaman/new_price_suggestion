# One container: builds the Angular app, then serves it and the API with uvicorn.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SEED_DEMO=1 \
    FRONTEND_DIST=/app/frontend/dist/crm/browser
WORKDIR /app
COPY backend/requirements-web.txt backend/
RUN pip install --no-cache-dir -r backend/requirements-web.txt
COPY backend/ backend/
COPY data/ data/
COPY --from=web /web/dist/crm/browser /app/frontend/dist/crm/browser
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
