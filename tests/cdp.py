"""Helper di test: esegue JavaScript nella finestra WebView2 dell'app via DevTools Protocol.

Richiede l'app avviata con la variabile ACESTEP_APP_DEBUG_PORT (es. 9333).
Uso:  python tests/cdp.py <porta> "<espressione js>"
"""

import json
import sys
import urllib.request

import websocket


def evaluate(port, expr, timeout=30):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    targets = json.load(opener.open(f"http://127.0.0.1:{port}/json", timeout=5))
    page = next(t for t in targets if t["type"] == "page")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                res = msg["result"]
                if "exceptionDetails" in res:
                    return {"error": res["exceptionDetails"].get("text"), "detail": res.get("result")}
                return res["result"].get("value")
    finally:
        ws.close()


if __name__ == "__main__":
    print(json.dumps(evaluate(int(sys.argv[1]), sys.argv[2]), ensure_ascii=False, indent=1))
