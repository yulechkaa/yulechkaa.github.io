import os
import json
import requests
import subprocess
from datetime import datetime

# Настройки

API_KEY = os.environ.get("GEMINI_API_KEY")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

def main():
    # 1. Загружаем историю
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    
    # 2. Формируем промпт для LLM
    prompt = f"""
    Придумай ОДНО новое, милое, забавное или ласковое слово-рифму к имени "Юлечка" (например: красотулечка, симпатюлечка, капризулечка).
    Это должно быть полноценное слово или составное слово через дефис, которое идеально звучит во фразе "Юлечка-[твое слово]".
    Критически важно: НЕ ИСПОЛЬЗУЙ слова из этого списка прошлых генераций: {json.dumps(history, ensure_ascii=False)}.
    Ответ верни строго в формате JSON: {{"rhyme": "слово"}} без какого-либо разметки markdown.
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    # 3. Запрос к бесплатному API
    response = requests.post(URL, json=payload)
    response_data = response.json()
    
    # Парсим ответ
    text_response = response_data['candidates'][0]['content']['parts'][0]['text']
    result = json.loads(text_response)
    new_rhyme = result['rhyme'].strip().lower()
    
    # 4. Обновляем файлы данных
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"rhyme": new_rhyme, "date": today_str}, f, ensure_ascii=False, indent=2)
        
    history.append(new_rhyme)
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        
    print(f"Сгенерирована новая рифма: Юлечка-{new_rhyme}")
    
    # 5. Генерация аудио (используем отличный женский голос Светланы)
    full_text = f"Юлечка {new_rhyme}"
    audio_cmd = f"edge-tts --voice ru-RU-SvetlanaNeural --text \"{full_text}\" --write-media audio.mp3"
    subprocess.run(audio_cmd, shell=True, check=True)

if __name__ == "__main__":
    main()