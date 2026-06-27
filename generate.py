import os
import re
import sys
import json
import time
import requests
from datetime import datetime

# --- Настройки ---
API_KEY = os.environ.get("GEMINI_API_KEY")
# Доступные на free-tier модели (RPD>0) от лучшей к запасной — по твоим лимитам в AI Studio.
# ВНИМАНИЕ: gemini-2.0-flash, gemini-1.5-*, *-pro на этом тарифе = 0 квоты → всегда 429, не использовать.
MODEL = "gemini-flash-latest"           # новейшая Flash, лучший арт; 5 RPM / 250K TPM / 20 RPD
FALLBACK_MODELS = [
    "gemini-3-flash-preview",            # 5 RPM / 250K TPM / 20 RPD
    "gemini-flash-lite-latest",       # 10 RPM / 250K TPM / 20 RPD — самый щедрый по запасу
]
MODELS = [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
RETRY_STATUS = {429, 500, 502, 503, 504}

# Перечни, согласованные с фронтендом (index.html)
ALLOWED_STYLES = ["aurora", "mesh", "dawn", "dusk", "bloom", "frost"]
ALLOWED_ART = ["constellation", "petals", "waves", "orbits", "lattice", "rays"]
ALLOWED_FONTS = ["playfair", "yeseva", "prata", "marck", "caveat",
                 "pacifico", "comfortaa", "unbounded", "philosopher", "lobster"]
ALLOWED_ANIMS = ["cascade", "fade", "blur", "scale", "drop", "glow", "wave"]

HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
FALLBACK_PALETTE = ["#f7d9c4", "#e7a3b6", "#c8a2d8"]

ARCHIVE_FILE = "archive.json"
RECENT_N = 8  # сколько прошлых открыток показываем модели, чтобы она не повторялась
PROOFREAD = True  # второй проход: лёгкая модель чинит грамматику двустишия
ART_MODE = "scene"  # "auto" — чередовать svg/scene по дням; "svg" — всегда SVG; "scene" — всегда сцена

_T0 = time.monotonic()


def log(msg):
    """Лог со временем от старта — видно, где уходит время."""
    print(f"[{time.monotonic() - _T0:6.1f}s] {msg}", flush=True)


def normalize_hex(c):
    if isinstance(c, str) and HEX.match(c.strip()):
        return "#" + c.strip().lstrip("#").lower()
    return None


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def call_gemini(payload, timeout=60, attempts=3, models=None):
    """Запрос с повторами при 429/5xx и каскадным откатом на другую модель.
    Возвращает распарсенный JSON-ответ модели или None, если все модели недоступны.
    timeout/attempts/models можно сузить для дешёвых вызовов (например, корректора)."""
    for model in (models or MODELS):
        url = f"{API_BASE}/{model}:generateContent?key={API_KEY}"
        for attempt in range(attempts):
            log(f"→ {model}: запрос (попытка {attempt + 1}/{attempts})…")
            t = time.monotonic()
            try:
                resp = requests.post(url, json=payload, timeout=timeout)
            except requests.RequestException as e:
                log(f"  {model}: сетевая ошибка: {e}; пауза 5с")
                time.sleep(5)
                continue
            dt = time.monotonic() - t

            if resp.status_code in RETRY_STATUS:
                ra = resp.headers.get("Retry-After", "")
                wait = float(ra) if ra.replace(".", "", 1).isdigit() else 5 * (attempt + 1)
                wait = min(wait, 30)
                kind = "перегрузка" if resp.status_code == 503 else "лимит"
                log(f"  {model}: HTTP {resp.status_code} ({kind}) за {dt:.1f}с; ждём {wait:.0f}с")
                time.sleep(wait)
                continue

            if not resp.ok:
                log(f"  {model}: HTTP {resp.status_code} за {dt:.1f}с: {resp.text[:200]}")
                break

            data = resp.json()
            cands = data.get("candidates") or []
            if not cands:
                log(f"  {model}: пустой ответ за {dt:.1f}с: {str(data)[:200]}")
                break
            try:
                text = cands[0]["content"]["parts"][0]["text"]
                obj = json.loads(text)
                log(f"  {model}: ответ за {dt:.1f}с, {len(text)} симв. — ОК")
                return obj
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                fr = (cands[0].get("finishReason") if cands else "") or ""
                hint = " (ответ обрезан по лимиту токенов!)" if fr == "MAX_TOKENS" else ""
                log(f"  {model}: не разобрал ответ ({e}); finishReason={fr}{hint}")
                break

        log(f"{model}: не вышло — следующая модель")
    return None


def proofread_verse(verse, rhyme):
    """Второй проход: чиним грамматику/согласование/пунктуацию, сохраняя смысл, рифму и
    обязательную фразу «Юлечка-<rhyme>». Низкая температура → стабильная корректность.
    При любой неудаче возвращаем исходное двустишие."""
    if not PROOFREAD:
        return verse
    text = " / ".join(verse)
    prompt = (
        "Ниже двустишие-поздравление для девушки по имени Юлечка.\n"
        f"«{text}»\n\n"
        "Проверь и при необходимости ИСПРАВЬ: согласование падежей, родов и чисел, "
        "грамматику, пунктуацию, естественность звучания. ОБЯЗАТЕЛЬНО сохрани смысл, рифму, "
        f"ритм и точную фразу «Юлечка-{rhyme}». Если всё уже верно — верни без изменений. "
        "Ровно 2 строки.\n\n"
        "Ответ строго JSON без markdown: {\"verse\": [\"строка1\", \"строка2\"]}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "responseSchema": {
                "type": "object",
                "properties": {"verse": {"type": "array", "items": {"type": "string"}}},
                "required": ["verse"],
            },
        },
    }
    try:
        # дёшево и быстро: одна лёгкая модель, 1 попытка, короткий таймаут — не растягиваем прогон
        res = call_gemini(payload, timeout=25, attempts=1, models=["gemini-2.5-flash-lite"])
        fixed = [str(s).strip() for s in (res.get("verse") or []) if str(s).strip()] if res else []
        if len(fixed) >= 2:
            return fixed[:4]
    except Exception as e:
        print(f"Корректор двустишия не сработал ({e}); оставляю исходное.")
    return verse


def main():
    log(f"Старт генерации. Модели: {MODELS}")
    # 1. Контекст прошлого: слова (для дедупа) + недавние открытки (чтобы не повторять настроение/палитру)
    history = load_json("history.json", [])
    archive = load_json(ARCHIVE_FILE, [])
    if not isinstance(archive, list):
        archive = []
    recent = archive[-RECENT_N:]
    recent_ctx = json.dumps(
        [{"mood": r.get("mood"), "palette": r.get("palette"), "font": r.get("font"), "anim": r.get("anim")}
         for r in recent],
        ensure_ascii=False,
    )

    # Чередуем тип арта по дням, чтобы появлялись и SVG, и живые JS-сцены
    if ART_MODE == "scene":
        prefer_scene = True
    elif ART_MODE == "svg":
        prefer_scene = False
    else:
        prefer_scene = (len(history) % 2 == 0)
    art_directive = (
        'СЕГОДНЯ обязательно сделай ЖИВУЮ JS-СЦЕНУ — заполни поле "scene", а "svg" оставь пустым "".'
        if prefer_scene else
        'СЕГОДНЯ сделай SVG — заполни поле "svg", а "scene" оставь пустым "".'
    )
    log(f"Тип арта сегодня: {'scene (JS-сцена)' if prefer_scene else 'svg'}")

    # 2. Промпт: Gemini — арт-директор всей открытки дня
    prompt = f"""
Ты — арт-директор и поэт. Каждый день ты создаёшь УНИКАЛЬНУЮ «открытку дня» для девушки Юлечки.
Замысел всегда про любовь и нежность к ней — НО у этого чувства бесконечно много оттенков,
и каждый день открытка должна быть ЗАМЕТНО другой: другое настроение, другая гамма,
другой шрифт, другой эффект. Удивляй. Избегай однообразия.

1) РИФМА. Придумай ОДНО новое милое/ласковое/забавное слово-рифму к имени "Юлечка"
   (например: красотулечка, симпатюлечка, капризулечка, лапулечка). Идеально звучит во фразе
   "Юлечка-[слово]".
   ТРЕБОВАНИЯ К СЛОВУ:
   - БЛАГОЗВУЧНОЕ и приятное, образовано от ПОЗИТИВНОГО корня (красота, нежность, радость,
     солнце, ласка, очарование…). Прочитай вслух — должно ласкать слух.
   - БЕЗ корявых/неуклюжих основ и случайных неприятных ассоциаций. Плохой пример: «обаянулечка»
     (слышится «баян»); лучше — «очарулечка», «обаяшечка». Если корень звучит странно — выбери другой.
   - Длина НЕ больше 12 букв, чтобы крупно помещалось на экране телефона; без чрезмерно длинных
     слов вроде «фейерверкулечка».
   - Естественное русское словообразование, без насилия над языком.
   НЕ ПОВТОРЯЙ слова из списка прошлых: {json.dumps(history, ensure_ascii=False)}.

2) НАСТРОЕНИЕ дня (1-2 слова). Перебирай ВЕСЬ спектр чувства, а не только «нежное»:
   нежное, страстное, игривое, мечтательное, искрящееся, тёплое, уютное, романтичное,
   восхищённое, шаловливое, светлое, трепетное, солнечное, томное, вдохновлённое, озорное,
   умиротворённое, влюблённое... Сегодня выбери оттенок, ЗАМЕТНО отличный от недавних.

3) ПАЛИТРА — ровно 3 цвета HEX (#RRGGBB), точно под сегодняшнее настроение и заметно
   отличная от недавних палитр. Гаммы бывают очень разные: пудрово-розовая, закатно-коралловая,
   сиренево-лиловая, золотисто-персиковая, мятно-розовая, винно-ягодная, небесно-голубая с тёплым
   акцентом, карамельно-бежевая... Изысканно и «дорого», не кисло и не грязно.

4) СТИЛЬ фона (мягкий градиент), строго из списка: aurora, mesh, dawn, dusk, bloom, frost.

5) АРТ — тип запасного линейного орнамента, строго из списка:
   constellation (созвездие), petals (цветочная мандала), waves (волны),
   orbits (орбиты), lattice (гильош), rays (лучи).

6) ШРИФT для слова — подбери под характер настроения, строго из ключей:
   playfair (драматичный сериф), yeseva (изысканный сериф), prata (тонкий дидон),
   philosopher (чистый элегантный), marck (рукописный, как любовное письмо),
   caveat (лёгкий рукописный), pacifico (весёлый скрипт), lobster (ретро-скрипт),
   comfortaa (мягкий округлый), unbounded (смелый современный).
   Чередуй: рукописные — для нежного/романтичного/игривого; серифы — для изысканного/мечтательного;
   округлый/современный — для уютного/озорного/смелого.

7) АНИМАЦИЯ появления слова, строго из списка:
   cascade (буквы поднимаются по очереди), fade (мягкое проявление),
   blur (из размытия в фокус), scale (вырастают), drop (падают с лёгким отскоком),
   glow (проявляются со свечением), wave (волной). Выбирай под настроение и не повторяй недавние.

8) SVG. Нарисуй САМ уникальный генеративный линейный орнамент — изящную абстракцию в духе
   дорогой гравюры/гильоша, художественно перекликающуюся с настроением и смыслом рифмы.
   СТРОГО:
   - цельный валидный <svg ...>...</svg> с viewBox="0 0 1000 1000";
   - можно использовать <defs> и <use href="#localId"> (локальные ссылки) для красивых повторов;
   - БЕЗ фонового прямоугольника (фон прозрачный), БЕЗ текста, растровых картинок,
     <script>, <style>, анимаций и внешних ссылок;
   - используй ТОЛЬКО цвета палитры; тонкие линии stroke-width 0.6–1.4, в основном fill="none",
     полупрозрачные штрихи (stroke-opacity 0.2–0.45);
   - сбалансированная композиция, заполняющая всё поле, — авторская абстракция.

9) ОЖИВИ орнамент встроенной SMIL-анимацией (НИКАКОГО JavaScript, только теги SVG):
   - <animateTransform attributeName="transform" type="rotate" ...> для ОЧЕНЬ медленного вращения
     (dur 30–120s, repeatCount="indefinite"); для вращения вокруг центра: from="0 500 500" to="360 500 500";
   - <animate attributeName="opacity" или "stroke-opacity" ...> для мягкого мерцания (dur 3–8s, с разными
     begin у элементов, чтобы мерцали не разом);
   - анимируй ТОЛЬКО transform / opacity / stroke-* (никаких href, событий, javascript:);
   - движение МЕДЛЕННОЕ и спокойное, оно НЕ должно отвлекать от слова в центре.

10) VERSE — короткое тёплое ДВУСТИШИЕ (ровно 2 строки) в рифму, в которое ОРГАНИЧНО входит
    фраза «Юлечка-[твоя рифма]». Это текст для голосовой озвучки.
    КРИТИЧЕСКИ ВАЖНО: безупречно грамотный русский — верное согласование падежей, родов и чисел,
    корректная пунктуация, живая естественная фраза без натяжек. Двустишие должно идеально
    звучать и читаться вслух, с чёткой рифмой и ровным ритмом. Сначала мысленно проверь грамматику,
    потом отвечай. Верни как массив из 2 строк в поле "verse".

11) SCENE (НЕОБЯЗАТЕЛЬНО, для максимального креатива) — можешь вместо SVG прислать ЖИВУЮ СЦЕНУ:
    небольшой самодостаточный JS-скрипт анимации на canvas. Он выполняется в ИЗОЛИРОВАННОЙ песочнице
    (sandbox, без доступа к странице и без сети). Тебе уже доступны переменные:
    - ctx — 2D-контекст canvas; W() и H() — ширина/высота вьюпорта в CSS-пикселях;
    - PALETTE — массив hex-цветов дня (используй ТОЛЬКО их); MOOD — строка настроения; DARK — тёмная ли тема.
    ПРАВИЛА: рисуй генеративную абстракцию в духе настроения; анимируй через requestAnimationFrame;
    движение МЕДЛЕННОЕ и спокойное, НЕ отвлекающее от текста по центру; фон прозрачный
    (НЕ заливай весь холст), линии/формы тонкие и полупрозрачные; БЕЗ текста; БЕЗ сети и внешних
    ресурсов. Не объявляй переменные с именами ctx/canvas/PALETTE/W/H. Если не уверен в качестве —
    оставь "scene" пустым (тогда покажется SVG). Верни код одной строкой в поле "scene".

ВАЖНО ПРО РАЗМЕР ОТВЕТА: дай ТОЛЬКО ОДНО из двух — либо "svg" (п.8), либо "scene" (п.11).
{art_directive}
ВТОРОЕ поле оставь ПУСТОЙ строкой "". НЕ заполняй оба сразу — это перегружает ответ. Держи код компактным.

НЕДАВНИЕ открытки (НЕ повторяй их настроение/палитру/шрифт/анимацию): {recent_ctx}

Ответ верни СТРОГО в формате JSON без markdown:
{{"rhyme":"...","mood":"...","palette":["#......","#......","#......"],"style":"bloom","art":"petals","font":"playfair","anim":"cascade","verse":["строка1","строка2"],"svg":"<svg viewBox=\\"0 0 1000 1000\\" xmlns=\\"http://www.w3.org/2000/svg\\">...</svg>","scene":""}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 1.3,   # выше разнообразие изо дня в день
            "topP": 0.95,
            "maxOutputTokens": 16384,   # запас, чтобы большой SVG/сцена не обрезались на полуслове
            "responseSchema": {
                "type": "object",
                "properties": {
                    "rhyme":   {"type": "string"},
                    "mood":    {"type": "string"},
                    "palette": {"type": "array", "items": {"type": "string"}},
                    "style":   {"type": "string", "enum": ALLOWED_STYLES},
                    "art":     {"type": "string", "enum": ALLOWED_ART},
                    "font":    {"type": "string", "enum": ALLOWED_FONTS},
                    "anim":    {"type": "string", "enum": ALLOWED_ANIMS},
                    "verse":   {"type": "array", "items": {"type": "string"}},
                    "svg":     {"type": "string"},
                    "scene":   {"type": "string"},
                },
                "required": ["rhyme", "mood", "palette", "style", "art", "font", "anim", "verse"],
            },
        },
    }

    # 3. Запрос (с повторами и каскадным откатом)
    log("Запрос открытки у Gemini (рифма/палитра/арт/двустишие)…")
    result = call_gemini(payload)
    if result is None:
        log("Все модели недоступны (лимит/перегрузка). data.json не трогаю — сайт покажет прошлую открытку.")
        sys.exit(0)

    # 4. Санитизация ответа (фронтенд тоже подстрахован)
    new_rhyme = result["rhyme"].strip().lower()
    mood = (result.get("mood") or "нежное").strip()

    palette = [normalize_hex(c) for c in result.get("palette", [])]
    palette = [c for c in palette if c]
    if len(palette) < 3:
        palette = FALLBACK_PALETTE

    style = result.get("style") if result.get("style") in ALLOWED_STYLES else "bloom"
    art = result.get("art") if result.get("art") in ALLOWED_ART else "petals"
    font = result.get("font") if result.get("font") in ALLOWED_FONTS else "playfair"
    anim = result.get("anim") if result.get("anim") in ALLOWED_ANIMS else "cascade"

    # Двустишие для озвучки (ровно 2 строки; если модель прислала иначе — подстрахуемся)
    verse = [str(s).strip() for s in (result.get("verse") or []) if str(s).strip()]
    if not verse:
        verse = [f"Юлечка-{new_rhyme},", "самая любимая на свете."]
    verse = verse[:4]
    log(f"Рифма: Юлечка-{new_rhyme} | настроение: {mood}")
    log("Корректор двустишия (лёгкая модель)…")
    verse = proofread_verse(verse, new_rhyme)   # лёгкий второй проход чинит грамматику

    # SVG: базовая проверка; финально чистит фронтенд. Если плох — "", страница откатится на мотив.
    svg = (result.get("svg") or "").strip()
    low = svg.lower()
    bad = "<script" in low or "</style" in low or "foreignobject" in low or "<iframe" in low
    if not (low.startswith("<svg") and "</svg>" in low) or bad or len(svg) > 80000:
        svg = ""

    # SCENE: JS-сцена. Выполняется в песочнице (sandbox+CSP) на фронте — здесь только лимит размера.
    scene = (result.get("scene") or "").strip()
    if len(scene) > 16000:
        scene = ""

    today_str = datetime.now().strftime("%Y-%m-%d")

    card = {
        "rhyme": new_rhyme,
        "mood": mood,
        "palette": palette,
        "style": style,
        "art": art,
        "font": font,
        "anim": anim,
        "verse": verse,
        "svg": svg,
        "scene": scene,
        "date": today_str,
    }

    # 5. Пишем сегодняшнюю открытку
    log("Пишу data.json / history.json / archive.json…")
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)

    # 6. История слов (для дедупа рифм)
    history.append(new_rhyme)
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # 7. Архив открыток (лёгкий, без svg/scene) — память «что было вчера» + контекст разнообразия
    archive.append({k: card[k] for k in ("date", "rhyme", "mood", "palette", "style", "art", "font", "anim", "verse")})
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    art_src = "scene-JS" if scene else ("Gemini-SVG" if svg else f"параметрика:{art}")
    log(f"Готово: Юлечка-{new_rhyme} | {mood} | стиль:{style} | арт:{art_src} | шрифт:{font} | аним:{anim} | {palette}")
    log("Двустишие: " + " / ".join(verse))
    log("Генератор завершён. Аудио — отдельным шагом (voice.py).")

    # 8. Озвучка вынесена в voice.py (Chatterbox — твой голос, с откатом на edge-tts).
    #    Воркфлоу запускает её отдельным шагом: python voice.py


if __name__ == "__main__":
    main()
