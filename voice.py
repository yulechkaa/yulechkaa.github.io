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
import json
import subprocess

REF = "voice_ref.wav"          # твой образец голоса (закоммить рядом)
OUT = "audio.mp3"
LANG = "ru"


def read_text():
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "Юлечка, самая любимая."
    verse = data.get("verse")
    if isinstance(verse, list) and verse:
        return " ".join(str(s).strip() for s in verse if str(s).strip())
    rhyme = (data.get("rhyme") or "").strip()
    return f"Юлечка-{rhyme}." if rhyme else "Юлечка, самая любимая."


def to_mp3(wav_path):
    """Конвертируем wav -> mp3 через ffmpeg; если ffmpeg нет — оставляем wav как audio.* ."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2", OUT],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
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
        wav = model.generate(text, language_id=LANG, audio_prompt_path=REF)
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
