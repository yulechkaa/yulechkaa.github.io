# Yulechka Daily Card

## Настройки генерации

Поэтическая часть (ласковая рифма и двустишие) генерируется отдельно от оформления и арта.
Провайдер выбирается переменной GitHub Actions `VERSE_PROVIDER`:

- `gemini` — только Gemini (значение по умолчанию);
- `openrouter` — только Claude через OpenRouter;
- `auto` — сначала Claude через OpenRouter, при неудаче Gemini.

Переменную можно задать в репозитории: **Settings → Secrets and variables → Actions → Variables**.
