# Yulechka Daily Card

## Настройки генерации

Поэтическая часть (ласковая рифма и двустишие) генерируется отдельно от оформления и арта.
Провайдер выбирается переменной GitHub Actions `VERSE_PROVIDER`:

- `gemini` — только Gemini (значение по умолчанию);
- `openrouter` — только Claude через OpenRouter;
- `auto` — сначала Claude через OpenRouter, при неудаче Gemini.

Переменную можно задать в репозитории: **Settings → Secrets and variables → Actions → Variables**.

### Режим арта

Переменная `ART_MODE`:

- `auto` — чередовать `scene`, `svg` и `image` (по умолчанию);
- `svg` — генеративный SVG;
- `scene` — живая canvas-сцена;
- `image` — вертикальная AI-иллюстрация с адаптивным кадрированием и анимированными слоями.

Для `image` используется OpenRouter Images API и модель из переменной `IMAGE_MODEL`
(`google/gemini-3.1-flash-image` по умолчанию). Нужен секрет `OPENROUTER_API_KEY`.
Если генерация изображения недоступна,
открытка остаётся рабочей и показывает градиент с живым слоем.
