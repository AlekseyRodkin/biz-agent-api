# Biz Agent API - Project Wiki

## Version History

### V2 (v0.2.2) - Align Supabase Contract & Indexes

**Изменения:**

1. **Таблицы приведены к единому контракту:**
   - `company_memory` (переименована из `memory`)
   - `course_chunks`
   - `course_lectures`
   - `user_progress`

2. **Индексы заменены на HNSW:**
   - `company_memory_embedding_idx` - HNSW vector_cosine_ops
   - `course_chunks_embedding_idx` - HNSW vector_cosine_ops
   - Удалены старые ivfflat индексы

3. **RPC функции обновлены:**
   - `match_company_memory(query_embedding, p_user_id, top)` → returns: id, memory_type, related_topic, question_asked, user_decision_raw, content, similarity
   - `match_course_chunks(query_embedding, filter, top)` → returns: chunk_id, lecture_id, lecture_title, speaker_type, content_type, sequence_order, content, similarity

4. **API контракт:**
   - POST /ask sources маппинг приведён к единому виду

---

### V1 (v0.2.1) - API Skeleton Core

**Создано:**
- FastAPI skeleton с /ask endpoint
- Локальные эмбеддинги (sentence-transformers, intfloat/multilingual-e5-small)
- Supabase RPC интеграция
- DeepSeek LLM через OpenAI SDK
- Веб-чат интерфейс

---

## Supabase Schema

### Таблицы

| Таблица | Назначение |
|---------|------------|
| `company_memory` | Корпоративная память (решения, FAQ, контекст) |
| `course_chunks` | Чанки лекций курса (для RAG) |
| `course_lectures` | Метаданные лекций |
| `user_progress` | Прогресс пользователя по курсу |

### RPC Functions

```sql
-- Поиск по корпоративной памяти
match_company_memory(query_embedding, p_user_id, top)

-- Поиск по чанкам курса
match_course_chunks(query_embedding, filter, top)
```

### Индексы (HNSW)

```sql
-- company_memory
CREATE INDEX company_memory_embedding_idx
  ON public.company_memory USING hnsw (embedding vector_cosine_ops);

-- course_chunks
CREATE INDEX course_chunks_embedding_idx
  ON public.course_chunks USING hnsw (embedding vector_cosine_ops);
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Веб-чат интерфейс |
| GET | `/health` | Health check |
| POST | `/ask` | RAG endpoint |

### POST /ask

**Request:**
```json
{
  "question": "Какой бюджет на маркетинг?"
}
```

**Response:**
```json
{
  "answer": "...",
  "sources": {
    "company": [
      {
        "id": "uuid",
        "memory_type": "decision",
        "related_topic": "marketing",
        "question_asked": "...",
        "user_decision_raw": "...",
        "similarity": 0.85
      }
    ],
    "course": [
      {
        "chunk_id": "lec01_chunk_005",
        "lecture_id": "lec01",
        "lecture_title": "Введение в маркетинг",
        "speaker_type": "instructor",
        "content_type": "explanation",
        "sequence_order": 5,
        "similarity": 0.78
      }
    ]
  }
}
```
