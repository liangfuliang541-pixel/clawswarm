"""
ClawSwarm Agent Spawner — Gateway WebSocket RPC
通过 Gateway WebSocket 直接调用 sessions.spawn
"""
import asyncio, json, os, time, base64, re, uuid
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────
GW_WS       = "ws://127.0.0.1:28789"
TOKEN       = "pXivTPMmUINF1zeIxGp8vsHLzgNrZoeCaLJRP1Rxhr0"
DEVICE_ID   = "e975c2f0412fd35a6dd1d805546353b1e5b6e4e566f3a8eee12841535f6e3c72"
PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIA25PFKWyhIavZqe09W2v+XETdDt5+kNT1VRiz6cmRaF
-----END PRIVATE KEY-----"""
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAVZFCGI69tKpU91Ib/jZuYY5twt4O8iW13wHd9KZLrTY=
-----END PUBLIC KEY-----"""


def _sign(payload: str) -> str:
    """Ed25519 sign"""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    key = load_pem_private_key(PRIVATE_KEY.encode(), password=None)
    return base64.urlsafe_b64encode(key.sign(payload.encode("utf8"))).rstrip(b"=").decode()


def _pubkey_raw() -> str:
    """Extract raw public key bytes, base64url encoded"""
    b64 = re.search(r"-----BEGIN PUBLIC KEY-----\s*([A-Za-z0-9+/=\s]+)\s*-----END", PUBLIC_KEY_PEM).group(1)
    der = base64.b64decode(re.sub(r"\s+", "", b64))
    return base64.urlsafe_b64encode(der[22:]).rstrip(b"=").decode()


def _build_device_payload(nonce: str, ts: int) -> str:
    return "|".join([
        "v3", DEVICE_ID, "gateway-client", "backend", "operator",
        "operator.admin,operator.approvals,operator.pairing,operator.read,operator.write",
        str(ts), TOKEN, nonce, "win32", "win32"
    ])


async def spawn_and_wait(message: str, label: str = "swarm-spawn",
                         timeout: int = 60, result_file: str = None) -> dict:
    """
    通过 Gateway WebSocket RPC spawn 子 agent，等待结果。
    """
    import websockets

    GW_VERSION = "2026.3.13"

    async def _do():
        async with websockets.connect(GW_WS, subprotocols=["v1.gateway"], close_timeout=10) as ws:
            # Step 1: 接收 challenge
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("event") != "connect.challenge":
                raise RuntimeError(f"Expected challenge, got: {raw[:200]}")
            nonce = msg["payload"]["nonce"]
            ts    = int(msg["payload"]["ts"])

            # Step 2: 签名 + 发送 connect RPC
            device_payload = _build_device_payload(nonce, ts)
            sig = _sign(device_payload)
            req_id = str(uuid.uuid4())

            await ws.send(json.dumps({
                "type": "req",
                "id": req_id,
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": "gateway-client",
                        "version": GW_VERSION,
                        "platform": "win32",
                        "deviceFamily": "win32",
                        "mode": "backend",
                    },
                    "caps": [],
                    "auth": {"token": TOKEN},
                    "role": "operator",
                    "scopes": ["operator.admin", "operator.approvals", "operator.pairing",
                                "operator.read", "operator.write"],
                    "device": {
                        "id": DEVICE_ID,
                        "publicKey": _pubkey_raw(),
                        "signature": sig,
                        "signedAt": ts,
                        "nonce": nonce,
                    },
                }
            }))

            # Step 3: 等待 auth 响应
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            resp = json.loads(raw)
            if resp.get("type") == "error" or resp.get("type") == "req.error":
                raise RuntimeError(f"Connect failed: {raw[:300]}")
            if resp.get("payload", {}).get("status") == "error":
                raise RuntimeError(f"Connect failed: {raw[:300]}")

            # Step 4: 发送 sessions.spawn RPC
            spawn_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": spawn_id,
                "method": "sessions.spawn",
                "params": {
                    "message": message,
                    "label": label,
                    "runtime": "subagent",
                    "mode": "run",
                    "timeoutSeconds": timeout,
                }
            }))

            # Step 5: 等待 spawn 响应
            start = time.time()
            spawn_resp = await asyncio.wait_for(ws.recv(), timeout=30)
            spawn_result = json.loads(spawn_resp)
            if spawn_result.get("type") == "error" or spawn_result.get("type") == "req.error":
                raise RuntimeError(f"Spawn failed: {spawn_resp[:300]}")

            session_key = (spawn_result.get("payload", {}).get("sessionKey")
                          or spawn_result.get("payload", {}).get("session_key")
                          or label)

            # Step 6: 等待 agent 完成
            deadline = start + timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
                    evt = json.loads(raw)
                    if evt.get("type") == "event":
                        event = evt.get("event", "")
                        pl = evt.get("payload", {})
                        if event in ("sessions.done", "sessions.output", "agent.done", "agent.output"):
                            return {
                                "status": "success",
                                "output": pl.get("output") or pl.get("result") or json.dumps(pl),
                                "session_key": session_key,
                                "elapsed": time.time() - start,
                            }
                except asyncio.TimeoutError:
                    break

            return {
                "status": "timeout",
                "output": f"Agent did not complete within {timeout}s",
                "session_key": session_key,
                "elapsed": time.time() - start,
            }

    start = time.time()
    try:
        result = await asyncio.wait_for(_do(), timeout=timeout + 90)
    except asyncio.TimeoutError:
        result = {"status": "timeout", "output": "Request timed out", "elapsed": time.time() - start}
    except Exception as e:
        result = {"status": "error", "output": str(e), "elapsed": time.time() - start}

    if result_file:
        Path(result_file).parent.mkdir(parents=True, exist_ok=True)
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def spawn_async(message: str, label: str = "swarm-spawn",
                timeout: int = 60, result_file: str = None) -> str:
    """后台线程执行 spawn"""
    import threading
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(spawn_and_wait(message, label=label, timeout=timeout, result_file=result_file))
        finally:
            loop.close()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return f"swarm-{label}-{int(time.time())}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Spawn OpenClaw agent via Gateway WebSocket")
    parser.add_argument("message")
    parser.add_argument("--label", default="swarm")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--result-file")
    args = parser.parse_args()
    result = asyncio.run(spawn_and_wait(args.message, label=args.label,
                                       timeout=args.timeout, result_file=args.result_file))
    print(json.dumps(result, ensure_ascii=False))
