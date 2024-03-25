import re
import requests

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
    global pattern
    para = req.params.get("url")
    if not para or not pattern.match(para):
        return func.HttpResponse("400 Bad Requset: no url param", status_code=400)
    h = {
        "user-agent": "COPY/2.0.7",
        "source": "copyApp",
        "webp": "1",
        "version": "2.0.7",
        "platform": "3",
        "accept": "application/json",
        "authorization": "Token",
        "region": "0",
    } # 保底
    for k, v in req.headers.items(): h[k.lower()] = v
    d = getapibody(para, req.method, req.get_body(), h)
    if len(d): return func.HttpResponse(d, status_code=200)
    return func.HttpResponse("504 Gateway Timeout: Empty Response From Upstream", status_code=504)
