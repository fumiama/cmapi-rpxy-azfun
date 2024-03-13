import re
import requests
import logging

import azure.functions as func


pattern = re.compile(r'^https://api\.(copymanga|mangacopy)\.\w+/api/')

def getapibody(u: str, method: str, body: bytes, headers: dict) -> bytes:
    s = {
        "GET": lambda: requests.get(u, data=body, headers=headers),
        "POST": lambda: requests.post(u, data=body, headers=headers),
        "DELETE": lambda: requests.delete(u, data=body, headers=headers)
    }.get(method, lambda: "400 Bad Request: invalid method")()
    if not isinstance(s, str):
        d = s._content
        s.close()
        return d
    else: return s

def main(req: func.HttpRequest) -> func.HttpResponse:
    para = req.params.get("url")
    if not para or not pattern.match(para):
        return func.HttpResponse("400 Bad Requset: no url param", status_code=400)
    h = {
        "User-Agent": "COPY/2.0.7",
        "source": "copyApp",
        "webp": "1",
        "version": "2.0.7",
        "platform": "3",
    } # 保底
    for k, v in req.headers.items(): h[k] = v
    resp = func.HttpResponse(getapibody(para, req.method, req.get_body(), h), status_code=200)
    return resp
