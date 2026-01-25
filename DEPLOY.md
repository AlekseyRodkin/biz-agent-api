# Деплой Biz Agent API

## Первоначальная настройка (уже выполнено)

```bash
# Создать директорию
sudo mkdir -p /opt/biz-agent-api-git
sudo chown -R $USER:$USER /opt/biz-agent-api-git

# Клонировать репозиторий
cd /opt/biz-agent-api-git
git clone git@github.com:AlekseyRodkin/biz-agent-api.git biz-agent-api

# Создать venv и установить зависимости
cd biz-agent-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Запустить через PM2
pm2 start "bash -lc 'cd /opt/biz-agent-api-git/biz-agent-api && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000'" --name biz-agent-api
pm2 save
```

## Стандартный деплой (после git push)

```bash
cd /opt/biz-agent-api-git/biz-agent-api
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
pm2 restart biz-agent-api
curl -s http://127.0.0.1:8000/health
```

## Проверка статуса

```bash
pm2 list
pm2 logs biz-agent-api --lines 20
curl -s http://127.0.0.1:8000/health
```

## Откат

```bash
cd /opt/biz-agent-api-git/biz-agent-api
git log --oneline -5  # найти нужный коммит
git checkout <commit_hash>
pm2 restart biz-agent-api
```
