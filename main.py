#!/usr/bin/env python3
"""
VK (public wall) → Telegram bot without VK access token.
"""

import os
import re
import time
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import telebot
from telebot.types import InputMediaPhoto

load_dotenv()

# === Настройки ===
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHANNEL")
VK_DOMAIN = os.getenv("nthnzone", "nthnzonehorny")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "1") == "1"

STATE_FILE = Path("last_post_id.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vk2tg")

bot = telebot.TeleBot(TG_BOT_TOKEN, parse_mode="HTML")


def load_last_id() -> Optional[str]:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("last_id")
    return None


def save_last_id(post_id: str):
    STATE_FILE.write_text(json.dumps({"last_id": post_id}, ensure_ascii=False), encoding="utf-8")


# ---------- Парсинг ----------

def fetch_html_simple(domain: str) -> str:
    """Простой способ через requests (может ловиться капчей)."""
    url = f"https://m.vk.com/{domain}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def fetch_html_playwright(domain: str) -> str:
    """Надёжный способ через Playwright."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(f"https://m.vk.com/{domain}", wait_until="domcontentloaded", timeout=30000)
        # Ждём появления постов
        page.wait_for_selector(".wall_item, .post, [data-post-id]", timeout=15000)
        html = page.content()
        browser.close()
        return html


def parse_posts(html: str) -> List[Dict]:
    """
    Извлекает посты из HTML мобильной версии.
    Возвращает список словарей: id, text, photos, url, date.
    """
    soup = BeautifulSoup(html, "lxml")
    posts = []

    # Разные возможные контейнеры постов (VK часто меняет классы)
    items = (
        soup.select(".wall_item")
        or soup.select(".post")
        or soup.select("[data-post-id]")
        or soup.select(".wi_body")
    )

    for item in items:
        try:
            # ID поста
            post_id = None
            # data-post-id="wall-123_456" или просто "123_456"
            data_id = item.get("data-post-id") or item.get("id") or ""
            m = re.search(r"(-?\d+)_(\d+)", data_id)
            if m:
                post_id = f"{m.group(1)}_{m.group(2)}"
            else:
                # Ищем ссылку на пост
                link = item.select_one("a[href*='wall']")
                if link:
                    href = link.get("href", "")
                    m = re.search(r"wall(-?\d+_\d+)", href)
                    if m:
                        post_id = m.group(1)

            if not post_id:
                continue

            # Текст
            text_el = (
                item.select_one(".wall_post_text")
                or item.select_one(".pi_text")
                or item.select_one(".post_content")
                or item.select_one(".wi_body")
            )
            text = text_el.get_text("\n", strip=True) if text_el else ""

            # Фото
            photos = []
            for img in item.select("img"):
                src = img.get("src") or img.get("data-src") or ""
                if "userapi.com" in src or "vk.com" in src or "vkuservideo" in src:
                    # Берём более качественную версию, если есть
                    if "size=" in src or "cs" in src:
                        photos.append(src)
                    elif src.startswith("//"):
                        photos.append("https:" + src)
                    elif src.startswith("http"):
                        photos.append(src)

            # Убираем дубликаты и аватарки
            photos = list(dict.fromkeys(photos))  # сохраняем порядок
            photos = [p for p in photos if "camera_50" not in p and "camera_100" not in p]

            posts.append({
                "id": post_id,
                "text": text,
                "photos": photos[:10],  # ограничим
                "url": f"https://vk.com/wall{post_id}",
            })
        except Exception as e:
            log.debug(f"Ошибка парсинга одного поста: {e}")
            continue

    return posts


def get_new_posts(domain: str, last_id: Optional[str]) -> List[Dict]:
    try:
        if USE_PLAYWRIGHT:
            html = fetch_html_playwright(domain)
        else:
            html = fetch_html_simple(domain)
    except Exception as e:
        log.error(f"Не удалось получить HTML: {e}")
        return []

    posts = parse_posts(html)
    if not posts:
        log.warning("Посты не найдены. Возможно, изменилась вёрстка или сработала защита.")
        return []

    # Сортируем от старых к новым (чтобы отправлять в хронологическом порядке)
    # Обычно на странице сначала новые, поэтому разворачиваем
    posts = list(reversed(posts))

    new_posts = []
    for p in posts:
        if last_id and p["id"] == last_id:
            break
        new_posts.append(p)

    # Оставляем только действительно новые (после last_id)
    if last_id:
        # Более надёжно: берём все, у которых id "новее"
        # (простая проверка — пока last_id не встретился)
        pass

    return new_posts


# ---------- Отправка в Telegram ----------

def send_post(post: Dict):
    text = post["text"]
    if len(text) > 3900:
        text = text[:3900] + "…"

    caption = f"{text}\n\n<a href='{post['url']}'>Источник ВК</a>" if text else f"<a href='{post['url']}'>Пост ВК</a>"

    photos = post.get("photos", [])

    try:
        if not photos:
            bot.send_message(TG_CHAT_ID, caption, disable_web_page_preview=False)
        elif len(photos) == 1:
            bot.send_photo(TG_CHAT_ID, photos[0], caption=caption)
        else:
            media = []
            for i, url in enumerate(photos[:10]):
                if i == 0:
                    media.append(InputMediaPhoto(url, caption=caption, parse_mode="HTML"))
                else:
                    media.append(InputMediaPhoto(url))
            bot.send_media_group(TG_CHAT_ID, media)
        log.info(f"Отправлен пост {post['id']}")
    except Exception as e:
        log.error(f"Ошибка отправки поста {post['id']}: {e}")
        # Fallback — только текст
        try:
            bot.send_message(TG_CHAT_ID, caption)
        except Exception as e2:
            log.error(f"Fallback тоже упал: {e2}")


# ---------- Основной цикл ----------

def main():
    if not all([TG_BOT_TOKEN, TG_CHAT_ID, VK_DOMAIN]):
        log.error("Заполни TG_BOT_TOKEN, TG_CHAT_ID и VK_DOMAIN в .env")
        return

    log.info(f"Старт. Мониторим https://vk.com/{VK_DOMAIN} → Telegram {TG_CHAT_ID}")
    log.info(f"Режим: {'Playwright' if USE_PLAYWRIGHT else 'requests'}")

    last_id = load_last_id()
    log.info(f"Последний известный пост: {last_id or 'нет'}")

    while True:
        try:
            new_posts = get_new_posts(VK_DOMAIN, last_id)

            if new_posts:
                log.info(f"Найдено новых постов: {len(new_posts)}")
                for post in new_posts:
                    send_post(post)
                    last_id = post["id"]
                    save_last_id(last_id)
                    time.sleep(1)  # небольшая пауза между сообщениями
            else:
                log.info("Новых постов нет")

        except Exception as e:
            log.exception(f"Ошибка в цикле: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
