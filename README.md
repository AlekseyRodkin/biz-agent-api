# Biz Agent API

FastAPI backend service for business automation.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check

## Деплой

См. [DEPLOY.md](DEPLOY.md)
