#!/usr/bin/env python3
"""
VK public walls → Telegram
Только картинки + хештеги/теги
Поддержка нескольких пабликов
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set

import requests
from bs4 import BeautifulSoup
import telebot
from telebot.types import InputMediaPhoto

# ===================== НАСТРОЙКИ =====================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# Можно указать несколько через запятую
# Пример: nthnzone,anotherpublic
VK_DOMAINS_RAW = os.getenv("nthnzone", "nthnzonehorny")
VK_DOMAINS = [d.strip() for d in VK_DOMAINS_RAW.split(",") if d.strip()]

USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "1") == "1"
STATE_FILE = Path("last_post_ids.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vk2tg")

if not TG_BOT_TOKEN:
    raise ValueError("TG_BOT_TOKEN не задан")
if not TG_CHAT_ID:
    raise ValueError("TG_CHAT_ID не задан")
if not VK_DOMAINS:
    raise ValueError("VK_DOMAIN не задан")

bot = telebot.TeleBot(TG_BOT_TOKEN, parse_mode="HTML")


# ===================== СОСТОЯНИЕ =====================
def load_state() -> Dict[str, str]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, str]):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ===================== HTML =====================
def fetch_html(domain: str) -> str:
    if USE_PLAYWRIGHT:
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
            try:
                page.wait_for_selector(".wall_item, .post, [data-post-id], div[id^='post']", timeout=15000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html
    else:
        r = requests.get(f"https://m.vk.com/{domain}", headers=HEADERS, timeout=25)
        r.raise_for_status()
        return r.text


# ===================== ОЧИСТКА ТЕКСТА =====================
def clean_text(raw: str) -> str:
    if not raw:
        return ""

    # Убираем типичный мусор интерфейса ВК
    junk_patterns = [
        r"Действия",
        r"Отправить реакцию.*",
        r"Выбор реакции",
        r"Нравится",
        r"Комментировать",
        r"Поделиться",
        r"\d+\s*(ч|мин|д|нед|мес)\s*назад",
        r"вчера",
        r"сегодня",
        r"Показать ещё",
        r"Читать полностью",
        r"Перевести",
        r"Редактировать",
        r"Удалить",
        r"Закрепить",
        r"^\d+$",                    # просто цифры
    ]

    text = raw
    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # Оставляем в основном хештеги и короткий осмысленный текст
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Оставляем строки с хештегами или нормальный текст
        if "#" in line or len(line) > 15:
            lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:900]


# ===================== ПАРСИНГ =====================
def parse_posts(html: str, domain: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    seen: Set[str] = set()

    items = soup.select(
        ".wall_item, .post, [data-post-id], .wi_body, "
        "div[id^='post'], .feed_row, .wall_post"
    )

    for item in items:
        try:
            # ID
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

            if not post_id or post_id in seen:
                continue
            seen.add(post_id)

            # Текст
            raw_text = ""
            for sel in [".wall_post_text", ".pi_text", ".post_content", ".wi_body", ".wall_text"]:
                el = item.select_one(sel)
                if el:
                    raw_text = el.get_text("\n", strip=True)
                    if len(raw_text) > 5:
                        break
            if not raw_text:
                raw_text = item.get_text("\n", strip=True)

            text = clean_text(raw_text)

            # Фото (главное)
            photos = []
            for img in item.select("img"):
                src = img.get("src") or img.get("data-src") or img.get("data-original") or ""
                if not src:
                    continue
                if src.startswith("//"):
                    src = "https:" + src

                if any(x in src for x in ["userapi.com", "vk.com", "sun", "vkuservideo"]):
                    # Отсекаем мелкие аватарки и иконки
                    if any(x in src for x in ["_50.", "_100.", "camera_50", "camera_100", "50x50", "75x75"]):
                        continue
                    photos.append(src)

            photos = list(dict.fromkeys(photos))  # уникальные

            # Нам нужны в основном посты с картинками
            if not photos and not text:
                continue

            posts.append({
                "id": post_id,
                "domain": domain,
                "text": text,
                "photos": photos[:10],
                "url": f"https://vk.com/wall{post_id}",
            })

        except Exception as e:
            log.debug(f"Ошибка парсинга: {e}")
            continue

    return posts


# ===================== ОТПРАВКА =====================
def send_post(post: Dict):
    text = post.get("text", "").strip()
    photos = post.get("photos", [])
    url = post["url"]

    # Формируем подпись: только текст (хештеги) + источник
    if text:
        caption = f"{text}\n\n<a href='{url}'>Источник</a>"
    else:
        caption = f"<a href='{url}'>Источник</a>"

    if len(caption) > 1024:
        caption = caption[:980] + f"…\n\n<a href='{url}'>Источник</a>"

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
            # Если картинок нет — просто текст с хештегами
            bot.send_message(TG_CHAT_ID, caption, disable_web_page_preview=True)

        log.info(f"✅ {post['domain']} → {post['id']}")
    except Exception as e:
        log.error(f"Ошибка отправки {post['id']}: {e}")


# ===================== MAIN =====================
def main():
    log.info(f"Паблики: {VK_DOMAINS}")
    state = load_state()

    for domain in VK_DOMAINS:
        log.info(f"--- Проверяем {domain} ---")
        last_id = state.get(domain)

        try:
            html = fetch_html(domain)
        except Exception as e:
            log.error(f"Не удалось загрузить {domain}: {e}")
            continue

        posts = parse_posts(html, domain)
        log.info(f"Найдено постов: {len(posts)}")

        if not posts:
            continue

        # Новые посты
        new_posts = []
        for post in posts:
            if last_id and post["id"] == last_id:
                break
            new_posts.append(post)

        new_posts = list(reversed(new_posts))  # от старых к новым

        if not new_posts:
            log.info("Новых нет")
            continue

        log.info(f"Новых: {len(new_posts)}")

        for post in new_posts:
            # Отправляем только если есть картинки или нормальные теги
            if post["photos"] or ("#" in post["text"]):
                send_post(post)
                state[domain] = post["id"]
                save_state(state)

    log.info("Готово")


if __name__ == "__main__":
    main()
