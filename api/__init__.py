import logging

import azure.functions as func
import cloudscraper

api = "https://api.copymanga.com/api"

def getapibody(para: str) -> str:
    scraper = cloudscraper.create_scraper()
    u = api + para
    logging.info("get "+u)
    s = scraper.get(u)
    d = s.text
    s.close()
    return d

def main(req: func.HttpRequest) -> func.HttpResponse:
    para = req.url
    para = para[para.index("?")+1:]
    return func.HttpResponse(getapibody(para), status_code=200)
