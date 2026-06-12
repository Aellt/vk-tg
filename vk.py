import requests

VK_API = "https://api.vk.com/method/wall.get"
API_VERSION = "5.131"


def get_latest_post(domain, token):
    r = requests.get(VK_API, params={
        "access_token": token,
        "v": API_VERSION,
        "domain": domain,
        "count": 1
    }).json()

    return r["response"]["items"][0]
