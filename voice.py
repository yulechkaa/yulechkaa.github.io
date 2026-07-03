"""
Озвучка двустишия дня ТВОИМ голосом через Chatterbox Multilingual (русский).

Как работает:
  1. Берёт текст из data.json (поле "verse" — двустишие; иначе "Юлечка-<rhyme>").
  2. Если рядом есть voice_ref.wav (твой образец 10–20 c) и установлен chatterbox-tts —
     клонирует твой голос и пишет audio.mp3.
  3. Если чего-то не хватает — мягкий откат на edge-tts (голос Светланы), чтобы аудио всё равно было.

Зависимости для клонирования (ставятся в воркфлоу):
  pip install chatterbox-tts torch torchaudio soundfile
Плюс системный ffmpeg (для конвертации wav -> mp3).
"""

import os
import sys
import re
import json
import subprocess

REF = "voice_ref.wav"          # твой образец голоса (закоммить рядом)
OUT = "audio.mp3"
LANG = "ru"

# --- Подача. Пресет «похожесть-first» (ближе к твоему голосу) ---
# exaggeration: эмоция (0.25–2.0). НИЖЕ = ближе к оригиналу; выше = ярче, но тембр «уплывает».
# cfg_weight:   манера/темп (0.2–1.0). НИЖЕ = ближе к клону и медленнее.
# temperature:  вариативность (0.05–5.0). НИЖЕ = стабильнее, меньше уходит от голоса.
# Хочешь выразительнее (ценой похожести) — подними exaggeration к 0.7.
EXAGGERATION = 0.5
CFG_WEIGHT = 0.3
TEMPERATURE = 0.7
# Доп. замедление готового аудио через ffmpeg (1.0 = выкл; 0.92 = на ~8% медленнее, без изменения тона)
SPEED = 1.0
# Подавать ли явные ударения (U+0301 из verse_tts). Если на слух хуже — поставь False (сравнить).
USE_STRESS = True


VOW = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"


def marks_to_acute(text):
    """Любые пометки ударения → U+0301: «+» ПЕРЕД гласной и «'» ПОСЛЕ гласной."""
    text = re.sub(r"\+([" + VOW + r"])", "\\1́", text)
    text = re.sub(r"([" + VOW + r"])'", "\\1́", text)
    # Страховка: уцелевший «+» (не перед гласной, задвоенная метка и т.п.) TTS
    # читает вслух как «плюс» — вычищаем всё, что не сконвертировалось
    return text.replace("+", "")


def _stress_rhyme(rhyme):
    """«+» перед ударной гласной рифмы по паттерну «…Vлечка/лочка» (слад-У-лечка)."""
    m = re.search(r"([аеёиоуыэюя])(л[еоа]чк)", rhyme.lower())
    return rhyme[:m.start(1)] + "+" + rhyme[m.start(1):] if m else rhyme


# Ручные исключения: ruaccent путает омографы, а в наших стихах контекст почти всегда один
# («дарит теплом» — творительный от «тепло», а не «в тёплом»). Пополнять по мере находок.
STRESS_OVERRIDES = {
    "теплом": "тепл+ом",
    "добром": "добр+ом",
    "серебром": "серебр+ом",
}


def _override_phrase(line, rhyme):
    """В уже размеченной строке ставим НАШИ ударения в «Юлечка», в самой рифме
    (даже хороший стрессер ошибается — слово выдуманное) и в словах-исключениях."""
    sr = _stress_rhyme(rhyme)
    rl = rhyme.lower()
    toks = re.split(r"(\s+)", line)
    for i, tok in enumerate(toks):
        if not tok.strip():
            continue
        sub = tok.split("-")
        for j, sp in enumerate(sub):
            m = re.match(r"^([^\w]*)(.*?)([^\w]*)$", sp, re.S)
            pre, core, post = m.group(1), m.group(2), m.group(3)
            low = core.replace("+", "").replace("'", "").replace("́", "").lower()
            if low in ("юлечка", rl) or low in STRESS_OVERRIDES:
                # ruaccent мог уже поставить метку ПЕРЕД словом («+юлечка» — ударная
                # первая гласная), и она попадает в pre. Перекрываем своим ударением —
                # чужие метки вычищаем, иначе получится «++Юлечка» и TTS скажет «плюс»
                strip = lambda s: s.replace("+", "").replace("'", "").replace("́", "")
                pre, post = strip(pre), strip(post)
            if low == "юлечка":
                core = "+Юлечка"
            elif low == rl:
                core = sr
            elif low in STRESS_OVERRIDES:
                fixed = STRESS_OVERRIDES[low]
                if core[:1].isupper():
                    k = 1 if fixed.startswith("+") else 0
                    fixed = fixed[:k] + fixed[k].upper() + fixed[k + 1:]
                core = fixed
            sub[j] = pre + core + post
        toks[i] = "-".join(sub)
    return "".join(toks)


def _patch_onnx_ttids():
    """Чиним ошибку ruaccent 'token_type_ids missing': подкладываем нули, если модель их просит."""
    try:
        import numpy as np
        import onnxruntime as ort
        if getattr(ort.InferenceSession, "_ttids_patched", False):
            return
        orig = ort.InferenceSession.run

        def run(self, output_names, input_feed, run_options=None):
            try:
                need = {i.name for i in self.get_inputs()}
                if "token_type_ids" in need and "token_type_ids" not in input_feed and "input_ids" in input_feed:
                    input_feed = dict(input_feed)
                    input_feed["token_type_ids"] = np.zeros_like(input_feed["input_ids"])
            except Exception:
                pass
            return orig(self, output_names, input_feed, run_options)

        ort.InferenceSession.run = run
        ort.InferenceSession._ttids_patched = True
    except Exception:
        pass


_ACC = None


def _ruaccent_lines(verse, rhyme):
    """Ударения во ВСЕХ словах через ruaccent, затем перекрываем «Юлечка»+рифму нашими."""
    global _ACC
    if _ACC is None:
        _patch_onnx_ttids()
        from ruaccent import RUAccent
        acc = RUAccent()
        # Омографы («теплом», «замок»…) turbo решает плохо — берём модель посильнее,
        # с откатом на turbo, если в установленной версии её нет
        err = None
        for size in ("turbo3.1", "turbo2", "turbo"):
            try:
                acc.load(omograph_model_size=size, use_dictionary=True)
                print(f"ruaccent: омограф-модель «{size}».")
                break
            except Exception as e:
                err = e
        else:
            raise err
        _ACC = acc
    return [_override_phrase(_ACC.process_all(l), rhyme) for l in verse]


def read_text():
    """Текст для синтеза с ударениями. Приоритет:
    1) ruaccent (все слова) + наше правило для «Юлечка/рифмы»;
    2) verse_tts из data.json (помечены только «Юлечка» и рифма);
    3) обычный verse без ударений."""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "Юлечка, самая любимая."

    verse = [str(s).strip() for s in (data.get("verse") or []) if str(s).strip()]
    rhyme = (data.get("rhyme") or "").strip()

    if not USE_STRESS:
        return " ".join(verse) if verse else (f"Юлечка-{rhyme}." if rhyme else "Юлечка, самая любимая.")

    # 1) ruaccent — ударения на все слова
    if verse:
        try:
            lines = _ruaccent_lines(verse, rhyme)
            print("Ударения: ruaccent (все слова) + правило для рифмы.")
            return marks_to_acute(" ".join(lines))
        except Exception as e:
            print(f"ruaccent недоступен ({e}); ставлю ударения только на «Юлечка» и рифму.")

    # 2) verse_tts (помечены только Юлечка+рифма)
    vt = [str(s).strip() for s in (data.get("verse_tts") or []) if str(s).strip()]
    if vt:
        return marks_to_acute(" ".join(vt))
    if verse:
        return marks_to_acute(" ".join(_override_phrase(l, rhyme) for l in verse))
    return f"Юлечка-{rhyme}." if rhyme else "Юлечка, самая любимая."


def to_mp3(wav_path):
    """Конвертируем wav -> mp3 через ffmpeg; если ffmpeg нет — оставляем wav как audio.* .
    При SPEED != 1.0 дополнительно меняем темп (atempo) без изменения высоты тона."""
    try:
        args = ["ffmpeg", "-y", "-i", wav_path]
        if abs(SPEED - 1.0) > 1e-3:
            args += ["-filter:a", f"atempo={SPEED}"]
        args += ["-codec:a", "libmp3lame", "-qscale:a", "2", OUT]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(wav_path)
        return True
    except Exception as e:
        print(f"ffmpeg недоступен ({e}); оставляю {wav_path}")
        return False


def try_chatterbox(text):
    """Клонируем твой голос. Возвращает True при успехе."""
    if not os.path.exists(REF):
        print(f"Нет {REF} — пропускаю Chatterbox (нужен образец голоса).")
        return False
    try:
        import torch  # noqa: F401
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except Exception as e:
        print(f"chatterbox-tts недоступен ({e}) — откат на edge-tts.")
        return False

    try:
        import torchaudio
        device = "cuda" if _cuda_available() else "cpu"
        print(f"Chatterbox: устройство={device}, язык={LANG}")
        model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        spoken = text   # ударения уже проставлены в read_text() (из verse_tts)
        kw = dict(language_id=LANG, audio_prompt_path=REF,
                  exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT, temperature=TEMPERATURE)
        print(f"Подача: exaggeration={EXAGGERATION}, cfg_weight={CFG_WEIGHT}, temperature={TEMPERATURE}")
        try:
            wav = model.generate(spoken, **kw)
        except TypeError:
            # старая версия модели без этих параметров — синтез с дефолтами
            print("Версия Chatterbox без параметров подачи — генерирую с дефолтами.")
            wav = model.generate(spoken, language_id=LANG, audio_prompt_path=REF)
        tmp = "audio_tmp.wav"
        torchaudio.save(tmp, wav, model.sr)
        if not to_mp3(tmp):
            os.replace(tmp, "audio.wav")
        print("Готово: озвучено твоим голосом (Chatterbox).")
        return True
    except Exception as e:
        print(f"Chatterbox упал ({e}) — откат на edge-tts.")
        return False


def _cuda_available():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def try_edge(text):
    """Запасной голос (бесплатный, без клонирования)."""
    try:
        subprocess.run(
            ["edge-tts", "--voice", "ru-RU-SvetlanaNeural", "--text", text, "--write-media", OUT],
            check=True,
        )
        print("Готово: озвучено через edge-tts (запасной голос).")
        return True
    except Exception as e:
        print(f"edge-tts тоже не сработал ({e}); audio.mp3 не обновлён.")
        return False


def main():
    text = read_text()
    print("Текст озвучки:", text)
    if try_chatterbox(text):
        return
    if try_edge(text):
        return
    # Совсем ничего не вышло — не валим деплой (останется прошлый audio.mp3)
    sys.exit(0)


if __name__ == "__main__":
    main()
