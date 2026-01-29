#!/usr/bin/env python3
"""
⚠️  DEV/TEST ONLY - DO NOT USE IN PRODUCTION ⚠️

Generate fake course data for testing purposes.
Creates manifest CSV and lecture text files with placeholder content.

This script is NOT called by ingest_course.py.
It must be run manually and explicitly for development/testing.

Course structure:
- 4 modules
- Each module: ~5 days
- Each day: 4-6 lectures
- Mix of methodology (Верховский) and case_study (various speakers)

Usage:
  python scripts/generate_course_data.py

WARNING: This will overwrite data/lectures_manifest.csv and data/course/*.txt
"""

import csv
import os
import random

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "lectures_manifest.csv")
COURSE_DIR = os.path.join(DATA_DIR, "course")

# Module topics
MODULES = {
    1: {
        "name": "Бизнес-эффекты от ИИ",
        "days": [
            {"topics": ["Введение в программу", "Что такое бизнес-эффекты от ИИ", "Как искать бизнес-эффекты"]},
            {"topics": ["Кейс: ИИ в ритейле", "Практическое задание: оценка эффектов"]},
            {"topics": ["Методы оценки ROI", "Приоритизация проектов", "Матрица эффект/сложность"]},
            {"topics": ["Кейс: ИИ в логистике", "Кейс: ИИ в HR", "Практикум: ваш первый проект"]},
            {"topics": ["Подготовка бизнес-кейса", "Защита проекта перед стейкхолдерами"]}
        ]
    },
    2: {
        "name": "Данные и этапы внедрения",
        "days": [
            {"topics": ["Какие данные нужны для ИИ", "Оценка качества данных", "Data readiness assessment"]},
            {"topics": ["Кейс: подготовка данных в банке", "Практикум: аудит данных"]},
            {"topics": ["Этапы внедрения ИИ", "MVP vs Полное решение", "Критерии успеха пилота"]},
            {"topics": ["Кейс: пилот в производстве", "Кейс: пилот в e-commerce"]},
            {"topics": ["Масштабирование пилота", "Управление рисками", "Практикум: план внедрения"]}
        ]
    },
    3: {
        "name": "Команда и компетенции",
        "days": [
            {"topics": ["Роли в ИИ-команде", "Data Scientist vs ML Engineer", "Нужен ли свой ML?"]},
            {"topics": ["Кейс: построение команды в стартапе", "Кейс: ИИ-команда в корпорации"]},
            {"topics": ["Аутсорсинг vs In-house", "Работа с вендорами", "Критерии выбора решения"]},
            {"topics": ["Кейс: интеграция внешнего решения", "Практикум: оценка вендоров"]},
            {"topics": ["Обучение сотрудников", "Change management", "Культура данных"]}
        ]
    },
    4: {
        "name": "Стратегия масштабирования",
        "days": [
            {"topics": ["От пилота к платформе", "Архитектура ML-платформы", "MLOps основы"]},
            {"topics": ["Кейс: ML-платформа в Сбере", "Кейс: платформа в Яндексе"]},
            {"topics": ["Governance и этика ИИ", "Регуляторные требования", "Ответственный ИИ"]},
            {"topics": ["Кейс: ИИ в медицине", "Кейс: ИИ в финансах"]},
            {"topics": ["Стратегия ИИ-трансформации", "Дорожная карта", "Итоговое задание", "Защита проекта"]}
        ]
    }
}

# Speakers for case studies
CASE_SPEAKERS = [
    "Алексей Иванов",
    "Мария Петрова",
    "Дмитрий Козлов",
    "Анна Сидорова",
    "Сергей Волков",
    "Елена Новикова",
    "Павел Федоров",
    "Ольга Морозова"
]

# Content templates
METHODOLOGY_TEMPLATE = """# {title}

## Введение
В этом блоке мы рассмотрим {topic_lower}. Это важный этап в процессе трансформации бизнеса с помощью ИИ.

## Ключевые концепции
- Первый важный аспект {topic_lower}
- Второй критический момент для понимания
- Третий элемент методологии
- Как это связано с предыдущими темами

## Методология
По методологии Верховского, {topic_lower} включает несколько этапов:

1. **Анализ текущего состояния** — оценка исходной точки и ресурсов
2. **Определение целей** — формулировка измеримых показателей успеха
3. **Планирование действий** — детальный план с контрольными точками
4. **Реализация** — пошаговое выполнение плана
5. **Измерение результатов** — сравнение с целевыми показателями

## Типичные ошибки
Многие компании совершают следующие ошибки:
- Начинают без четких метрик успеха
- Недооценивают важность данных
- Пропускают этап пилотирования
- Не учитывают организационные изменения

## Практическое задание
Для закрепления материала выполните следующее:
1. Проанализируйте текущий процесс в вашей компании
2. Определите 2-3 потенциальные области применения ИИ
3. Оцените каждую по матрице "эффект/сложность"

## Резюме
{title} — это фундаментальный блок программы. Без понимания этих концепций невозможно успешно внедрить ИИ в бизнес-процессы.
"""

CASE_STUDY_TEMPLATE = """# {title}

## О кейсе
Рассмотрим практический пример {topic_lower}. Этот кейс демонстрирует реальный опыт внедрения ИИ.

## Контекст
Компания столкнулась с типичными вызовами:
- Ручные процессы занимали много времени
- Качество решений зависело от опыта сотрудников
- Масштабирование было затруднено

## Решение
Было принято решение внедрить ИИ-систему, которая:
- Автоматизирует рутинные операции
- Обеспечивает консистентность решений
- Позволяет масштабировать процесс

## Этапы внедрения
1. **Пилот (3 месяца)** — тестирование на ограниченном объеме
2. **Расширение (6 месяцев)** — масштабирование на другие направления
3. **Оптимизация (ongoing)** — постоянное улучшение модели

## Результаты
После внедрения компания достигла:
- Сокращение времени обработки на 60%
- Повышение точности решений на 25%
- ROI проекта: 300% за первый год

## Уроки
Ключевые выводы из этого кейса:
- Важность качественных данных с первого дня
- Необходимость вовлечения бизнес-пользователей
- Итеративный подход к развитию решения
"""

ASSIGNMENT_TEMPLATE = """# {title}

## Цель задания
Применить знания о {topic_lower} к вашей конкретной ситуации.

## Задание
Выполните следующие шаги:

1. **Анализ** — проанализируйте текущее состояние в вашей компании
2. **Идентификация** — найдите 2-3 возможности для применения ИИ
3. **Оценка** — оцените каждую возможность по критериям:
   - Потенциальный бизнес-эффект (высокий/средний/низкий)
   - Сложность реализации (высокая/средняя/низкая)
   - Доступность данных (есть/частично/нет)
4. **Приоритизация** — выберите приоритетный проект
5. **План** — составьте краткий план действий

## Формат отчета
Подготовьте документ на 2-3 страницы с:
- Описанием выбранного процесса
- Обоснованием выбора
- Планом первых шагов

## Критерии оценки
Ваша работа будет оценена по следующим критериям:
- Конкретность и измеримость
- Реалистичность плана
- Учет рисков и ограничений
"""


def generate_lecture_content(title: str, speaker_type: str) -> str:
    """Generate lecture content based on type."""
    topic_lower = title.lower()

    if "практи" in topic_lower or "задание" in topic_lower or "практикум" in topic_lower:
        return ASSIGNMENT_TEMPLATE.format(title=title, topic_lower=topic_lower)
    elif speaker_type == "case_study":
        return CASE_STUDY_TEMPLATE.format(title=title, topic_lower=topic_lower)
    else:
        return METHODOLOGY_TEMPLATE.format(title=title, topic_lower=topic_lower)


def generate_filename(lecture_id: str, speaker_type: str, speaker_name: str, title: str) -> str:
    """Generate filename for lecture."""
    # Clean title for filename - remove all problematic characters
    import re
    clean_title = re.sub(r'[^\w\s-]', '', title)  # Remove non-word chars except space and dash
    clean_title = clean_title.replace(" ", "_")[:30]
    clean_speaker = speaker_name.split()[0] if speaker_name else "Unknown"
    return f"{lecture_id.replace('-', '_')}__{speaker_type}__{clean_speaker}__{clean_title}.txt"


def main():
    print("Generating full course data (100 lectures)...")

    # Ensure directories exist
    os.makedirs(COURSE_DIR, exist_ok=True)

    lectures = []
    lecture_count = 0
    case_speaker_idx = 0

    for module_num, module_data in MODULES.items():
        for day_num, day_data in enumerate(module_data["days"], 1):
            for lecture_order, topic in enumerate(day_data["topics"], 1):
                lecture_count += 1

                # Determine speaker type based on topic keywords
                is_case = "кейс" in topic.lower()
                speaker_type = "case_study" if is_case else "methodology"

                if speaker_type == "methodology":
                    speaker_name = "Николай Верховский"
                else:
                    speaker_name = CASE_SPEAKERS[case_speaker_idx % len(CASE_SPEAKERS)]
                    case_speaker_idx += 1

                lecture_id = f"M{module_num}-D{day_num}-L{lecture_order:02d}"
                filename = generate_filename(lecture_id, speaker_type, speaker_name, topic)

                lectures.append({
                    "lecture_id": lecture_id,
                    "module": module_num,
                    "day": day_num,
                    "lecture_order": lecture_order,
                    "lecture_title": topic,
                    "speaker_name": speaker_name,
                    "speaker_type": speaker_type,
                    "source_file": filename
                })

                # Generate content and save to file
                content = generate_lecture_content(topic, speaker_type)
                filepath = os.path.join(COURSE_DIR, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

    # Write manifest
    with open(MANIFEST_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "lecture_id", "module", "day", "lecture_order",
            "lecture_title", "speaker_name", "speaker_type", "source_file"
        ])
        writer.writeheader()
        writer.writerows(lectures)

    print(f"\nGenerated:")
    print(f"  - Manifest: {MANIFEST_PATH}")
    print(f"  - Lectures: {len(lectures)} files in {COURSE_DIR}")

    # Stats
    methodology_count = sum(1 for l in lectures if l["speaker_type"] == "methodology")
    case_count = sum(1 for l in lectures if l["speaker_type"] == "case_study")
    print(f"\nDistribution:")
    print(f"  - Methodology: {methodology_count}")
    print(f"  - Case study: {case_count}")

    # By module
    print(f"\nBy module:")
    for m in range(1, 5):
        m_count = sum(1 for l in lectures if l["module"] == m)
        print(f"  - Module {m}: {m_count} lectures")


if __name__ == "__main__":
    main()
