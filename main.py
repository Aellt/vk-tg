import os

from vk import get_latest_posts
from telegram import send_post
from utils import extract_photos, post_fingerprint


VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]


def is_valid_post(post):
    # убираем закреп
    if post.get("is_pinned", 0) == 1:
        return False

    # убираем рекламу (на всякий случай)
    if post.get("marked_as_ads", 0) == 1:
        return False

    return True


def run():
    sent = set()

    print("BOT STARTED")

    for group in GROUPS:
        print(f"\nCHECK GROUP: {group}")

        posts = get_latest_posts(group, VK_TOKEN, count=5)

        for post in posts:

            post_id = post.get("id")
            print("FOUND POST:", post_id)

            # фильтр pinned / ads
            if not is_valid_post(post):
                print("SKIP PINNED/ADS:", post_id)
                continue

            fp = post_fingerprint(post, group)

            if fp in sent:
                print("SKIP DUPLICATE:", fp)
                continue

            text = post.get("text", "").strip()
            photos = extract_photos(post)

            print("SEND POST:", fp)
            print("TEXT LEN:", len(text), "PHOTOS:", len(photos))

            send_post(TG_TOKEN, TG_CHANNEL, text, photos)

            sent.add(fp)

            # важно: отправляем только 1 новый пост за запуск
            break


if __name__ == "__main__":
    run()
