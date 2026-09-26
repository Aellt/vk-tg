#!/usr/bin/env python3
"""
VK → Telegram
Только картинки + хештеги
Паблики: nthnzone + nthnzonehorny
"""

import os
import re
import json
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Set

import requests
from bs4 import BeautifulSoup
import telebot
from telebot.types import InputMediaPhoto

# ===================== НАСТРОЙКИ =====================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

VK_DOMAINS = ["nthnzone", "nthnzonehorny"]
STATE_FILE = Path("last_post_ids.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://m.vk.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("vk2tg")

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("TG_BOT_TOKEN или TG_CHAT_ID не заданы")

bot = telebot.TeleBot(TG_BOT_TOKEN)


# ===================== СОСТОЯНИЕ =====================
def load_state() -> Dict[str, str]:
    if not STATE_FILE.exists():
        log.warning("Файл last_post_ids.json не найден, создаём пустой")
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        log.info(f"Загружено состояние: {data}")
        return data
    except Exception as e:
        log.error(f"Ошибка чтения состояния: {e}")
        return {}


def save_state(state: Dict[str, str]):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info(f"Состояние сохранено: {state}")


# ===================== ПОЛУЧЕНИЕ HTML =====================
def fetch_html(domain: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(f"https://m.vk.com/{domain}", wait_until="domcontentloaded", timeout=45000)

        try:
            page.wait_for_selector(
                ".wall_item, .post, [data-post-id], div[id^='post']",
                timeout=15000
            )
        except Exception:
            log.warning(f"[{domain}] посты не найдены")

        html = page.content()
        browser.close()
        return html


# ===================== ОЧИСТКА ТЕКСТА =====================
def clean_text(raw: str) -> str:
    if not raw:
        return ""

    junk = [
        r"Действия", r"Отправить реакцию.*", r"Выбор реакции",
        r"Нравится", r"Комментировать", r"Поделиться",
        r"Показать ещё", r"Читать полностью", r"Перевести",
        r"Источник", r"No Thoughts Head Null",
        r"nthnzonehorny", r"nthnzone",
        r"http\S+", r"vk\.com\S*",
        r"\d+\s*(ч|мин|д|нед|мес)\s*назад",
        r"вчера", r"сегодня", r"^\d+$",
    ]

    text = raw
    for pattern in junk:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    hashtags = re.findall(r"#\w+", text)
    if not hashtags:
        return ""

    if len(hashtags) == 1:
        return hashtags[0]

    return f"{hashtags[0]}\n{' '.join(hashtags[1:])}"


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

            photos = []
            for img in item.select("img"):
                src = img.get("src") or img.get("data-src") or img.get("data-original") or ""
                if not src:
                    continue
                if src.startswith("//"):
                    src = "https:" + src

                if any(x in src for x in ["userapi.com", "vk.com", "sun", "vkuservideo"]):
                    if any(x in src for x in ["_50.", "_100.", "camera_50", "camera_100", "50x50", "75x75"]):
                        continue
                    photos.append(src)

            photos = list(dict.fromkeys(photos))
            if not photos:
                continue

            posts.append({
                "id": post_id,
                "domain": domain,
                "text": text,
                "photos": photos[:9],
            })
        except Exception as e:
            log.debug(f"Ошибка парсинга: {e}")
            continue

    return posts


# ===================== СКАЧИВАНИЕ КАРТИНКИ =====================
def download_image(url: str) -> str | None:
    """Скачивает картинку во временный файл и возвращает путь"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()

        suffix = ".jpg"
        if "png" in url.lower():
            suffix = ".png"
        elif "webp" in url.lower():
            suffix = ".webp"

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        log.warning(f"Не удалось скачать {url}: {e}")
        return None


# ===================== ОТПРАВКА =====================
def send_post(post: Dict):
    text = post.get("text", "").strip()
    photos = post.get("photos", [])
    caption = text if text else None

    # Скачиваем все картинки
    local_files = []
    for url in photos:
        path = download_image(url)
        if path:
            local_files.append(path)

    if not local_files:
        log.warning(f"Не удалось скачать ни одной картинки для {post['id']}")
        return

    try:
        if len(local_files) == 1:
            with open(local_files[0], "rb") as f:
                bot.send_photo(TG_CHAT_ID, f, caption=caption)
        else:
            media = []
            files = []
            for i, path in enumerate(local_files):
                f = open(path, "rb")
                files.append(f)
                if i == 0 and caption:
                    media.append(InputMediaPhoto(f, caption=caption))
                else:
                    media.append(InputMediaPhoto(f))

            bot.send_media_group(TG_CHAT_ID, media)

            for f in files:
                f.close()

        log.info(f"✅ [{post['domain']}] {post['id']} | фото: {len(local_files)}")
    except Exception as e:
        log.error(f"Ошибка отправки {post['id']}: {e}")
    finally:
        # Удаляем временные файлы
        for path in local_files:
            try:
                os.unlink(path)
            except Exception:
                pass


# ===================== MAIN =====================
def main():
    log.info(f"Паблики: {VK_DOMAINS}")
    state = load_state()

    for domain in VK_DOMAINS:
        log.info(f"---------- {domain} ----------")
        last_id = state.get(domain)
        log.info(f"Последний ID из файла: {last_id or 'нет'}")

        try:
            html = fetch_html(domain)
        except Exception as e:
            log.error(f"Не удалось загрузить {domain}: {e}")
            continue

        posts = parse_posts(html, domain)
        log.info(f"Найдено постов с картинками: {len(posts)}")

        if not posts:
            continue

        # Показываем ID найденных постов для отладки
        found_ids = [p["id"] for p in posts]
        log.info(f"ID на странице: {found_ids}")

        new_posts = []
        for post in posts:
            if last_id and post["id"] == last_id:
                break
            new_posts.append(post)

        new_posts = list(reversed(new_posts))

        if not new_posts:
            log.info("Новых постов нет")
            continue

        log.info(f"Новых постов: {len(new_posts)}")

        for post in new_posts:
            send_post(post)
            state[domain] = post["id"]
            save_state(state)

    log.info("Готово")


if __name__ == "__main__":
    main()
