import os
import time

from vk import get_latest_posts
from telegram import send_post
from utils import extract_photos, post_fingerprint


VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]


def run():
    sent = set()

    print("BOT STARTED")

    for group in GROUPS:
        print(f"CHECK GROUP: {group}")

        posts = get_latest_posts(group, VK_TOKEN, count=3)

        for post in posts:
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

            # важно: чтобы не слать сразу 10 постов за один запуск
            break


if __name__ == "__main__":
    run()
