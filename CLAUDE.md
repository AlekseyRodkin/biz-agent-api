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

## Репозиторий

- **GitHub:** https://github.com/AlekseyRodkin/biz-agent-api
- **Локальная директория:** ~/projects/biz-agent-api

## Деплой на VPS (Timeweb)

**VPS директория:** `/opt/biz-agent-api-git/biz-agent-api`

**PM2 процесс:** `biz-agent-api` (id: 7)

**Порт:** 8000

### Инструментарий для Claude

- **Локальный git:** через Bash tool (git add, commit, push)
- **VPS команды:** через MCP `mcp__ssh-vps__exec`
- **GitHub API:** через MCP `mcp__github__*` (если нужно)

### Процедура деплоя

1. Локально запушить изменения:
```bash
cd ~/projects/biz-agent-api
git add . && git commit -m "описание" && git push origin main
```

2. На VPS через `mcp__ssh-vps__exec`:
```bash
cd /opt/biz-agent-api-git/biz-agent-api && git pull origin main
source .venv/bin/activate && pip install -r requirements.txt
pm2 restart biz-agent-api
curl -s http://127.0.0.1:8000/health
```

### Проверка статуса

```bash
pm2 list
pm2 logs biz-agent-api --lines 20
curl -s http://127.0.0.1:8000/health
```

## Правила кода

- Использовать async/await для endpoints
- Типизация параметров и возвращаемых значений
- Docstrings для сложных функций
- requirements.txt с фиксированными версиями
