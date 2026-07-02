"""
Пуш-уведомление об открытке дня (запускается GitHub Actions в 12:00 МСК).

Читает подписки из subscriptions.json (их кладёт туда владелец сайта — код подписки
приходит с телефона через кнопку-колокольчик на странице) и шлёт Web Push
с рифмой и двустишием дня из data.json.

Приватный VAPID-ключ приходит из секрета VAPID_PRIVATE_KEY (PEM).
Умершие подписки (HTTP 404/410 — приложение удалили или отозвали разрешение)
вычищаются из subscriptions.json; воркфлоу коммитит файл обратно.
"""

import json
import os
import sys

from pywebpush import webpush, WebPushException

VAPID_CLAIMS = {"sub": "mailto:idslash@gmail.com"}
KEY_FILE = "vapid_private.pem"


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    subs = load("subscriptions.json", [])
    if not isinstance(subs, list) or not subs:
        print("Подписок нет — слать некому. Добавь код подписки в subscriptions.json.")
        return

    key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not key:
        print("Нет секрета VAPID_PRIVATE_KEY — выходим.")
        sys.exit(1)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key + "\n")

    data = load("data.json", {})
    rhyme = (data.get("rhyme") or "").strip()
    verse = [str(s).strip() for s in (data.get("verse") or []) if str(s).strip()]
    payload = json.dumps({
        "title": f"Юлечка-{rhyme} 💌" if rhyme else "Для Юлечки 💌",
        "body": " ".join(verse) or "Новая открытка дня ждёт тебя",
        "url": "./",
    }, ensure_ascii=False)

    alive, sent = [], 0
    for s in subs:
        endpoint = (s or {}).get("endpoint", "")[:60]
        try:
            webpush(
                subscription_info=s,
                data=payload,
                vapid_private_key=KEY_FILE,
                vapid_claims=dict(VAPID_CLAIMS),  # pywebpush дополняет claims — даём копию
                ttl=43200,
            )
            alive.append(s)
            sent += 1
            print(f"OK   {endpoint}…")
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                print(f"DEAD {endpoint}… (HTTP {code}) — удаляю подписку")
            else:
                alive.append(s)  # временная ошибка — подписку сохраняем
                print(f"FAIL {endpoint}… (HTTP {code}): {e}")

    if alive != subs:
        with open("subscriptions.json", "w", encoding="utf-8") as f:
            json.dump(alive, f, ensure_ascii=False, indent=2)
        print("subscriptions.json обновлён (вычищены умершие).")

    os.remove(KEY_FILE)
    print(f"Отправлено: {sent}/{len(subs)}")


if __name__ == "__main__":
    main()
