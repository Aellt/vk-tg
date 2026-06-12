import os
import json
import traceback

from vk import get_latest_post
from telegram import send_post
from utils import extract_photos, post_fingerprint


VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]


def run():
    sent = set()

    print("START BOT")

    for group in GROUPS:
        print("GROUP:", group)

        post = get_latest_post(group, VK_TOKEN)

        print("POST RECEIVED:", post["id"])

        fp = post_fingerprint(post, group)

        if fp in sent:
            print("SKIP DUPLICATE")
            continue

        text = post.get("text", "")
        photos = extract_photos(post)

        print("SENDING TO TG")

        send_post(TG_TOKEN, TG_CHANNEL, text, photos)

        sent.add(fp)

        print("DONE:", fp)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        raise
