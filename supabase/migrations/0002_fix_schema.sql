-- =============================================================================
-- AiShift: Supabase Schema Fix Migration
-- Version: 0002_fix_schema
-- Description: Приведение схемы к контракту (пересоздание таблиц, данных нет)
-- =============================================================================

-- 1) Extensions (идемпотентно)
-- -----------------------------------------------------------------------------
create extension if not exists pgcrypto;
create extension if not exists vector;

-- 2) Drop существующих таблиц (порядок важен: сначала зависимые)
-- -----------------------------------------------------------------------------
drop table if exists course_chunks cascade;
drop table if exists course_lectures cascade;
drop table if exists company_memory cascade;
drop table if exists user_progress cascade;

-- Drop старых RPC функций (если существуют)
drop function if exists match_course_chunks(vector(384), int, jsonb);
drop function if exists match_company_memory(vector(384), int, text);

-- 3) course_lectures — метаданные лекций (PK: lecture_id)
-- -----------------------------------------------------------------------------
create table course_lectures (
  lecture_id text primary key,
  module smallint not null,
  day smallint not null,
  lecture_order smallint not null,
  lecture_title text not null,
  speaker_name text not null,
  speaker_type text not null check (speaker_type in ('methodology', 'case_study')),
  source_file text not null,
  created_at timestamptz default now()
);

create index idx_course_lectures_module_day_order
  on course_lectures (module, day, lecture_order);

-- 4) course_chunks — чанки курса с эмбеддингами
-- -----------------------------------------------------------------------------
create table course_chunks (
  id uuid primary key default gen_random_uuid(),
  chunk_id text unique not null,
  lecture_id text not null references course_lectures(lecture_id) on delete cascade,
  module smallint not null,
  day smallint not null,
  speaker_type text not null check (speaker_type in ('methodology', 'case_study')),
  speaker_name text not null,
  content_type text not null check (content_type in ('theory', 'assignment', 'example', 'tool')),
  sequence_order int not null,
  parent_topic text,
  content text not null,
  embedding vector(384),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);

create index idx_course_chunks_lecture_seq
  on course_chunks (lecture_id, sequence_order);

create index idx_course_chunks_module_day
  on course_chunks (module, day);

create index idx_course_chunks_embedding_hnsw
  on course_chunks using hnsw (embedding vector_cosine_ops);

-- 5) company_memory — память компании (решения пользователя)
-- -----------------------------------------------------------------------------
create table company_memory (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  memory_type text not null check (memory_type in ('decision', 'company_context', 'note')),
  status text not null check (status in ('active', 'superseded')) default 'active',
  related_module smallint,
  related_day smallint,
  related_lecture_id text,
  related_topic text,
  question_asked text,
  user_decision_raw text not null,
  user_decision_normalized text,
  source_chunk_ids text[] not null default '{}'::text[],
  embedding vector(384),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_company_memory_user_status
  on company_memory (user_id, status);

create index idx_company_memory_embedding_hnsw
  on company_memory using hnsw (embedding vector_cosine_ops);

-- 6) user_progress — прогресс прохождения курса (PK: user_id)
-- -----------------------------------------------------------------------------
create table user_progress (
  user_id text primary key,
  mode text not null check (mode in ('study', 'qa')) default 'study',
  current_module smallint not null default 1,
  current_day smallint not null default 1,
  current_lecture_id text,
  current_sequence_order int not null default 0,
  updated_at timestamptz default now()
);

-- 7) RPC: match_course_chunks — поиск по курсу (cosine similarity)
-- -----------------------------------------------------------------------------
create or replace function match_course_chunks(
  query_embedding vector(384),
  match_count int default 12,
  filter jsonb default '{}'::jsonb
)
returns table (
  chunk_id text,
  lecture_id text,
  lecture_title text,
  speaker_type text,
  speaker_name text,
  content_type text,
  sequence_order int,
  parent_topic text,
  content text,
  similarity float
)
language sql stable
as $$
  select
    c.chunk_id,
    c.lecture_id,
    l.lecture_title,
    c.speaker_type,
    c.speaker_name,
    c.content_type,
    c.sequence_order,
    c.parent_topic,
    c.content,
    1 - (c.embedding <=> query_embedding) as similarity
  from course_chunks c
  join course_lectures l on l.lecture_id = c.lecture_id
  where (filter = '{}'::jsonb or c.metadata @> filter)
  order by c.embedding <=> query_embedding asc
  limit match_count;
$$;

-- 8) RPC: match_company_memory — поиск по памяти компании
-- -----------------------------------------------------------------------------
create or replace function match_company_memory(
  query_embedding vector(384),
  match_count int default 6,
  p_user_id text default 'alexey'
)
returns table (
  id uuid,
  memory_type text,
  related_topic text,
  question_asked text,
  user_decision_raw text,
  user_decision_normalized text,
  source_chunk_ids text[],
  similarity float
)
language sql stable
as $$
  select
    m.id,
    m.memory_type,
    m.related_topic,
    m.question_asked,
    m.user_decision_raw,
    m.user_decision_normalized,
    m.source_chunk_ids,
    1 - (m.embedding <=> query_embedding) as similarity
  from company_memory m
  where m.user_id = p_user_id and m.status = 'active'
  order by m.embedding <=> query_embedding asc
  limit match_count;
$$;

-- =============================================================================
-- Smoke tests (запустить вручную для проверки):
--
-- select * from match_course_chunks(
--   array_fill(0::float, array[384])::vector(384),
--   1,
--   '{}'::jsonb
-- );
--
-- select * from match_company_memory(
--   array_fill(0::float, array[384])::vector(384),
--   1,
--   'alexey'
-- );
-- =============================================================================
-- End of migration 0002_fix_schema
-- =============================================================================