import os
import re
import json
import requests
import subprocess
from datetime import datetime

# --- Настройки ---
API_KEY = os.environ.get("GEMINI_API_KEY")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

ALLOWED_STYLES = ["aurora", "mesh", "dawn", "dusk", "bloom", "frost"]
HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Резервная палитра, если модель пришлёт что-то невалидное
FALLBACK_PALETTE = ["#f7d9c4", "#e7a3b6", "#c8a2d8"]


def normalize_hex(c):
    if isinstance(c, str) and HEX.match(c.strip()):
        return "#" + c.strip().lstrip("#").lower()
    return None


def main():
    # 1. История прошлых рифм
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)

    # 2. Промпт: модель задаёт слово, настроение, палитру и стиль фона
    prompt = f"""
Ты — художник и поэт. Каждый день ты создаёшь уникальную «открытку дня» для девушки по имени Юлечка.

1) Придумай ОДНО новое милое, ласковое или забавное слово-рифму к имени "Юлечка"
   (например: красотулечка, симпатюлечка, капризулечка). Это полноценное или составное
   через дефис слово, которое идеально звучит во фразе "Юлечка-[слово]".
   Критически важно: НЕ ИСПОЛЬЗУЙ слова из этого списка прошлых генераций:
   {json.dumps(history, ensure_ascii=False)}.

2) Подбери НАСТРОЕНИЕ дня — 1-2 слова (например: нежное, игривое, тёплое,
   мечтательное, искрящееся, уютное).

3) Создай гармоничную эстетичную палитру из РОВНО 3 цветов в формате HEX (#RRGGBB),
   передающую это настроение. Цвета должны изысканно сочетаться, как у дорогого бренда,
   не быть кислотными или грязными.

4) Выбери стиль фона, наиболее подходящий настроению, строго из списка:
   aurora, mesh, dawn, dusk, bloom, frost.

Ответ верни СТРОГО в формате JSON без markdown:
{{"rhyme": "слово", "mood": "настроение", "palette": ["#......", "#......", "#......"], "style": "bloom"}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "rhyme":   {"type": "string"},
                    "mood":    {"type": "string"},
                    "palette": {"type": "array", "items": {"type": "string"}},
                    "style":   {"type": "string", "enum": ALLOWED_STYLES},
                },
                "required": ["rhyme", "mood", "palette", "style"],
            },
        },
    }

    # 3. Запрос к бесплатному API
    response = requests.post(URL, json=payload)
    response.raise_for_status()
    text_response = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(text_response)

    # 4. Санитизация ответа (фронтенд тоже подстрахован, но чистим и здесь)
    new_rhyme = result["rhyme"].strip().lower()
    mood = (result.get("mood") or "нежное").strip()

    palette = [normalize_hex(c) for c in result.get("palette", [])]
    palette = [c for c in palette if c]
    if len(palette) < 3:
        palette = FALLBACK_PALETTE

    style = result.get("style")
    if style not in ALLOWED_STYLES:
        style = "bloom"

    today_str = datetime.now().strftime("%Y-%m-%d")

    # 5. Пишем данные дня
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "rhyme": new_rhyme,
                "mood": mood,
                "palette": palette,
                "style": style,
                "date": today_str,
            },
            f, ensure_ascii=False, indent=2,
        )

    history.append(new_rhyme)
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Сгенерирована рифма: Юлечка-{new_rhyme} | настроение: {mood} | стиль: {style} | палитра: {palette}")



if __name__ == "__main__":
    main()
