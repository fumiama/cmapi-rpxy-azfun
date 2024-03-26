import re
import requests
from os import getenv
from typing import Tuple, Union

import azure.functions as func


use_proxy = not not getenv("CMAPI_USE_PROXY", False)
use_pipe = not not getenv("CMAPI_USE_PIPE", False)

pattern = re.compile(r'^https://api\.(copymanga|mangacopy)\.\w+/api/')

apierr = None

if not use_pipe and use_proxy:
    from ftea import TEA
    from time import time
    import struct
    import subprocess
    from pathlib import Path
    from urllib.parse import quote

    # extracted from https://code.launchpad.net/~fumiama/+archive/ubuntu/ppa/+build/27959779
    b14_path = str(Path(__file__).parent.parent/'usr'/'bin'/'base16384')

    def b14_encode(b: bytes) -> Tuple[bytes, bytes]:
        process = subprocess.Popen([b14_path, '-e', '-', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output_bytes, err = process.communicate(input=b)
        return output_bytes[2:], err

    def b14_decode(b: bytes) -> Tuple[bytes, bytes]:
        process = subprocess.Popen([b14_path, '-d', '-', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output_bytes, err = process.communicate(input=b)
        return output_bytes, err

    def b14_encode_string(data: str) -> str:
        try:
            d, err = b14_encode(data.encode())
            if not d: return "Error: zero encode result: " + err.decode()
            return d.decode("utf-16-be")
        except Exception as e:
            return "b14_encode_string: " + str(e)

    def b14_encode_to_string(data: bytes) -> str:
        try:
            d, err = b14_encode(data)
            if not d: return "Error: zero decode result: " + err.decode()
            return d.decode("utf-16-be")
        except Exception as e:
            return "b14_encode_to_string: " + str(e)

    def b14_decode_from_string(data: str) -> bytes:
        d, err = b14_decode(data.encode("utf-16-be"))
        if not d: return err
        return d

    try:
        api = getenv("CMAPI_REMOTE_API")
        tea = TEA(b14_decode_from_string(getenv("CMAPI_REMOTE_KEY") + "㴂"))
    except Exception as e:
        apierr = str(e)
elif use_pipe:
    import subprocess
    import struct
    from pathlib import Path
    from json import dumps, loads
    from base64 import b64decode, b64encode
    from urllib3.response import MultiDecoder

    simp_path = str(Path(__file__).parent.parent/'simp')

    def simp_pipe(u: str, method: str, headers: dict, body: Union[bytes, None] = None) -> Union[bytes, int]:
        cap = {
            "M": method,
            "H": headers,
            "D": u,
        }
        data = "Null".encode()
        try:
            with subprocess.Popen([simp_path, '-pipe', dumps(cap)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE) as process:
                if body and len(body):
                    process.stdin.write(struct.pack("<q", len(body)))
                    process.stdin.write(body)
                else: process.stdin.write(b'\x00\x00\x00\x00\x00\x00\x00\x00')
                process.stdin.close()
                data = process.stdout.read(struct.unpack("<q", process.stdout.read(8))[0])
                process.stdout.close()
                err = process.stderr.read()
                process.stderr.close()
                process.wait()
                if len(err): return ("simp_pipe: " + err.decode()).encode(), 500
                cap = loads(data)
                data = b64decode(cap["D"])
                coding = cap["H"].get("Content-Encoding", None)
                if coding:
                    data = MultiDecoder(coding).decompress(data)
                return data, cap["C"]
        except Exception as e:
            return ("simp_pipe: " + str(e) + "\n\n" + b64encode(data).decode()).encode(), 500
else:
    import httpx
    try:
        client = httpx.Client(http2=True)
    except Exception as e:
        apierr = str(e)

def getapibody(u: str, method: str, body: bytes, headers: dict) -> Tuple[Union[bytes, str], int]:
    global apierr
    if apierr: return apierr, 500
    if use_pipe:
        return simp_pipe(u, method, headers, body)
    if not use_proxy:
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
        else: return s, 400
    global api, tea
    remu = api + "/" + quote(b14_encode_string(u))
    try:
        headers["cmapiauth"] = quote(tea.encrypt_qq(struct.pack("<q", int(time()*1000))))
        if body and len(body): body = tea.encrypt_qq(body)
    except Exception as e:
        return "b14_encode_to_string/tea.encrypt_qq: " + str(e), 500
    try:
        s = {
            "GET": lambda: requests.get(remu, data=body, headers=headers),
            "POST": lambda: requests.post(remu, data=body, headers=headers),
            "DELETE": lambda: requests.delete(remu, data=body, headers=headers)
        }.get(method, lambda: "400 Bad Request: invalid method".encode())()
    except Exception as e:
        return "requests: " + str(e), 500
    if not isinstance(s, bytes):
        if s.status_code != 200:
            return "Error: " + method + " request to " + u + " => " + str(s.status_code) + " " + s.reason + "\n\n" + s.text, s.status_code
        d = s.content
        s.close()
        return d, s.status_code
    else: return s, 400

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
