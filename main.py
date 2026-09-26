#!/usr/bin/env python3
"""
VK public wall → Telegram bot (без access token)
Режим для GitHub Actions: один проход и выход.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import telebot
from telebot.types import InputMediaPhoto

# ===================== НАСТРОЙКИ =====================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
VK_DOMAIN = os.getenv("nthnzone", "nthnzonehorny)
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "1") == "1"

STATE_FILE = Path("last_post_id.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vk2tg")

# ===================== ПРОВЕРКИ =====================
if not TG_BOT_TOKEN:
    raise ValueError("❌ TG_BOT_TOKEN не задан! Добавь секрет в GitHub Actions.")
if not TG_CHAT_ID:
    raise ValueError("❌ TG_CHAT_ID не задан!")
if not VK_DOMAIN:
    raise ValueError("❌ VK_DOMAIN не задан!")

bot = telebot.TeleBot(TG_BOT_TOKEN, parse_mode="HTML")


# ===================== СОСТОЯНИЕ =====================
def load_last_id() -> Optional[str]:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data.get("last_id")
        except Exception:
            return None
    return None


def save_last_id(post_id: str):
    STATE_FILE.write_text(
        json.dumps({"last_id": post_id}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ===================== ПОЛУЧЕНИЕ HTML =====================
def fetch_html_simple(domain: str) -> str:
    url = f"https://m.vk.com/{domain}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def fetch_html_playwright(domain: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(f"https://m.vk.com/{domain}", wait_until="domcontentloaded", timeout=40000)

        # Ждём появления постов
        try:
            page.wait_for_selector(
                ".wall_item, .post, [data-post-id], .wi_body, div[id^='post']",
                timeout=20000
            )
        except Exception:
            log.warning("Селектор постов не найден, продолжаем с тем что есть")

        html = page.content()
        browser.close()
        return html


# ===================== ПАРСИНГ =====================
def parse_posts(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    seen_ids = set()

    items = soup.select(
        ".wall_item, .post, [data-post-id], .wi_body, "
        ".Post, .feed_row, .wall_post, div[id^='post']"
    )

    for item in items:
        try:
            # ----- ID -----
            post_id = None
            data_id = item.get("data-post-id") or item.get("id") or ""
            m = re.search(r"(-?\d+)_(\d+)", str(data_id))
            if m:
                post_id = f"{m.group(1)}_{m.group(2)}"

            if not post_id:
                for a in item.select("a[href*='wall']"):
                    href = a.get("href", "")
                    m = re.search(r"wall(-?\d+_\d+)", href)
                    if m:
                        post_id = m.group(1)
                        break

            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            # ----- Текст -----
            text = ""
            for sel in [
                ".wall_post_text", ".pi_text", ".post_content",
                ".wi_body", ".PostText", ".wall_text",
                "[class*='post_text']", "[class*='PostContent']"
            ]:
                el = item.select_one(sel)
                if el:
                    text = el.get_text("\n", strip=True)
                    if len(text) > 10:
                        break

            if len(text) < 10:
                text = item.get_text("\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)[:1800]

            # ----- Фото -----
            photos = []
            for img in item.select("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or ""
                )
                if not src:
                    continue
                if src.startswith("//"):
                    src = "https:" + src

                if any(x in src for x in ["userapi.com", "vk.com", "sun", "vkuservideo"]):
                    if any(x in src for x in ["_50.", "_100.", "camera_50", "camera_100", "50x50"]):
                        continue
                    photos.append(src)

            photos = list(dict.fromkeys(photos))  # уникальные с сохранением порядка

            posts.append({
                "id": post_id,
                "text": text.strip(),
                "photos": photos[:9],
                "url": f"https://vk.com/wall{post_id}",
            })

        except Exception as e:
            log.debug(f"Ошибка парсинга одного поста: {e}")
            continue

    return posts


# ===================== ОТПРАВКА =====================
def send_post(post: Dict):
    text = post.get("text", "").strip()
    url = post["url"]
    photos = post.get("photos", [])

    if text:
        caption = f"{text}\n\n<a href='{url}'>Источник</a>"
    else:
        caption = f"<a href='{url}'>Новый пост</a>"

    if len(caption) > 1024:
        caption = caption[:980] + "…\n\n<a href='{0}'>Источник</a>".format(url)

    try:
        if photos:
            if len(photos) == 1:
                bot.send_photo(TG_CHAT_ID, photos[0], caption=caption)
            else:
                media = []
                for i, p in enumerate(photos):
                    if i == 0:
                        media.append(InputMediaPhoto(p, caption=caption, parse_mode="HTML"))
                    else:
                        media.append(InputMediaPhoto(p))
                bot.send_media_group(TG_CHAT_ID, media)
        else:
            bot.send_message(TG_CHAT_ID, caption, disable_web_page_preview=False)

        log.info(f"✅ Отправлен пост {post['id']}")
    except Exception as e:
        log.error(f"Ошибка отправки {post['id']}: {e}")
        try:
            bot.send_message(
                TG_CHAT_ID,
                f"<b>Пост ВК</b>\n{text[:600]}\n\n<a href='{url}'>Открыть</a>",
                disable_web_page_preview=False
            )
        except Exception as e2:
            log.error(f"Fallback тоже упал: {e2}")


# ===================== ОСНОВНАЯ ЛОГИКА =====================
def main():
    log.info(f"Запуск. Мониторим: https://vk.com/{VK_DOMAIN}")
    log.info(f"Режим: {'Playwright' if USE_PLAYWRIGHT else 'requests'}")

    last_id = load_last_id()
    log.info(f"Последний известный пост: {last_id or 'нет'}")

    # Получаем HTML
    try:
        if USE_PLAYWRIGHT:
            html = fetch_html_playwright(VK_DOMAIN)
        else:
            html = fetch_html_simple(VK_DOMAIN)
    except Exception as e:
        log.error(f"Не удалось получить страницу: {e}")
        return

    posts = parse_posts(html)
    log.info(f"Найдено постов на странице: {len(posts)}")

    if not posts:
        log.warning("Посты не найдены. Возможно, сработала защита или изменилась вёрстка.")
        return

    # Берём только новые посты (те, что появились после last_id)
    new_posts = []
    for post in posts:
        if last_id and post["id"] == last_id:
            break
        new_posts.append(post)

    # Отправляем от старых к новым
    new_posts = list(reversed(new_posts))

    if not new_posts:
        log.info("Новых постов нет")
        return

    log.info(f"Новых постов: {len(new_posts)}")

    for post in new_posts:
        send_post(post)
        save_last_id(post["id"])

    log.info("Готово")


if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
VK public wall → Telegram bot (без access token)
Режим для GitHub Actions: один проход и выход.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import telebot
from telebot.types import InputMediaPhoto

# ===================== НАСТРОЙКИ =====================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
VK_DOMAIN = os.getenv("VK_DOMAIN")
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "1") == "1"

STATE_FILE = Path("last_post_id.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vk2tg")

# ===================== ПРОВЕРКИ =====================
if not TG_BOT_TOKEN:
    raise ValueError("❌ TG_BOT_TOKEN не задан! Добавь секрет в GitHub Actions.")
if not TG_CHAT_ID:
    raise ValueError("❌ TG_CHAT_ID не задан!")
if not VK_DOMAIN:
    raise ValueError("❌ VK_DOMAIN не задан!")

bot = telebot.TeleBot(TG_BOT_TOKEN, parse_mode="HTML")


# ===================== СОСТОЯНИЕ =====================
def load_last_id() -> Optional[str]:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data.get("last_id")
        except Exception:
            return None
    return None


def save_last_id(post_id: str):
    STATE_FILE.write_text(
        json.dumps({"last_id": post_id}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ===================== ПОЛУЧЕНИЕ HTML =====================
def fetch_html_simple(domain: str) -> str:
    url = f"https://m.vk.com/{domain}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def fetch_html_playwright(domain: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(f"https://m.vk.com/{domain}", wait_until="domcontentloaded", timeout=40000)

        # Ждём появления постов
        try:
            page.wait_for_selector(
                ".wall_item, .post, [data-post-id], .wi_body, div[id^='post']",
                timeout=20000
            )
        except Exception:
            log.warning("Селектор постов не найден, продолжаем с тем что есть")

        html = page.content()
        browser.close()
        return html


# ===================== ПАРСИНГ =====================
def parse_posts(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    seen_ids = set()

    items = soup.select(
        ".wall_item, .post, [data-post-id], .wi_body, "
        ".Post, .feed_row, .wall_post, div[id^='post']"
    )

    for item in items:
        try:
            # ----- ID -----
            post_id = None
            data_id = item.get("data-post-id") or item.get("id") or ""
            m = re.search(r"(-?\d+)_(\d+)", str(data_id))
            if m:
                post_id = f"{m.group(1)}_{m.group(2)}"

            if not post_id:
                for a in item.select("a[href*='wall']"):
                    href = a.get("href", "")
                    m = re.search(r"wall(-?\d+_\d+)", href)
                    if m:
                        post_id = m.group(1)
                        break

            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            # ----- Текст -----
            text = ""
            for sel in [
                ".wall_post_text", ".pi_text", ".post_content",
                ".wi_body", ".PostText", ".wall_text",
                "[class*='post_text']", "[class*='PostContent']"
            ]:
                el = item.select_one(sel)
                if el:
                    text = el.get_text("\n", strip=True)
                    if len(text) > 10:
                        break

            if len(text) < 10:
                text = item.get_text("\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)[:1800]

            # ----- Фото -----
            photos = []
            for img in item.select("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or ""
                )
                if not src:
                    continue
                if src.startswith("//"):
                    src = "https:" + src

                if any(x in src for x in ["userapi.com", "vk.com", "sun", "vkuservideo"]):
                    if any(x in src for x in ["_50.", "_100.", "camera_50", "camera_100", "50x50"]):
                        continue
                    photos.append(src)

            photos = list(dict.fromkeys(photos))  # уникальные с сохранением порядка

            posts.append({
                "id": post_id,
                "text": text.strip(),
                "photos": photos[:9],
                "url": f"https://vk.com/wall{post_id}",
            })

        except Exception as e:
            log.debug(f"Ошибка парсинга одного поста: {e}")
            continue

    return posts


# ===================== ОТПРАВКА =====================
def send_post(post: Dict):
    text = post.get("text", "").strip()
    url = post["url"]
    photos = post.get("photos", [])

    if text:
        caption = f"{text}\n\n<a href='{url}'>Источник</a>"
    else:
        caption = f"<a href='{url}'>Новый пост</a>"

    if len(caption) > 1024:
        caption = caption[:980] + "…\n\n<a href='{0}'>Источник</a>".format(url)

    try:
        if photos:
            if len(photos) == 1:
                bot.send_photo(TG_CHAT_ID, photos[0], caption=caption)
            else:
                media = []
                for i, p in enumerate(photos):
                    if i == 0:
                        media.append(InputMediaPhoto(p, caption=caption, parse_mode="HTML"))
                    else:
                        media.append(InputMediaPhoto(p))
                bot.send_media_group(TG_CHAT_ID, media)
        else:
            bot.send_message(TG_CHAT_ID, caption, disable_web_page_preview=False)

        log.info(f"✅ Отправлен пост {post['id']}")
    except Exception as e:
        log.error(f"Ошибка отправки {post['id']}: {e}")
        try:
            bot.send_message(
                TG_CHAT_ID,
                f"<b>Пост ВК</b>\n{text[:600]}\n\n<a href='{url}'>Открыть</a>",
                disable_web_page_preview=False
            )
        except Exception as e2:
            log.error(f"Fallback тоже упал: {e2}")


# ===================== ОСНОВНАЯ ЛОГИКА =====================
def main():
    log.info(f"Запуск. Мониторим: https://vk.com/{VK_DOMAIN}")
    log.info(f"Режим: {'Playwright' if USE_PLAYWRIGHT else 'requests'}")

    last_id = load_last_id()
    log.info(f"Последний известный пост: {last_id or 'нет'}")

    # Получаем HTML
    try:
        if USE_PLAYWRIGHT:
            html = fetch_html_playwright(VK_DOMAIN)
        else:
            html = fetch_html_simple(VK_DOMAIN)
    except Exception as e:
        log.error(f"Не удалось получить страницу: {e}")
        return

    posts = parse_posts(html)
    log.info(f"Найдено постов на странице: {len(posts)}")

    if not posts:
        log.warning("Посты не найдены. Возможно, сработала защита или изменилась вёрстка.")
        return

    # Берём только новые посты (те, что появились после last_id)
    new_posts = []
    for post in posts:
        if last_id and post["id"] == last_id:
            break
        new_posts.append(post)

    # Отправляем от старых к новым
    new_posts = list(reversed(new_posts))

    if not new_posts:
        log.info("Новых постов нет")
        return

    log.info(f"Новых постов: {len(new_posts)}")

    for post in new_posts:
        send_post(post)
        save_last_id(post["id"])

    log.info("Готово")


if __name__ == "__main__":
    main()
