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
ART_MODE = "auto"  # "auto" — чередовать svg/scene по дням; "svg" — всегда SVG; "scene" — всегда сцена

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
        out.append("".join(toks))
    return out


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


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


def proofread_verse(verse, rhyme, banned=()):
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
        if OPENROUTER_API_KEY:
            res = call_openrouter(prompt, max_tokens=1024, attempts=1,
                                  models=[CLAUDE_PROOFREAD_MODEL], timeout=30)
        if res is None:
            res = call_gemini(payload, timeout=25, attempts=1, models=["gemini-2.5-flash-lite"]) or {}
        v = [str(s).strip() for s in (res.get("verse") or []) if str(s).strip()]
        if len(v) >= 2:
            return v[:4]
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

    # Концепции прошлых артов — чтобы каждый день был новый художественный замысел
    recent_concepts = [r["concept"] for r in archive if r.get("concept")][-10:]

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

ВАЖНО ПРО РАЗМЕР ОТВЕТА: дай ТОЛЬКО ОДНО из двух — либо "svg" (п.10), либо "scene" (п.11).
{art_directive}
ВТОРОЕ поле оставь ПУСТОЙ строкой "". НЕ заполняй оба сразу — это перегружает ответ. Держи код компактным.

НЕДАВНИЕ открытки (НЕ повторяй их настроение/палитру/шрифт/анимацию): {recent_ctx}

Ответ верни СТРОГО в формате JSON без markdown:
{{"rhyme":"...","mood":"...","palette":["#......","#......","#......"],"style":"bloom","art":"petals","font":"playfair","anim":"cascade","verse":["строка1","строка2"],"concept":"...","svg":"<svg viewBox=\\"0 0 1000 1000\\" xmlns=\\"http://www.w3.org/2000/svg\\">...</svg>","scene":""}}
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
                    "anim":      {"type": "string", "enum": ALLOWED_ANIMS},
                    "verse":     {"type": "array", "items": {"type": "string"}},
                    "concept":   {"type": "string"},
                    "svg":       {"type": "string"},
                    "scene":     {"type": "string"},
                },
                "required": ["rhyme", "mood", "palette", "style", "art", "font", "anim", "verse", "concept"],
                # Порядок генерации важен: сначала стих, из него — концепция, из неё — арт
                "propertyOrdering": ["rhyme", "mood", "palette", "style", "art", "font", "anim",
                                     "verse", "concept", "svg", "scene"],
            },
        },
    }

    # 3. Запрос: Claude Sonnet 5 через OpenRouter (если есть ключ), иначе/при неудаче — Gemini
    result = None
    if OPENROUTER_API_KEY:
        log("Провайдер: Claude (Sonnet 5) через OpenRouter; Gemini — запасной.")
        result = call_openrouter(prompt)
        if result is None:
            log("OpenRouter не ответил — откат на Gemini.")
    else:
        log("OPENROUTER_API_KEY не задан — работаем через Gemini.")
    if result is None:
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

    # Двустишие для показа (verse) и для озвучки с ударениями (verse_tts, «+» перед ударной гласной)
    verse = [str(s).strip() for s in (result.get("verse") or []) if str(s).strip()]
    if not verse:
        verse = [f"Юлечка-{new_rhyme},", "самая любимая на свете."]
    verse = verse[:4]
    log(f"Рифма: Юлечка-{new_rhyme} | настроение: {mood}")
    log("Корректор двустишия (лёгкая модель)…")
    verse = proofread_verse(verse, new_rhyme, banned_end_words)  # грамматика + защита от само-рифмы и повторов
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
    if len(scene) > 16000:
        scene = ""

    # Дата всегда по Москве: раннеры живут в UTC, а cron может опоздать на часы —
    # без явной зоны открытка около полуночи получала бы соседнюю дату
    try:
        from zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
    except Exception:
        today_str = datetime.now().strftime("%Y-%m-%d")

    concept = (result.get("concept") or "").strip()[:200]

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
    archive.append({k: card[k] for k in ("date", "rhyme", "mood", "concept", "palette", "style", "art", "font", "anim", "verse")})
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    art_src = "scene-JS" if scene else ("Gemini-SVG" if svg else f"параметрика:{art}")
    log(f"Готово: Юлечка-{new_rhyme} | {mood} | стиль:{style} | арт:{art_src} | шрифт:{font} | аним:{anim} | {palette}")
    log(f"Концепция арта: {concept or '—'}")
    log("Двустишие: " + " / ".join(verse))
    log("Генератор завершён. Аудио — отдельным шагом (voice.py).")

    # 8. Озвучка вынесена в voice.py (Chatterbox — твой голос, с откатом на edge-tts).
    #    Воркфлоу запускает её отдельным шагом: python voice.py


if __name__ == "__main__":
    main()
