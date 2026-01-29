# Biz Agent API

FastAPI backend service for AI-powered course learning system.

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
- `POST /ask` - QA mode (RAG)
- `POST /study/start` - Start/reset study progress
- `POST /study/next` - Get next methodology block
- `GET /decisions/review` - Review all user decisions
- `POST /decisions/refine` - Refine a decision

## Scripts

### Course Ingestion

```bash
# Validate manifest and files (ALWAYS run first)
python scripts/ingest_course.py --validate

# Preview without writing to DB
python scripts/ingest_course.py --dry-run

# Ingest all lectures
python scripts/ingest_course.py

# Ingest single module
python scripts/ingest_course.py --module 1

# Ingest single lecture
python scripts/ingest_course.py --lecture-id M1-D1-L02
```

**IMPORTANT:** Ingestion requires real course data:
- `data/lectures_manifest.csv` - manifest file
- `data/course/*.txt` - lecture text files

Without these files, ingestion will fail with pre-check error.

### Quality Control

```bash
# QC report for loaded data
python scripts/qc_course.py
```

### Purge Data

```bash
# Show current counts (dry-run)
python scripts/purge_course_data.py

# Delete all course data
python scripts/purge_course_data.py --force
```

### Test Data Generator (DEV ONLY)

```bash
# Generate test course data (53 fake lectures)
# ⚠️ FOR DEVELOPMENT/TESTING ONLY
# ⚠️ DO NOT use in production
python scripts/generate_course_data.py
```

## Data Directory Structure

```
data/
├── lectures_manifest.csv    # Required: lecture metadata
└── course/                  # Required: lecture text files
    ├── M1_D1_L01__methodology__Speaker__Title.txt
    └── ...
```

## Manifest CSV Format

```csv
lecture_id,module,day,lecture_order,lecture_title,speaker_name,speaker_type,source_file
M1-D1-L01,1,1,1,"Введение в программу","Николай Верховский","methodology","M1_D1_L01__methodology__Verkhovsky__Intro.txt"
```

## Деплой

См. [DEPLOY.md](DEPLOY.md)
