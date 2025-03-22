import re
from os import getenv, chmod
from platform import system, machine
from io import BytesIO
from multiprocessing import Lock
from typing import Tuple, Union

import azure.functions as func

use_pipe = not not getenv("CMAPI_USE_PIPE", False)

pattern = re.compile(r'^https://api\.(copymanga|mangacopy|copy-manga)\.\w+/api/')

apierr = None

lk = Lock()

if use_pipe:
    import subprocess
    import struct
    from pathlib import Path
    from json import dumps, loads
    from base64 import b64decode, b64encode
    from urllib3.response import MultiDecoder

    simp_path = Path(__file__).parent.parent/'simp'

    def simp_pipe(u: str, method: str, headers: dict, body: Union[bytes, None] = None) -> Union[bytes, int]:
        cap = {
            "M": method,
            "H": headers,
            "D": u,
        }
        data = (system() + " " + machine() + " " + str(simp_path) + ": " + str(simp_path.exists()) + " " + str(simp_path.stat()) + "\n" + str(cap)).encode()
        try:
            tmpp = Path("/tmp/simp")
            lk.acquire()
            if not tmpp.exists():
                with open(tmpp, "wb") as tmpf:
                    with open(simp_path, "rb") as sf:
                        tmpf.write(sf.read())
                chmod(tmpp, 0o755)
            lk.release()
            stdin = BytesIO()
            if body and len(body):
                stdin.write(struct.pack("<q", len(body)))
                stdin.write(body)
            else:
                stdin.write(b'\x00\x00\x00\x00\x00\x00\x00\x00')
            stdin.seek(0, 0)
            r = subprocess.run(
                [tmpp, '-pipe', dumps(cap)],
                input=stdin.read(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            data = r.stdout
            if r.returncode: return ("simp_pipe: return " + str(r.returncode)).encode(), 500
            if len(r.stderr): return ("simp_pipe: " + r.stderr.decode()).encode(), 500
            cap = loads(data)
            data = b64decode(cap["D"])
            coding = cap["H"].get("Content-Encoding", None)
            if coding:
                data = MultiDecoder(coding).decompress(data)
            return data, cap["C"]
        except Exception as e:
            return ("simp_pipe: " + repr(e) + "\n\n" + b64encode(data).decode()).encode(), 500
else:
    import httpx
    try:
        client = httpx.Client(http2=True, verify=False)
    except Exception as e:
        apierr = str(e)

def getapibody(u: str, method: str, body: bytes, headers: dict) -> Tuple[Union[bytes, str], int]:
    global apierr
    if apierr: return apierr, 500
    if use_pipe:
        return simp_pipe(u, method, headers, body)
    global client
    try:
        s = {
            "GET": lambda: client.get(u, headers=headers),
            "POST": lambda: client.post(u, data=body, headers=headers),
            "DELETE": lambda: client.delete(u, data=body, headers=headers)
        }.get(method, lambda: "400 Bad Request: invalid method".encode())()
    except Exception as e:
        return "http2.client: " + str(e), 500
    if not isinstance(s, bytes):
        if s.status_code != 200:
            return "Error: " + method + " request to " + u + " => " + str(s.status_code) + "\n\n" + s.text, s.status_code
        d = s.content
        s.close()
        return d, s.status_code


def main(req: func.HttpRequest) -> func.HttpResponse:
    global pattern
    para = req.params.get("url")
    if not para or not pattern.match(para):
        return func.HttpResponse("400 Bad Requset: no url param", status_code=400)
    h = {}
    for k, v in req.headers.items(): h[k.lower()] = v
    d, s = getapibody(para, req.method, req.get_body(), h)
    if len(d): return func.HttpResponse(d, status_code=s)
    return func.HttpResponse("504 Gateway Timeout: Empty Response From Upstream", status_code=504)
