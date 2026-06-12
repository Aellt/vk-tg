import hashlib


def post_fingerprint(post, group):
    return f"{group}_{post['id']}"


def extract_photos(post):
    photos = []

    for att in post.get("attachments", []):
        if att["type"] == "photo":
            sizes = att["photo"]["sizes"]
            best = sizes[-1]["url"]
            photos.append(best)

    return photos
