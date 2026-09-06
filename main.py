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

    changed = False

    for group in GROUPS:
        print(f"CHECK GROUP: {group}")

        posts = get_latest_posts(group, VK_TOKEN, count=5)

        latest_post = None

        for post in posts:
            if is_valid_post(post):
                latest_post = post
                break

        if latest_post is None:
            print("NO VALID POSTS")
            continue

        fp = post_fingerprint(latest_post, group)

        if fp in sent:
            print("ALREADY SENT:", fp)
            continue

        text = latest_post.get("text", "").strip()
        photos = extract_photos(latest_post)

        print("SEND:", fp)

        success = send_post(
            TG_TOKEN,
            TG_CHANNEL,
            text,
            photos
        )

        if not success:
            print("SEND FAILED", fp)
            continue
        # Для каждой группы храним только последний пост
        sent = {
            x for x in sent
            if not x.startswith(group + "_")
        }

        sent.add(fp)

        changed = True

    if changed:
        state["sent"] = list(sent)
        save_state(state)


if __name__ == "__main__":
    run()
