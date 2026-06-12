import requests

VK_API = "https://api.vk.com/method/wall.get"
VERSION = "5.131"


def get_latest_posts(domain, token, count=3):
    r = requests.get(VK_API, params={
        "access_token": token,
        "v": VERSION,
        "domain": domain,
        "count": count
    }).json()

    if "error" in r:
        raise Exception(f"VK ERROR: {r['error']}")

    return r["response"]["items"]
