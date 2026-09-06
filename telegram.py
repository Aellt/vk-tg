import requests


def send_post(token, channel, text, photos):
    base = f"https://api.telegram.org/bot{token}"

    files = {}
    media = []

    for i, url in enumerate(photos):
        try:
            image = requests.get(url, timeout=30)

            if not image.ok:
                print(
                    f"VK IMAGE ERROR #{i}: "
                    f"{image.status_code} {image.text[:200]}"
                )
                return False

            file_key = f"photo{i}"

            files[file_key] = (
                f"photo{i}.jpg",
                image.content,
                image.headers.get("Content-Type", "image/jpeg")
            )

            media.append({
                "type": "photo",
                "media": f"attach://{file_key}"
            })

        except requests.RequestException as e:
            print(f"VK IMAGE DOWNLOAD ERROR #{i}:", e)
            return False

    if media:
        if text:
            media[0]["caption"] = text

        r = requests.post(
            base + "/sendMediaGroup",
            data={
                "chat_id": channel,
                "media": __import__("json").dumps(media)
            },
            files=files,
            timeout=60
        )

        if not r.ok:
            print("TG ERROR:", r.text)
            return False

        print("TG OK")
        return True

    if text:
        r = requests.post(
            base + "/sendMessage",
            data={
                "chat_id": channel,
                "text": text
            },
            timeout=30
        )

        if not r.ok:
            print("TG ERROR:", r.text)
            return False

        print("TG OK")
        return True

    print("NOTHING TO SEND")
    return False
