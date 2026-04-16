"""
ClawSwarm Pairing — 龙虾一键互联

通过配对码实现零配置节点互联：
1. 节点A 生成配对码
2. 节点B 输入配对码连接
3. Relay Server 中转握手，双方获得对方 gateway URL
4. 后续直接 P2P 通信（或继续用 relay）
"""

import json
import threading
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any


class PairingError(Exception):
    """Pairing 相关错误"""
    pass


class ClawPairing:
    """
    ClawSwarm 一键配对客户端

    用法（节点A，生成本节点配对码）：
        pairing = ClawPairing(
            relay_url="http://localhost:18080",
            node_id="node-A",
            gateway_url="http://localhost:18789",
            token="secret",
        )
        code = pairing.generate_code()
        print(f"配对码: {code}")  # 分享给节点B

    用法（节点B，使用配对码连接）：
        pairing = ClawPairing(...)
        result = pairing.connect_with_code(code)
        peer = pairing.get_peer_info()
    """

    def __init__(
        self,
        relay_url: str,
        node_id: str,
        gateway_url: str,
        token: str,
    ):
        self.relay_url = relay_url.rstrip("/")
        self.node_id = node_id
        self.gateway_url = gateway_url
        self.token = token
        self._current_peer: Optional[Dict[str, Any]] = None
        self._status_cache: Optional[Dict[str, Any]] = None
        self._last_code: Optional[str] = None

    # ── 底层 HTTP ────────────────────────────────────────────────────────

    def _get(self, path: str) -> Dict[str, Any]:
        """GET 请求到 relay"""
        url = f"{self.relay_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                body = json.loads(body)
            except Exception:
                pass
            raise PairingError(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise PairingError(f"Connection failed: {e.reason}")
        except Exception as e:
            raise PairingError(f"Unexpected error: {e}")

    def _post(self, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """POST JSON 请求到 relay"""
        url = f"{self.relay_url}{path}"
        body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode("utf-8")
            try:
                resp_body = json.loads(resp_body)
            except Exception:
                pass
            raise PairingError(f"HTTP {e.code}: {resp_body}")
        except urllib.error.URLError as e:
            raise PairingError(f"Connection failed: {e.reason}")
        except Exception as e:
            raise PairingError(f"Unexpected error: {e}")

    # ── 配对码生成 ──────────────────────────────────────────────────────

    def generate_code(self) -> str:
        """
        生成本节点的配对码（供其他节点连接）

        Returns:
            str: 6位配对码

        Raises:
            PairingError: 生成失败
        """
        result = self._get(f"/pairing/generate?node_id={self.node_id}")
        code = result.get("code")
        if not code:
            raise PairingError(f"Failed to generate code: {result}")
        self._last_code = code
        self._status_cache = result
        return code

    # ── 连接 ────────────────────────────────────────────────────────────

    def connect_with_code(self, code: str) -> Dict[str, Any]:
        """
        使用配对码连接对方节点

        Args:
            code: 对方生成的6位配对码

        Returns:
            dict: {
                "status": "connected",
                "partner": {"node_id": ..., "node_info": ...},
                "self": {"node_id": ..., "node_info": ...}
            }

        Raises:
            PairingError: 连接失败（无效码/已使用/不能连自己）
        """
        result = self._post(f"/pairing/connect/{code}", {
            "node_id": self.node_id,
            "node_info": {
                "gateway_url": self.gateway_url,
                "capabilities": [],  # 可扩展
            },
        })
        if "error" in result:
            raise PairingError(f"{result.get('error')}: {result.get('message', '')}")

        self._current_peer = result.get("partner")
        self._status_cache = result
        return result

    # ── 等待连接 ────────────────────────────────────────────────────────

    def wait_for_connection(self, timeout: int = 60) -> Optional[Dict[str, Any]]:
        """
        阻塞等待对端使用配对码连接本节点（轮询 status 端点）

        配合 generate_code() 使用：
            code = pairing.generate_code()
            # 把 code 分享给对端，让对端调用 connect_with_code(code)
            peer = pairing.wait_for_connection(timeout=60)

        Args:
            timeout: 超时时间（秒）

        Returns:
            对端节点信息 dict，或 None（超时）
        """
        if not self._last_code:
            raise PairingError("No code to wait for. Call generate_code() first.")

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                status = self._get(f"/pairing/status/{self._last_code}")
            except PairingError:
                time.sleep(1)
                continue

            if status.get("status") == "connected":
                self._current_peer = status.get("partner")
                self._status_cache = status
                return self._current_peer
            elif status.get("status") == "expired":
                raise PairingError("配对码已过期")
            elif status.get("status") == "ALREADY_USED":
                raise PairingError("配对码已被使用")

            time.sleep(1)

        return None  # 超时

    # ── 对端信息 ────────────────────────────────────────────────────────

    def get_peer_info(self) -> Optional[Dict[str, Any]]:
        """
        获取已连接对端的信息

        Returns:
            dict: {"node_id": ..., "node_info": ...} 或 None（未连接）
        """
        return self._current_peer

    def get_connection_status(self, code: str = None) -> Optional[Dict[str, Any]]:
        """
        查询配对状态（不轮询）

        Args:
            code: 配对码（不传则用最近一次生成的码）

        Returns:
            dict: 配对状态信息
        """
        code = code or self._last_code
        if not code:
            return None
        try:
            return self._get(f"/pairing/status/{code}")
        except PairingError:
            return None
