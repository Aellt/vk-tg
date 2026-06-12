import os

from vk import get_latest_posts
from telegram import send_post
from utils import extract_photos, post_fingerprint
from state import load_state, save_state


VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]


def is_valid_post(post):
    if post.get("is_pinned", 0) == 1:
        return False
    if post.get("marked_as_ads", 0) == 1:
        return False
    return True


def run():
    state = load_state()
    sent = set(state.get("sent", []))

    print("BOT STARTED")

    for group in GROUPS:
        print(f"CHECK GROUP: {group}")

        posts = get_latest_posts(group, VK_TOKEN, count=10)

        for post in posts:

            if not is_valid_post(post):
                continue

            fp = post_fingerprint(post, group)

            if fp in sent:
                continue

            text = post.get("text", "").strip()
            photos = extract_photos(post)

            print("SEND:", fp)

            send_post(TG_TOKEN, TG_CHANNEL, text, photos)

            sent.add(fp)

            # сразу сохраняем state (ВАЖНО!)
            state["sent"] = list(sent)
            save_state(state)

            break


if __name__ == "__main__":
    run()
