import requests


def send_post(token, channel, text, photos):
    base = f"https://api.telegram.org/bot{token}"

    media = []

    for i, url in enumerate(photos):
        media.append({
            "type": "photo",
            "media": url
        })

    # если есть фото → media group
    if media:
        # первый элемент может содержать caption
        media[0]["caption"] = text if text else ""

        r = requests.post(base + "/sendMediaGroup", json={
            "chat_id": channel,
            "media": media
        })

        if not r.ok:
            print("TG ERROR:", r.text)

        return

    # если нет фото → просто текст
    if text:
        r = requests.post(base + "/sendMessage", data={
            "chat_id": channel,
            "text": text
        })

        if not r.ok:
            print("TG ERROR:", r.text)
