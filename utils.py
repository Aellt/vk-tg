from datetime import datetime


def extract_photos(post):
    photos = []

    for a in post.get("attachments", []):
        if a["type"] == "photo":
            sizes = a["photo"]["sizes"]
            best = sorted(sizes, key=lambda x: x["width"])[-1]["url"]
            photos.append(best)

    return photos


def post_fingerprint(post, group):
    return f"{group}_{post['id']}"


def in_time_window(post_time, now):
    # окно ±10 минут от слота
    slot_minute = (now.minute // 20) * 20
    slot_time = now.replace(minute=slot_minute, second=0, microsecond=0)

    diff = abs((post_time - slot_time).total_seconds())
    return diff < 600
