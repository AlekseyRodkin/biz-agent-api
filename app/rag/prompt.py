SYSTEM_PROMPT = """Ты — AI-агент для обучения бизнес-программе "Трансформация бизнеса с ИИ".

ПРАВИЛА:
- Отвечай кратко, пунктами
- Если course пустой — скажи, что лекции не загружены
- Приоритет: COMPANY_SOURCES (решения пользователя) > COURSE_SOURCES (методология)
- КРИТИЧЕСКИ ВАЖНО: проверяй COMPANY_SOURCES на расхождения с методологией
- Ты НЕ ИМЕЕШЬ ПРАВА молча игнорировать потенциальные конфликты
- Если решение пользователя противоречит методологии — укажи это

Если обнаружены расхождения между решениями пользователя и методологией, ДОБАВЬ секцию:

[ВОЗМОЖНЫЕ РАСХОЖДЕНИЯ]
- По методологии: что говорит курс
- У тебя принято: что пользователь решил ранее
- Риск: почему это может быть проблемой

В конце ответа ОБЯЗАТЕЛЬНО укажи SOURCES_USED: список id/chunk_id использованных источников."""


def build_messages(question: str, context: dict) -> list[dict]:
    company_sources = context.get("company", [])
    course_sources = context.get("course", [])

    company_block = ""
    if company_sources:
        company_block = "COMPANY_SOURCES:\n"
        for item in company_sources:
            item_id = item.get("id", "unknown")
            content = item.get("content", "")
            company_block += f"[id:{item_id}] {content}\n\n"

    course_block = ""
    if course_sources:
        course_block = "COURSE_SOURCES:\n"
        for item in course_sources:
            chunk_id = item.get("chunk_id", item.get("id", "unknown"))
            content = item.get("content", "")
            course_block += f"[chunk_id:{chunk_id}] {content}\n\n"

    user_content = f"Вопрос: {question}\n\n{company_block}\n{course_block}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
