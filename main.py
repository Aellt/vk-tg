import os
import json
from datetime import datetime

from vk import get_latest_post
from telegram import send_post
from utils import extract_photos, post_fingerprint, in_time_window


VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]


def load_cache():
    try:
        with open("sent_cache.json", "r") as f:
            return json.load(f)
    except:
        return {"sent": []}


def save_cache(cache):
    with open("sent_cache.json", "w") as f:
        json.dump(cache, f, indent=2)


def run():
    cache = load_cache()
    sent = set(cache["sent"])

    now = datetime.utcnow()

    for group in GROUPS:
        post = get_latest_post(group, VK_TOKEN)

        post_time = datetime.utcfromtimestamp(post["date"])

        fp = post_fingerprint(post, group)

        # уже отправляли
        if fp in sent:
            continue


        text = post.get("text", "")
        photos = extract_photos(post)

        send_post(TG_TOKEN, TG_CHANNEL, text, photos)

        sent.add(fp)

    cache["sent"] = list(sent)[-500:]
    save_cache(cache)
    
post = get_latest_post(group, VK_TOKEN)
print(post)

if __name__ == "__main__":
    run()
