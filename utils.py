import hashlib


def post_fingerprint(post, group):
    return f"{group}_{post['id']}"


def extract_photos(post):
    photos = []

    for att in post.get("attachments", []):
        if att["type"] == "photo":
            sizes = att["photo"]["sizes"]

            if sizes:
                best = max(
                    sizes,
                    key=lambda x: x.get("width", 0) * x.get("height", 0)
                )

                photos.append(best["url"])

    return photos
