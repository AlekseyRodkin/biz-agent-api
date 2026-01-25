# Biz Agent API - Правила для Claude

## Проект

FastAPI бэкенд для бизнес-автоматизации.

## Стек

- Python 3.11+
- FastAPI
- Uvicorn

## Структура

```
biz-agent-api/
├── app/
│   ├── __init__.py
│   └── main.py
├── requirements.txt
├── README.md
├── CLAUDE.md
└── DEPLOY.md
```

## Деплой на VPS

**Директория:** `/opt/biz-agent-api-git/biz-agent-api`

**PM2 процесс:** `biz-agent-api`

**Порт:** 8000

### Команды деплоя

```bash
cd /opt/biz-agent-api-git/biz-agent-api
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
pm2 restart biz-agent-api
curl -s http://127.0.0.1:8000/health
```

## Правила кода

- Использовать async/await для endpoints
- Типизация параметров и возвращаемых значений
- Docstrings для сложных функций
- requirements.txt с фиксированными версиями
