import logging
from requests.adapters import HTTPAdapter
from requests import Session
from urllib3 import PoolManager
from ssl import PROTOCOL_TLSv1_2

import azure.functions as func

api = "https://api.pixivel.moe/v2/pixiv/illust/search/"

#Subclass of HTTPAdapter
class TLSv1_2Adapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       ssl_version=PROTOCOL_TLSv1_2)

def getapibody(para: str) -> str:
    ses = Session()
    ses.mount('https://', TLSv1_2Adapter())
    u = api + para
    logging.info("get "+u)
    s = ses.get(u, headers={"Referer": "https://pixivel.moe/", "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36"})
    d = s.text
    s.close()
    return d

def main(req: func.HttpRequest) -> func.HttpResponse:
    para = req.url
    para = para[para.index("?")+1:]
    return func.HttpResponse(getapibody(para), status_code=200)
