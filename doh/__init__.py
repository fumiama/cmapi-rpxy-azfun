import logging
import typing
import cachetools
import re
from urllib.parse import quote

import azure.functions as func
import cloudscraper

dohurl = "https://dns.google/resolve?name="
pattern = re.compile(r'^(?:[\w-]+\.)+[\w-]+$')
scraper = cloudscraper.create_scraper()
cache = cachetools.TTLCache(maxsize=1024*1024*1024, ttl=10*60)

def getapibody(u: str) -> typing.Tuple[bytes, bool]:
    global scraper, cache
    d = cache.get(u)
    if d is not None:
        logging.info("get cached "+u)
        return d, True
    logging.info("get new "+u)
    s = scraper.get(u)
    d = s.content
    s.close()
    cache[u] = d
    return d, False

def main(req: func.HttpRequest) -> func.HttpResponse:
    global pattern
    para = req.params.get("name")
    if not para or not pattern.match(para):
        return func.HttpResponse("400 Bad requset", status_code=400)
    typ = req.params.get("type", "1")
    d, cached = getapibody(dohurl+quote(para)+"&type="+quote(typ))
    resp = func.HttpResponse(d, status_code=200, mimetype="application/json")
    resp.headers.add_header("Cached", str(cached))
    return resp
