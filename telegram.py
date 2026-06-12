import requests


def send_post(token, channel, text, photos):
    if photos:
        media = []

        for i, url in enumerate(photos):
            media.append({
                "type": "photo",
                "media": url,
                "caption": text if i == 0 else ""
            })

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMediaGroup",
            json={
                "chat_id": channel,
                "media": media
            }
        )
    else:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": channel,
                "text": text
            }
        )
