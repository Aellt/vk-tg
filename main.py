import os

from vk import get_latest_posts
from telegram import send_post
from utils import extract_photos, post_fingerprint
from state import load_state, save_state

VK_TOKEN = os.environ["VK_TOKEN"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHANNEL = os.environ["TG_CHANNEL"]

GROUPS = ["nthnzone", "nthnzonehorny"]
MAX_CACHE_SIZE = 100  # Сколько кэшированных ID постов хранить, чтобы не раздувать файл


def is_valid_post(post):
    if post.get("is_pinned", 0) == 1:
        return False

    if post.get("marked_as_ads", 0) == 1:
        return False

    # Пост валиден, только если в нём есть ХОТЯ БЫ текст или ХОТЯ БЫ одна фотография
    # Это защитит от постов, содержащих только видео/опросы/ссылки
    has_text = bool(post.get("text", "").strip())
    has_photos = any(att["type"] == "photo" for att in post.get("attachments", []))
    
    if not has_text and not has_photos:
        return False

    return True


def run():
    state = load_state()
    # Используем list, так как порядок добавления может быть важен для обрезки
    sent_list = state.get("sent", [])
    sent_set = set(sent_list)

    print("BOT STARTED")
    changed = False

    for group in GROUPS:
        print(f"CHECK GROUP: {group}")

        try:
            # Берем последние 10 постов, чтобы точно не пропустить ничего, если бот долго не работал
            posts = get_latest_posts(group, VK_TOKEN, count=10)
        except Exception as e:
            print(f"Error fetching posts for {group}: {e}")
            continue

        # Перебираем посты ОТ СТАРЫХ К НОВЫМ (разворачиваем список), 
        # чтобы они постились в правильном хронологическом порядке
        for post in reversed(posts):
            if not is_valid_post(post):
                continue

            fp = post_fingerprint(post, group)

            if fp in sent_set:
                continue

            text = post.get("text", "").strip()
            photos = extract_photos(post)

            print("SEND:", fp)
            send_post(TG_TOKEN, TG_CHANNEL, text, photos)

            # Добавляем в кэш
            sent_set.add(fp)
            sent_list.append(fp)
            changed = True

    if changed:
        # Ограничиваем размер кэша, удаляя самые старые записи, если их больше лимита
        if len(sent_list) > MAX_CACHE_SIZE:
            sent_list = sent_list[-MAX_CACHE_SIZE:]
            
        state["sent"] = sent_list
        save_state(state)
        print("STATE SAVED")


if __name__ == "__main__":
    run()
