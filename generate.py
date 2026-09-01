import os
import re
import sys
import json
import time
import base64
import io
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

# --- Claude через OpenRouter: основной провайдер, если задан OPENROUTER_API_KEY ---
# (Gemini остаётся запасным; без ключа всё работает по-старому)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CLAUDE_MODELS = [
    "anthropic/claude-sonnet-5",      # лучший баланс качества/цены для творчества
    "anthropic/claude-sonnet-4.6",    # запасной
    "anthropic/claude-haiku-4.5",     # совсем запасной, дешёвый
]
CLAUDE_PROOFREAD_MODEL = "anthropic/claude-haiku-4.5"
# Кто пишет рифму и двустишие независимо от генератора оформления:
# "gemini" — только Gemini, "openrouter" — только Claude через OpenRouter,
# "auto" — Claude при наличии ключа, затем Gemini как запасной.
VERSE_PROVIDER = os.environ.get("VERSE_PROVIDER", "gemini").strip().lower()
if VERSE_PROVIDER not in {"gemini", "openrouter", "auto"}:
    raise ValueError("VERSE_PROVIDER должен быть gemini, openrouter или auto")
# Claude тянет куда более сложный генеративный код, чем Gemini Flash — лимиты шире
SCENE_MAX = 30000 if OPENROUTER_API_KEY else 16000

# Генерация растрового фона через OpenRouter (третий вариант арта).
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-3.1-flash-image").strip()
OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images"

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
VERSES_N = 14   # сколько прошлых двустиший показываем модели (против повторов образов)
END_WORDS_N = 40  # сколько последних концевых слов строк запрещаем повторять в рифме
PROOFREAD = True  # второй проход: лёгкая модель чинит грамматику двустишия
ART_MODE = os.environ.get("ART_MODE", "auto").strip().lower()
if ART_MODE not in {"auto", "svg", "scene", "image", "video"}:
    raise ValueError("ART_MODE должен быть auto, svg, scene, image или video")

_T0 = time.monotonic()


def log(msg):
    """Лог со временем от старта — видно, где уходит время."""
    print(f"[{time.monotonic() - _T0:6.1f}s] {msg}", flush=True)


def normalize_hex(c):
    if isinstance(c, str) and HEX.match(c.strip()):
        return "#" + c.strip().lstrip("#").lower()
    return None


# --- Ударения: чиним то, что Gemini ставит плохо (выдуманное слово + имя «Юлечка») ---
VOWELS = "аеёиоуыэюя"


def stress_rhyme(rhyme):
    """Ставит «+» перед ударной гласной рифмы по доминирующему паттерну «…Vлечка/лочка»
    (красот-У-лечка, симпат-Ю-лечка, слад-У-лечка). Неизвестный паттерн — без метки."""
    m = re.search(r"([" + VOWELS + r"])(л[еоа]чк)", rhyme.lower())
    if m:
        i = m.start(1)
        return rhyme[:i] + "+" + rhyme[i:]
    return rhyme


def fix_verse_tts(verse, rhyme):
    """Разметку ударений строим САМИ из чистого текста и помечаем ТОЛЬКО «Юлечка» и рифму —
    Gemini ошибается даже в обычных словах. Остальные слова оставляем без меток
    (Chatterbox прочитает их по своей просодии, для словарных слов это надёжнее)."""
    sr = stress_rhyme(rhyme)
    rl = rhyme.lower()
    out = []
    for line in verse:
        line = line.replace("+", "")          # снять любые чужие пометки
        toks = re.split(r"(\s+)", line)
        for i, tok in enumerate(toks):
            if not tok.strip():
                continue
            sub = tok.split("-")
            for j, sp in enumerate(sub):
                m = re.match(r"^([^\w]*)(.*?)([^\w]*)$", sp, re.S)
                pre, core, post = m.group(1), m.group(2), m.group(3)
                low = core.lower()
                if low == "юлечка":
                    core = "+Юлечка"
                elif low == rl:
                    core = sr
                sub[j] = pre + core + post
            toks[i] = "-".join(sub)
        marked = "".join(toks)
        # Chatterbox иногда проглатывает вторую половину длинного выдуманного
        # слова через дефис. Для озвучки превращаем обращение в приложение с
        # короткой паузой: «Юлечка, осенюлечка». Отображаемый verse не меняется.
        marked_rhyme = stress_rhyme(rhyme)
        compound = re.compile(
            r"(?P<name>\+[Юю]лечка)-" + re.escape(marked_rhyme), re.IGNORECASE
        )
        marked = compound.sub(lambda m: m.group("name") + ", " + marked_rhyme, marked)
        out.append(marked)
    return out


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
SEASONS_RU = {
    1: "зима", 2: "зима", 3: "весна", 4: "весна", 5: "весна",
    6: "лето", 7: "лето", 8: "лето", 9: "осень", 10: "осень",
    11: "осень", 12: "зима",
}
# Только поводы, которые естественно подходят взрослой романтической паре.
# Школьные, детские, государственные, военные, профессиональные и религиозные
# даты сюда намеренно не добавляются.
COUPLE_OCCASIONS = {
    (1, 1): "Новый год",
    (2, 14): "День святого Валентина",
    (3, 8): "Международный женский день",
    (7, 8): "День семьи, любви и верности",
    (12, 31): "канун Нового года",
}
COUPLE_OCCASION_MARKERS = {
    "новогодний повод": (
        {"Новый год", "канун Нового года"},
        ("новый год", "нового года", "новогод"),
    ),
    "День святого Валентина": (
        {"День святого Валентина"},
        ("день святого валентина", "валентинк"),
    ),
    "Международный женский день": (
        {"Международный женский день"},
        ("женский день", "8 марта", "восьмое марта"),
    ),
    "День семьи, любви и верности": (
        {"День семьи, любви и верности"},
        ("день семьи", "любви и верности"),
    ),
}
UNSUITABLE_OCCASION_MARKERS = {
    "школьная тема": ("день знаний", "первокласс", "школьн", "учебный год"),
    "профессиональный праздник": (
        "день космонавтики", "днём космонавтики", "дня космонавтики",
        "день учителя", "днём учителя", "дня учителя",
        "день программиста", "днём программиста", "дня программиста",
    ),
    "государственный или военный праздник": (
        "день победы", "день россии", "день защитника отечества",
        "народного единства", "23 февраля",
    ),
    "религиозный праздник": ("рождеств", "пасх"),
}
SEASON_FIRST_DAYS = {
    (3, 1): "первый день весны",
    (6, 1): "первый день лета",
    (9, 1): "первый день осени",
    (12, 1): "первый день зимы",
}


def moscow_now():
    """Current Moscow time, with a safe local-time fallback."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Moscow"))
    except Exception:
        return datetime.now()


def build_calendar_info(now):
    occasions = []
    season_start = SEASON_FIRST_DAYS.get((now.month, now.day))
    special = COUPLE_OCCASIONS.get((now.month, now.day))
    if season_start:
        occasions.append(season_start)
    if special:
        occasions.append(special)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "date_ru": f"{now.day} {MONTHS_RU[now.month - 1]} {now.year} года",
        "season": SEASONS_RU[now.month],
        "occasions": occasions,
    }


def calendar_prompt(info):
    occasion = ", ".join(info["occasions"]) if info["occasions"] else "нет обязательного повода"
    return f"""КАЛЕНДАРНЫЙ КОНТЕКСТ (строгий факт, но не обязательная тема):
- сегодня по Москве: {info['date_ru']}; текущее время года — {info['season']};
- значимый повод: {occasion}.
Не превращай каждое двустишие в стих о календаре: в обычный день лучше выбрать свежий
вневременной образ. Значимый повод можно использовать только если он естественно украшает
любовное двустишие. Но если упоминаешь месяц, сезон, праздник или сезонный образ, он ОБЯЗАН
соответствовать этим данным. Нельзя писать про другое время года. Не выдумывай конкретную
погоду только на основании календаря. Используй ТОЛЬКО повод, явно перечисленный выше.
Не добавляй самостоятельно школьные, детские, государственные, военные, профессиональные,
религиозные или другие памятные даты. Если указан «нет обязательного повода», вообще не
упоминай праздники."""


def wrong_calendar_references(verse, info):
    """Return explicit season/month words that contradict today's Moscow date."""
    text = " ".join(verse).lower()
    words = re.findall(r"[а-яё]+", text)
    found = set()
    for word in words:
        if word.startswith("зим"):
            found.add("зима")
        elif word.startswith("весн") or word.startswith("весен"):
            found.add("весна")
        elif word.startswith("осен") or word in {"осень", "осени", "осенью"}:
            found.add("осень")
        elif word.startswith("летн") or word in {"лето", "лета", "летом", "лету"}:
            found.add("лето")
    wrong = {season for season in found if season != info["season"]}

    month_stems = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4,
        "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
        "ноябр": 11, "декабр": 12,
    }
    for word in words:
        for stem, month in month_stems.items():
            if word.startswith(stem) and month != int(info["date"][5:7]):
                wrong.add(MONTHS_RU[month - 1])
        if (word in {"май", "мая", "маю", "маем", "мае"} or word.startswith("майск")) \
                and int(info["date"][5:7]) != 5:
            wrong.add(MONTHS_RU[4])

    allowed = set(info["occasions"])
    for label, (allowed_names, markers) in COUPLE_OCCASION_MARKERS.items():
        if allowed.isdisjoint(allowed_names) and any(marker in text for marker in markers):
            wrong.add(label)
    for label, markers in UNSUITABLE_OCCASION_MARKERS.items():
        if any(marker in text for marker in markers):
            wrong.add(label)
    return sorted(wrong)


def call_gemini(payload, timeout=60, attempts=8, models=None):
    """Запрос с повторами при 429/5xx и каскадным откатом на другую модель.
    Возвращает распарсенный JSON или None, если все модели недоступны.
    503 (перегрузка) — временная, поэтому повторов на модель много (attempts)."""
    for model in (models or MODELS):
        url = f"{API_BASE}/{model}:generateContent?key={API_KEY}"
        for attempt in range(attempts):
            log(f"→ {model}: попытка {attempt + 1}/{attempts}…")
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
                wait = min(wait, 45)
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


def _extract_json(text):
    """Достаёт JSON-объект из ответа модели: срезает ```-заборы и текст вокруг."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise json.JSONDecodeError("в ответе нет JSON-объекта", text, 0)
    return json.loads(m.group(0))


def call_openrouter(prompt, max_tokens=16384, attempts=3, models=None, timeout=120):
    """Claude через OpenRouter (chat/completions), с повторами и каскадом моделей.
    Возвращает распарсенный JSON или None (тогда зовём Gemini).
    ВАЖНО: сэмплинг-параметры (temperature и т.п.) НЕ шлём — новые модели Claude
    их не принимают; формат ответа обеспечивает сам промпт."""
    if not OPENROUTER_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yulechkaa.github.io",
        "X-Title": "Yulechka Daily Card",
    }
    for model in (models or CLAUDE_MODELS):
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        for attempt in range(attempts):
            log(f"→ OpenRouter {model}: попытка {attempt + 1}/{attempts}…")
            t = time.monotonic()
            try:
                resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=timeout)
            except requests.RequestException as e:
                log(f"  {model}: сетевая ошибка: {e}; пауза 5с")
                time.sleep(5)
                continue
            dt = time.monotonic() - t

            if resp.status_code in RETRY_STATUS:
                wait = min(5 * (attempt + 1), 45)
                log(f"  {model}: HTTP {resp.status_code} за {dt:.1f}с; ждём {wait}с")
                time.sleep(wait)
                continue

            if not resp.ok:
                log(f"  {model}: HTTP {resp.status_code} за {dt:.1f}с: {resp.text[:200]}")
                break

            try:
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                obj = _extract_json(text)
                log(f"  {model}: ответ за {dt:.1f}с, {len(text)} симв. — ОК")
                return obj
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                log(f"  {model}: не разобрал ответ ({e})")
                break

        log(f"OpenRouter {model}: не вышло — следующая модель")
    return None


def generate_background_image(prompt, output_path, attempts=3):
    """Генерирует вертикальный фон через OpenRouter Images API и сохраняет WebP."""
    if not OPENROUTER_API_KEY:
        log("OPENROUTER_API_KEY не задан — растровый фон пропущен.")
        return False

    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "1K",
        "n": 1,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yulechkaa.github.io",
        "X-Title": "Yulechka Daily Card",
    }

    for attempt in range(attempts):
        log(f"→ {IMAGE_MODEL}: фон, попытка {attempt + 1}/{attempts}…")
        try:
            resp = requests.post(OPENROUTER_IMAGE_URL, json=payload, headers=headers, timeout=180)
        except requests.RequestException as e:
            log(f"  image API: сетевая ошибка: {e}")
            time.sleep(5)
            continue
        if resp.status_code in RETRY_STATUS:
            wait = min(8 * (attempt + 1), 30)
            log(f"  image API: HTTP {resp.status_code}; ждём {wait}с")
            time.sleep(wait)
            continue
        if not resp.ok:
            log(f"  image API: HTTP {resp.status_code}: {resp.text[:240]}")
            return False

        try:
            data = resp.json()
            image_part = next(item for item in (data.get("data") or []) if item.get("b64_json"))
            raw = base64.b64decode(image_part["b64_json"], validate=True)
            from PIL import Image
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            image.save(output_path, "WEBP", quality=84, method=6)
            log(f"  фон сохранён: {output_path} ({os.path.getsize(output_path) // 1024} КБ)")
            return True
        except (KeyError, StopIteration, ValueError, OSError) as e:
            log(f"  image API: не удалось разобрать изображение ({e})")
            return False
    return False


def generate_verse(provider, history, past_verses_ctx, banned_end_words, calendar_ctx):
    """Отдельно генерирует рифму и двустишие выбранным провайдером."""
    prompt = f"""Ты — русский поэт. Придумай для девушки Юлечки одну новую ласковую рифму
к имени «Юлечка» и тёплое двустишие с ней.

{calendar_ctx}

РИФМА:
- одно благозвучное слово не длиннее 12 букв для фразы «Юлечка-[слово]»;
- позитивный, целый и легко узнаваемый корень + естественное «-улечка/-юлечка»;
- не повторяй уже использованные слова: {json.dumps(history, ensure_ascii=False)};
- плохие примеры: «пламулечка», «обаянулечка», «фейерверкулечка».

ДВУСТИШИЕ:
- ровно 2 строки, грамотный естественный русский, ровный ритм и свежая точная рифма;
- фраза «Юлечка-[твоя рифма]» входит ровно один раз, лучше внутри строки;
- концы строк — разные созвучные слова, нельзя рифмовать слово само с собой;
- «шкатулочка» запрещена в любом виде;
- запрещённые концевые слова: {json.dumps(banned_end_words, ensure_ascii=False)};
- не повторяй образы и обороты прошлых двустиший: {past_verses_ctx}.

Ответ строго JSON без markdown:
{{"rhyme":"слово","verse":["строка 1","строка 2"]}}"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 1.2,
            "topP": 0.95,
            "maxOutputTokens": 2048,
            "responseSchema": {
                "type": "object",
                "properties": {
                    "rhyme": {"type": "string"},
                    "verse": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["rhyme", "verse"],
            },
        },
    }

    log(f"Провайдер стихов: {provider}.")
    result = None
    if provider in {"openrouter", "auto"}:
        if OPENROUTER_API_KEY:
            result = call_openrouter(prompt, max_tokens=2048, timeout=60)
        elif provider == "openrouter":
            log("Для VERSE_PROVIDER=openrouter не задан OPENROUTER_API_KEY.")
        if result is None and provider == "auto":
            log("Стихи через OpenRouter недоступны — пробую Gemini.")
    if result is None and provider in {"gemini", "auto"}:
        result = call_gemini(payload, timeout=60, attempts=3)
    if result is None:
        return None

    rhyme = str(result.get("rhyme") or "").strip().lower()
    verse = [str(s).strip() for s in (result.get("verse") or []) if str(s).strip()]
    if not rhyme or len(verse) != 2:
        log("Провайдер стихов вернул неполный ответ.")
        return None
    return {"rhyme": rhyme, "verse": verse}


def proofread_verse(verse, rhyme, banned=(), provider="auto", calendar_ctx=""):
    """Второй проход: чиним грамматику/согласование/пунктуацию двустишия и убираем «рифму
    слова с самим собой». Сохраняем смысл и точную фразу «Юлечка-<rhyme>». Ударения НЕ трогаем —
    их ставит fix_verse_tts(). При любой неудаче возвращаем исходное."""
    if not PROOFREAD:
        return verse
    text = " / ".join(verse)
    ban = ""
    if banned:
        ban = (f"\nЗАПРЕЩЁННЫЕ слова (не добавляй их при правке): "
               f"{json.dumps(list(banned), ensure_ascii=False)}. "
               "Слово «шкатулочка» запрещено в любом виде.")
    prompt = (
        "Ниже двустишие-поздравление для девушки по имени Юлечка.\n"
        f"«{text}»\n\n"
        f"{calendar_ctx}\n\n"
        "Проверь и при необходимости ИСПРАВЬ: согласование падежей, родов и чисел, грамматику, "
        f"пунктуацию, естественность. ОБЯЗАТЕЛЬНО сохрани смысл, ритм и точную фразу «Юлечка-{rhyme}». "
        "ВАЖНО: строки НЕ должны рифмоваться одинаковым словом — концы строк должны быть РАЗНЫМИ "
        "созвучными словами (никаких «солнцулечка/солнцулечка»). Рифменную пару двустишия сохрани; "
        "если рифма ленивая — перепиши одну строку так, чтобы концы строк стали разными созвучными "
        f"словами. Ровно 2 строки.{ban}\n\n"
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
        res = None
        if provider in {"openrouter", "auto"} and OPENROUTER_API_KEY:
            res = call_openrouter(prompt, max_tokens=1024, attempts=1,
                                  models=[CLAUDE_PROOFREAD_MODEL], timeout=30)
        if res is None and provider in {"gemini", "auto"}:
            res = call_gemini(payload, timeout=25, attempts=1, models=["gemini-2.5-flash-lite"]) or {}
        v = [str(s).strip() for s in (res.get("verse") or []) if str(s).strip()]
        if len(v) >= 2:
            return v[:4]
    except Exception as e:
        print(f"Корректор двустишия не сработал ({e}); оставляю исходное.")
    return verse


def main():
    log(f"Старт генерации. Модели: {MODELS}; стихи: {VERSE_PROVIDER}")
    now = moscow_now()
    calendar_info = build_calendar_info(now)
    calendar_ctx = calendar_prompt(calendar_info)
    today_str = calendar_info["date"]
    log(
        f"Календарь: {calendar_info['date_ru']}, сезон: {calendar_info['season']}, "
        f"повод: {', '.join(calendar_info['occasions']) or '—'}"
    )
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

    # Прошлые двустишия — модель их видит и не повторяет образы/обороты
    past_verses = [" / ".join(r["verse"]) for r in archive if r.get("verse")]
    past_verses_ctx = json.dumps(past_verses[-VERSES_N:], ensure_ascii=False)

    # Концевые слова строк прошлых двустиший — запрещаем их в рифме, чтобы не заезживались
    # («шкатулочка» — в бане навсегда: это почти единственная словарная рифма к «-улечке»,
    # и модель тянется к ней каждый раз)
    banned_end_words = ["шкатулочка", "шкатулочкой", "шкатулочку"]
    for r in archive:
        for line in r.get("verse") or []:
            words = re.findall(r"[а-яёА-ЯЁ]+", line)
            if words:
                w = words[-1].lower()
                if w not in banned_end_words:
                    banned_end_words.append(w)
    banned_end_words = banned_end_words[:3] + banned_end_words[3:][-END_WORDS_N:]

    # Рифма и двустишие создаются отдельным запросом. Так выбор поэтической модели
    # не зависит от модели, которая затем рисует и оформляет открытку.
    poem = None
    for calendar_attempt in range(2):
        extra = ""
        if calendar_attempt:
            extra = (
                "\nПРЕДЫДУЩИЙ ВАРИАНТ БЫЛ ОТКЛОНЁН из-за неверного времени года. "
                f"Сегодня только {calendar_info['season']}; либо используй её, либо вообще "
                "не упоминай сезоны."
            )
        candidate = generate_verse(
            VERSE_PROVIDER, history, past_verses_ctx, banned_end_words,
            calendar_ctx + extra,
        )
        if candidate is None:
            continue
        wrong = wrong_calendar_references(candidate["verse"], calendar_info)
        if wrong:
            log(f"Стих отклонён: неверный сезон ({', '.join(wrong)}); повторяю запрос.")
            continue
        poem = candidate
        break
    if poem is None:
        log("Не удалось получить календарно актуальный стих. data.json не трогаю.")
        sys.exit(0)
    log("Корректор двустишия (тот же провайдер)…")
    proofread = proofread_verse(
        poem["verse"], poem["rhyme"], banned_end_words, VERSE_PROVIDER, calendar_ctx
    )
    if wrong_calendar_references(proofread, calendar_info):
        log("Корректор добавил неверную календарную ссылку — оставляю исходное двустишие.")
    else:
        poem["verse"] = proofread

    # Концепции прошлых артов — чтобы каждый день был новый художественный замысел
    recent_concepts = [r["concept"] for r in archive if r.get("concept")][-10:]

    # Четыре типа арта: SVG, canvas-сцена, AI-иллюстрация и деликатный видеофон.
    # В auto они равномерно чередуются по истории открыток.
    art_mode_today = ART_MODE if ART_MODE != "auto" else ("scene", "svg", "image", "video")[len(history) % 4]
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            output.write(f"art_mode={art_mode_today}\n")
    if art_mode_today == "image":
        art_directive = '''СЕГОДНЯ сделай AI-ИЛЛЮСТРАЦИЮ С ЖИВЫМИ СЛОЯМИ:
   - поле "image_prompt": подробный самостоятельный промпт для генератора изображения на основе
     двустишия и концепции; вертикальная композиция 9:16, главный образ по краям/в верхней и нижней
     трети, спокойный малоконтрастный центр под крупную надпись; без букв, текста, рамок и логотипов;
   - поле "scene": прозрачная медленная canvas-анимация ПОВЕРХ изображения: световая пыль,
     тонкие линии, мягкие блики или частицы, которые продолжают образ, но не закрывают центр;
   - поле "svg" оставь пустым "".'''
    elif art_mode_today == "video":
        art_directive = '''СЕГОДНЯ сделай ОСНОВУ ДЛЯ ДЕЛИКАТНОГО ВИДЕОФОНА:
   - поле "image_prompt": подробный самостоятельный промпт для статичной иллюстрации на основе
     двустишия и концепции; вертикальная композиция 9:16, главный образ по краям/в верхней и нижней
     трети, спокойный малоконтрастный центр под крупную надпись; без букв, текста, рамок и логотипов;
   - эта иллюстрация затем получит только локальные микроэффекты: блики, блёстки и переливы;
   - поля "scene" и "svg" оставь пустыми "".'''
    elif art_mode_today == "scene":
        art_directive = ('СЕГОДНЯ обязательно сделай ЖИВУЮ JS-СЦЕНУ — заполни поле "scene", '
                         'а "svg" и "image_prompt" оставь пустыми "".')
    else:
        art_directive = ('СЕГОДНЯ сделай SVG — заполни поле "svg", '
                         'а "scene" и "image_prompt" оставь пустыми "".')
    log(f"Тип арта сегодня: {art_mode_today}")


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
   - БЕЗ корявых/неуклюжих основ и случайных неприятных ассоциаций. Плохие примеры: «обаянулечка»
     (слышится «баян»), «пламулечка» (корень «плам-» обрублен и груб). Корень должен остаться
     ЦЕЛЫМ и узнаваемым («красот-» → красота). Если корень звучит странно — выбери другой.
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

8) VERSE — короткое тёплое ДВУСТИШИЕ (ровно 2 строки) в рифму, в которое ОРГАНИЧНО входит
    фраза «Юлечка-[твоя рифма]» (ровно ОДИН раз). Это текст для голосовой озвучки.
    КРИТИЧЕСКИ ВАЖНО: безупречно грамотный русский — верное согласование падежей, родов и чисел,
    корректная пунктуация, живая естественная фраза без натяжек. Двустишие должно идеально
    звучать и читаться вслух, с чёткой рифмой и ровным ритмом.
    КАК СТРОИТЬ РИФМУ (это главное против однообразия):
    - ЛУЧШИЙ приём: поставь «Юлечка-[рифма]» ВНУТРИ одной из строк, а сами строки рифмуй
      ЛЮБОЙ другой свежей парой слов (как «тиши/души», «холода/звезда», «тень/день»,
      «рассвет/секрет»). Так рифменная пара каждый день новая.
    - Можно и рифмовать на саму «[рифму]» в конце строки — но ТОЛЬКО если второе слово-рифма
      свежее и не из запретного списка ниже.
    - ЗАПРЕЩЕНО рифмовать слово само с собой (плохо: «солнцулечка / солнцулечка»).
    ЗАПРЕЩЁННЫЕ КОНЦЕВЫЕ СЛОВА СТРОК (уже были в прошлых открытках, повтор = провал):
    {json.dumps(banned_end_words, ensure_ascii=False)}.
    Слово «шкатулочка» ЗАПРЕЩЕНО в любом виде и в любом месте двустишия — оно заезжено.
    ПРОШЛЫЕ ДВУСТИШИЯ — НЕ повторяй их образы, сравнения и обороты, найди новый мотив:
    {past_verses_ctx}
    Сначала мысленно проверь грамматику, рифму и запреты, потом отвечай.
    Верни как массив из 2 строк в поле "verse".

9) КОНЦЕПЦИЯ АРТА (поле "concept"). Перечитай СВОЁ двустишие из п.8 и выпиши его образы
   (рассвет, звёзды, крыло, сад, море, чашка, пламя свечи…). Выбери ОДИН центральный образ
   и придумай его художественную интерпретацию — как настоящий арт-принт или плакат,
   а НЕ «узор вообще». Каждый день — НОВЫЙ художественный язык. Направления для вдохновения
   (не ограничивайся списком): рисунок одной непрерывной линией, японская гравюра (волна,
   ветви, туман), ар-деко (лучи, дуги, симметрия), витражная геометрия, ботаническая
   иллюстрация, созвездие с историей, каллиграфический росчерк, пуантилизм из сотен точек,
   баухаус-геометрия, муар и оптические наложения, многослойный «вырезанный из бумаги» пейзаж,
   спираль золотого сечения, поток частиц на ветру.
   ЗАПРЕЩЕНО повторять концепции прошлых дней: {json.dumps(recent_concepts, ensure_ascii=False)}.
   СТРОГО ЗАПРЕЩЕНЫ образы с траурными ассоциациями: свечи и их пламя, венки, кресты,
   увядшие цветы, гаснущий огонёк — ничего, что можно прочитать как скорбь.
   Запиши замысел ОДНОЙ фразой в поле "concept" — например: «пар над чашкой сплетается
   в силуэт сердца — рисунок одной линией».

10) SVG — воплоти концепцию из п.9. Это должно УДИВЛЯТЬ: зритель должен узнать образ из стиха.
   СТРОГО:
   - цельный валидный <svg ...>...</svg> с viewBox="0 0 1000 1000";
   - можно <defs>, <use href="#localId">, локальные <linearGradient>/<radialGradient> из цветов палитры;
   - БЕЗ фонового прямоугольника (фон прозрачный), БЕЗ текста, растровых картинок,
     <script>, <style> и внешних ссылок.
   Художественные средства СВОБОДНЫ: тонкая линия (0.6–1.5) и жирный штрих (2–4), заливки
   с прозрачностью (fill-opacity 0.06–0.3), точки, штриховка, повторы через <use>.
   Композиция НЕ обязана быть центральной мандалой: смело используй асимметрию, диагональ,
   крупный образ со смещением, сцену по краям кадра. ЕДИНСТВЕННОЕ ПРАВИЛО КОМПОЗИЦИИ:
   середина экрана остаётся спокойной и малоконтрастной — там живёт слово дня.
   ОЖИВИ арт встроенной SMIL-анимацией (НИКАКОГО JavaScript, только теги SVG):
   - <animateTransform type="rotate/translate/scale"> — ОЧЕНЬ медленное движение
     (dur 30–120s, repeatCount="indefinite"); вращение вокруг центра: from="0 500 500" to="360 500 500";
   - <animate attributeName="opacity"/"stroke-opacity"> — мягкое мерцание (dur 3–8s,
     разные begin, чтобы не разом);
   - анимируй ТОЛЬКО transform / opacity / stroke-* / fill-opacity (никаких href, событий, javascript:);
   - движение МЕДЛЕННОЕ, оно НЕ должно отвлекать от слова в центре.

11) SCENE (НЕОБЯЗАТЕЛЬНО, для максимального креатива) — можешь вместо SVG прислать ЖИВУЮ СЦЕНУ:
    небольшой самодостаточный JS-скрипт анимации на canvas. Он выполняется в ИЗОЛИРОВАННОЙ песочнице
    (sandbox, без доступа к странице и без сети). Тебе уже доступны переменные:
    - ctx — 2D-контекст canvas; W() и H() — ширина/высота вьюпорта в CSS-пикселях;
    - PALETTE — массив hex-цветов дня (используй ТОЛЬКО их); MOOD — строка настроения; DARK — тёмная ли тема.
    ПРАВИЛА: воплоти ту же концепцию из п.9 (её живую canvas-вариацию); анимируй через requestAnimationFrame;
    движение МЕДЛЕННОЕ и спокойное, НЕ отвлекающее от текста по центру; фон прозрачный
    (НЕ заливай весь холст), линии/формы тонкие и полупрозрачные; БЕЗ текста; БЕЗ сети и внешних
    ресурсов. Не объявляй переменные с именами ctx/canvas/PALETTE/W/H. Если не уверен в качестве —
    оставь "scene" пустым (тогда покажется SVG). Верни код одной строкой в поле "scene".

ФОРМАТ АРТА НА СЕГОДНЯ:
{art_directive}
Во всех остальных режимах не заполняй лишние поля. Держи код компактным.

НЕДАВНИЕ открытки (НЕ повторяй их настроение/палитру/шрифт/анимацию): {recent_ctx}

Ответ верни СТРОГО в формате JSON без markdown:
{{"rhyme":"...","mood":"...","palette":["#......","#......","#......"],"style":"bloom","art":"petals","font":"playfair","anim":"cascade","verse":["строка1","строка2"],"concept":"...","svg":"<svg viewBox=\\"0 0 1000 1000\\" xmlns=\\"http://www.w3.org/2000/svg\\">...</svg>","scene":""}}
"""

    # --- Отдельный промпт для Claude: полная творческая свобода в рамках контракта фронтенда ---
    claude_prompt = f"""Ты — художник и поэт, который каждый день делает для девушки Юлечки «открытку дня»:
живую страницу с ласковым словом-рифмой, двустишием и генеративным артом. Это признание
в любви языком искусства. Сегодняшняя открытка должна УДИВЛЯТЬ — быть маленьким
произведением, которое хочется рассматривать, а не «узором на фоне». У тебя полная
творческая свобода в рамках технического контракта ниже. Не будь осторожным — будь смелым.

════ ПОРЯДОК ТВОРЧЕСТВА (строго в этой последовательности) ════

1) РИФМА (поле "rhyme") — одно новое ласковое слово-рифма к имени «Юлечка», идеально
   звучащее во фразе «Юлечка-[слово]». Не длиннее 12 букв.
   КАК ПРИДУМЫВАТЬ: сначала мысленно набросай 6–8 кандидатов от РАЗНЫХ позитивных
   корней (красота, нежность, солнце, ласка, сладость, очарование, уют, мечта,
   звёзды, весна, счастье, чудо…) и отбрось слабых. Критерии отбора:
   - МОРФОЛОГИЯ: узнаваемый ЦЕЛЫЙ корень + «-улечка/-юлечка». Убери суффикс — остаток
     должен мгновенно читаться как исходное слово («красот-» → красота, «сладу-» →
     сладость). Если корень обрублен до неузнаваемости — кандидат отпадает.
   - ТЕСТ ВСЛУХ: так могла бы ласково назвать любимую живая бабушка или влюблённый —
     без запинки, без смеха, без случайных неприятных созвучий внутри слова?
   ПЛОХИЕ примеры (НЕ делай так): «пламулечка» (корень «плам-» обрублен и груб),
   «обаянулечка» (слышится «баян»), «фейерверкулечка» (длинно и технично).
   ХОРОШИЕ по форме: «красотулечка», «симпатюлечка», «лапулечка», «сладулечка» —
   но эти УЖЕ БЫЛИ, нужен новый. Верни только лучшего кандидата.
   УЖЕ БЫЛИ (не повторяй): {json.dumps(history, ensure_ascii=False)}

2) НАСТРОЕНИЕ (поле "mood", 1-2 слова) — весь спектр чувства: нежное, страстное, игривое,
   мечтательное, искрящееся, озорное, томное, трепетное, умиротворённое… Выбери оттенок,
   ЗАМЕТНО отличный от недавних (см. НЕДАВНИЕ ОТКРЫТКИ ниже).

3) ДВУСТИШИЕ (поле "verse", ровно 2 строки) — тёплое, с безупречной грамматикой,
   чётким ритмом (выдержи стихотворный размер!) и СВЕЖЕЙ рифмой. Ты умеешь писать
   настоящие стихи — никаких банальностей и вымученных конструкций.
   - Фраза «Юлечка-[твоя рифма]» входит ровно ОДИН раз, органично.
   - ЛУЧШИЙ приём: поставь её ВНУТРИ строки, а строки рифмуй любой свежей парой слов.
   - ЗАПРЕЩЕНО рифмовать слово само с собой и использовать «шкатулочка» в любом виде.
   - ЗАПРЕЩЁННЫЕ концевые слова строк (уже были): {json.dumps(banned_end_words, ensure_ascii=False)}
   - ПРОШЛЫЕ двустишия — не повторяй их образы и обороты: {past_verses_ctx}

4) КОНЦЕПЦИЯ АРТА (поле "concept", одна фраза) — перечитай своё двустишие, возьми его
   центральный образ и придумай художественную интерпретацию уровня арт-принта.
   Каждый день — новый художественный язык: рисунок одной линией, укиё-э, ар-деко,
   витраж, ботаническая гравюра, пуантилизм, баухаус, муар, бумажные слои, каллиграфия,
   биолюминесценция, неон в тумане, созвездие с историей… — или придумай своё.
   ЗАПРЕЩЕНО повторять прошлые концепции: {json.dumps(recent_concepts, ensure_ascii=False)}
   СТРОГО ЗАПРЕЩЕНЫ образы с траурными или печальными ассоциациями: свечи и их пламя,
   венки, кресты, увядшие/опадающие цветы, гаснущий или одинокий огонёк, плакучие ивы,
   вороны, всё «поминальное». Если образ можно прочитать как скорбь — выбери другой.
   Открытка только про жизнь, любовь и радость.

5) ОФОРМЛЕНИЕ — под настроение и концепцию, заметно отличное от недавних открыток:
   - "palette": ровно 3 изысканных цвета HEX #RRGGBB;
   - "style" (фоновый градиент) из: aurora, mesh, dawn, dusk, bloom, frost;
   - "art" (запасной мотив) из: constellation, petals, waves, orbits, lattice, rays;
   - "font" из: playfair (драм. сериф), yeseva (изысканный), prata (тонкий дидон),
     philosopher (чистый), marck (рукописный), caveat (лёгкий рукописный),
     pacifico (весёлый), lobster (ретро), comfortaa (округлый), unbounded (смелый);
   - "anim" (появление слова) из: cascade, fade, blur, scale, drop, glow, wave.

6) АРТ — воплоти концепцию. {art_directive}
   Зритель должен УЗНАТЬ образ из стиха и удивиться. Бюджет кода большой — трать его
   на красоту. Смелая композиция: асимметрия, диагональ, крупный образ, сцена по краям.
   ЕДИНСТВЕННЫЙ закон композиции: центр экрана спокоен и малоконтрастен — там живёт
   слово дня. Фон всегда прозрачный, БЕЗ текста, движение медленное и созерцательное.

   ЕСЛИ SVG (поле "svg", до ~50 000 символов):
   - цельный валидный <svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg">;
   - сотни элементов не проблема; <defs>, <use href="#id">, локальные градиенты
     и <filter> (feGaussianBlur — свечение, feTurbulence — фактура) разрешены;
   - ЗАПРЕЩЕНО: <script>, <style>, <text>, растровые картинки, внешние ссылки,
     сплошной фоновый прямоугольник;
   - цвета — из твоей палитры (плюс прозрачности); линии любой толщины, заливки
     с fill-opacity, штриховка, точки;
   - ОЖИВИ встроенной SMIL-анимацией (НИКАКОГО JavaScript). Хореография из нескольких
     слоёв с разными периодами гипнотизирует. Разрешено анимировать ТОЛЬКО
     transform / opacity / stroke-* / fill-opacity и геометрические атрибуты.
     Эффектные приёмы: «самопрорисовка» контура (stroke-dasharray = длина штриха,
     анимируй stroke-dashoffset к нулю), <animateMotion> с локальным path,
     медленное вращение (dur 30–120s, from="0 500 500" to="360 500 500"),
     мерцание с разными begin. Движение НЕ должно отвлекать от слова.

   ЕСЛИ ЖИВАЯ СЦЕНА (поле "scene", до ~25 000 символов) — самодостаточный JS для canvas
   в изолированной песочнице (без DOM вокруг, без сети). Уже доступны переменные:
   ctx (2D-контекст), W() и H() (размеры в CSS-пикселях), PALETTE (массив hex),
   MOOD (строка), DARK (булево). Не объявляй свои ctx/canvas/PALETTE/W/H.
   Полноценные генеративные техники приветствуются: поле потоков на value-noise,
   системы из сотен частиц со шлейфами (шлейф — массив прошлых точек, НЕ полупрозрачная
   заливка всего холста!), слои с параллаксом, орбиты, пружины, кривые Безье,
   createRadialGradient, умеренный shadowBlur. Анимируй через requestAnimationFrame.
   Держи 60 fps на телефоне: до ~600 частиц, без тяжёлых вычислений в кадре.
   НЕ заливай весь холст непрозрачным цветом — фон страницы должен просвечивать.

НЕДАВНИЕ ОТКРЫТКИ (не повторяй их настроение/палитру/шрифт/анимацию): {recent_ctx}

ОТВЕТ: верни СТРОГО один JSON-объект без markdown и пояснений, со ВСЕМИ полями:
{{"rhyme":"...","mood":"...","palette":["#......","#......","#......"],"style":"...","art":"...","font":"...","anim":"...","verse":["строка1","строка2"],"concept":"...","svg":"...","scene":""}}
Дополнительно верни строковое поле "image_prompt".
ФОРМАТ АРТА НА СЕГОДНЯ:
{art_directive}"""

    calendar_lock = f"""

{calendar_ctx}
Календарь не обязан быть темой оформления, но концепция и арт также не должны противоречить дате.
"""
    poem_lock = f"""

ВАЖНО: рифма и двустишие уже написаны отдельной поэтической моделью.
Используй их ДОСЛОВНО, не исправляй и не заменяй; создавай настроение, концепцию и арт по их образам.
Поле "rhyme": {json.dumps(poem["rhyme"], ensure_ascii=False)}
Поле "verse": {json.dumps(poem["verse"], ensure_ascii=False)}
"""
    prompt += calendar_lock + poem_lock
    claude_prompt += calendar_lock + poem_lock

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
                    "anim":      {"type": "string", "enum": ALLOWED_ANIMS},
                    "verse":     {"type": "array", "items": {"type": "string"}},
                    "concept":   {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "svg":       {"type": "string"},
                    "scene":     {"type": "string"},
                },
                "required": ["rhyme", "mood", "palette", "style", "art", "font", "anim", "verse", "concept", "image_prompt"],
                # Порядок генерации важен: сначала стих, из него — концепция, из неё — арт
                "propertyOrdering": ["rhyme", "mood", "palette", "style", "art", "font", "anim",
                                     "verse", "concept", "image_prompt", "svg", "scene"],
            },
        },
    }

    # 3. Запрос: Claude Sonnet 5 через OpenRouter (если есть ключ), иначе/при неудаче — Gemini
    result = None
    if OPENROUTER_API_KEY:
        log("Провайдер: Claude (Sonnet 5) через OpenRouter; Gemini — запасной.")
        # у Claude свой промпт (полное творческое ТЗ) и запас токенов/времени под сложный арт
        result = call_openrouter(claude_prompt, max_tokens=24000, timeout=240)
        if result is None:
            log("OpenRouter не ответил — откат на Gemini.")
    else:
        log("OPENROUTER_API_KEY не задан — работаем через Gemini.")
    if result is None:
        result = call_gemini(payload)
    if result is None:
        log("Все модели недоступны (лимит/перегрузка). data.json не трогаю — сайт покажет прошлую открытку.")
        sys.exit(0)

    # Даже если арт-модель не выполнила инструкцию, текст выбранного поэтического
    # провайдера остаётся неизменным.
    result["rhyme"] = poem["rhyme"]
    result["verse"] = poem["verse"]

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

    # Двустишие для показа (verse) и для озвучки с ударениями (verse_tts, «+» перед ударной гласной)
    verse = [str(s).strip() for s in (result.get("verse") or []) if str(s).strip()]
    if not verse:
        verse = [f"Юлечка-{new_rhyme},", "самая любимая на свете."]
    verse = verse[:4]
    log(f"Рифма: Юлечка-{new_rhyme} | настроение: {mood}")
    verse_tts = fix_verse_tts(verse, new_rhyme)          # ударения ставим САМИ (Юлечка + рифма)
    log("Ударения (verse_tts): " + " / ".join(verse_tts))

    # SVG: базовая проверка; финально чистит фронтенд. Если плох — "", страница откатится на мотив.
    svg = (result.get("svg") or "").strip()
    low = svg.lower()
    bad = "<script" in low or "</style" in low or "foreignobject" in low or "<iframe" in low
    if not (low.startswith("<svg") and "</svg>" in low) or bad or len(svg) > 80000:
        svg = ""

    # SCENE: JS-сцена. Выполняется в песочнице (sandbox+CSP) на фронте — здесь только лимит размера.
    scene = (result.get("scene") or "").strip()
    if len(scene) > SCENE_MAX:
        scene = ""

    concept = (result.get("concept") or "").strip()[:200]

    # Image и video начинают с отдельной вертикальной иллюстрации. Для video второй
    # шаг workflow опубликует этот кадр и аккуратно оживит его через Seedance.
    # Файл именуется датой, поэтому старые открытки продолжают показывать свой фон из архива.
    image_path = ""
    if art_mode_today in {"image", "video"}:
        model_prompt = (result.get("image_prompt") or "").strip()
        if not model_prompt:
            model_prompt = f"Художественная иллюстрация: {concept}. Настроение: {mood}."
        final_image_prompt = f"""{model_prompt}

Создай премиальную вертикальную иллюстрацию-фон для любовной открытки.
Смысл двустишия: {json.dumps(verse, ensure_ascii=False)}.
Палитра: {', '.join(palette)}. Композиция 9:16, адаптивная под телефон и широкий экран:
главные детали находятся в верхней/нижней трети и ближе к краям; центральные 45% изображения
спокойные, мягкие и малоконтрастные, потому что поверх будет крупная надпись.
Без текста, букв, цифр, рамки, интерфейса, логотипов и водяных знаков. Никаких траурных образов,
свечей, венков, крестов, увядания или печали. Живо, радостно, изысканно, атмосферно.
Изображение должно хорошо переносить object-fit: cover без потери главного образа."""
        candidate_path = os.path.join("art", f"{today_str}.webp")
        if generate_background_image(final_image_prompt, candidate_path):
            image_path = candidate_path.replace(os.sep, "/")

    card = {
        "rhyme": new_rhyme,
        "mood": mood,
        "concept": concept,
        "palette": palette,
        "style": style,
        "art": art,
        "font": font,
        "anim": anim,
        "verse": verse,
        "verse_tts": verse_tts,
        "image": image_path,
        "video": "",
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

    # 7. Архив открыток (без тяжёлого svg/scene); пути к медиофонам сохраняем.
    archive.append({k: card[k] for k in ("date", "rhyme", "mood", "concept", "palette", "style", "art", "font", "anim", "verse", "image", "video")})
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    if art_mode_today == "video" and image_path:
        art_src = "OpenRouter-Image→Seedance-video"
    else:
        art_src = "OpenRouter-Image+layers" if image_path else ("scene-JS" if scene else ("Gemini-SVG" if svg else f"параметрика:{art}"))
    log(f"Готово: Юлечка-{new_rhyme} | {mood} | стиль:{style} | арт:{art_src} | шрифт:{font} | аним:{anim} | {palette}")
    log(f"Концепция арта: {concept or '—'}")
    log("Двустишие: " + " / ".join(verse))
    log("Генератор завершён. Аудио — отдельным шагом (voice.py).")

    # 8. Озвучка вынесена в voice.py (Chatterbox — твой голос, с откатом на edge-tts).
    #    Воркфлоу запускает её отдельным шагом: python voice.py


if __name__ == "__main__":
    main()
