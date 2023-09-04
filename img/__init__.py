import logging

import azure.functions as func
import cloudscraper

api = "https://hi77-overseas.mangafuna.xyz/"
scraper = cloudscraper.create_scraper()

cache = {}

def getapibody(para: str) -> bytes:    
    u = api + para
    if u in cache.keys():
        logging.info("get cached "+u)
        return cache[u]
    logging.info("get new "+u)
    s = scraper.get(u)
    d = s._content
    s.close()
    cache[u] = d
    return d

def main(req: func.HttpRequest) -> func.HttpResponse:
    para = req.params.get("url")
    if not para or not para.startswith(api):
        return func.HttpResponse("400 Bad requset", status_code=400)
    para = para[len(api):]
    return func.HttpResponse(getapibody(para), status_code=200)
