"""
ClawSwarm 龙虾间通信协议库

用法:
    from inter_agent_protocol import AgentClient

    # 连接到 relay
    relay = AgentClient("https://your-relay-serveo-url", agent_id="kimi-claw")

    # 给自己发一条消息测试连通性
    relay.ping()

    # 发消息给主龙虾
    relay.send_to("main-agent", "你好，我是 KimiClaw！")

    # 检查有没有发给我的消息
    messages = relay.check_inbox()
    for msg in messages:
        print(f"来自 {msg['from']}: {msg['content']}")

    # 主龙虾的命令轮询（可选，兼容旧的 cmd 模式）
    cmd = relay.poll_command()
    if cmd:
        result = execute(cmd)
        relay.report_done(cmd, result)
"""

import json
import time
import urllib.request
import ssl
from typing import Optional, List


class AgentClient:
    """
    龙虾间通信客户端。
    通过 relay server 的 HTTP API 与其他龙虾通信。
    """

    def __init__(self, relay_url: str, agent_id: str, timeout: int = 10):
        self.relay_url = relay_url.rstrip("/")
        self.agent_id = agent_id
        self.timeout = timeout
        self._ctx = ssl.create_default_context()
        self._last_health_check = 0
        self._health_cache = None

    # ── 低层 HTTP ──────────────────────────────────────────────────────

    def _get(self, path: str) -> dict:
        url = f"{self.relay_url}{path}"
        try:
            r = urllib.request.urlopen(url, context=self._ctx, timeout=self.timeout)
            return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise AgentError(f"HTTP {e.code}: {body}")

    def _post(self, path: str, data: bytes = b"") -> dict:
        url = f"{self.relay_url}{path}"
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            r = urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout)
            return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise AgentError(f"HTTP {e.code}: {body}")

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.relay_url + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            r = urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout)
            return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise AgentError(f"HTTP {e.code}: {body}")

    # ── 健康检查 ────────────────────────────────────────────────────────

    def health(self, use_cache: bool = True) -> dict:
        """返回 relay 健康状态"""
        now = time.time()
        if use_cache and self._health_cache and (now - self._last_health_check) < 5:
            return self._health_cache
        try:
            self._health_cache = self._get("/health")
            self._last_health_check = now
            return self._health_cache
        except Exception:
            return {"status": "error"}

    def ping(self) -> bool:
        """给自己发一条 ping 消息，测试连通性"""
        try:
            r = self._post(f"/msg/{self.agent_id}/{self.agent_id}", b"ping")
            return r.get("ok", False)
        except Exception:
            return False

    # ── 注册 ───────────────────────────────────────────────────────────

    def register(self, capabilities: List[str] = None, **extra) -> dict:
        """注册到 relay"""
        payload = {
            "node_id": self.agent_id,
            "name": self.agent_id,
            "capabilities": capabilities or ["exec", "fetch"],
            **extra,
        }
        return self._post_json("/register", payload)

    def heartbeat(self) -> dict:
        """心跳保活"""
        return self._post(f"/heartbeat/{self.agent_id}")

    # ── 消息收件箱 ─────────────────────────────────────────────────────

    def check_inbox(self, peek: bool = False) -> List[dict]:
        """
        检查收件箱。
        默认 peek=False：取走消息（下次 check 不会重复收到）。
        peek=True：只瞄一眼，不删除。
        """
        suffix = "/peek" if peek else ""
        try:
            r = self._get(f"/inbox/{self.agent_id}{suffix}")
            return r.get("messages", [])
        except AgentError:
            return []

    def send_to(self, target_agent: str, content: str, msg_type: str = "text") -> dict:
        """发送消息给另一个龙虾"""
        payload = json.dumps({"content": content, "type": msg_type}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.relay_url}/msg/{self.agent_id}/{target_agent}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            return json.loads(
                urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout).read()
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise AgentError(f"HTTP {e.code}: {body}")

    # ── 命令队列（兼容旧模式）──────────────────────────────────────────

    def poll_command(self) -> Optional[str]:
        """轮询待执行的命令（旧的 cmd 模式）"""
        try:
            r = self._get(f"/poll/{self.agent_id}")
            return r.get("command") or None
        except AgentError:
            return None

    def report_done(self, command: str, result: str, status: str = "ok") -> dict:
        """提交命令执行结果"""
        data = json.dumps({"command": command, "result": result, "status": status}).encode()
        return self._post(f"/done/{self.agent_id}", data)

    def get_result(self) -> Optional[dict]:
        """获取执行结果（旧的 result 模式）"""
        try:
            return self._get(f"/result/{self.agent_id}")
        except AgentError:
            return None

    # ── 节点查询 ───────────────────────────────────────────────────────

    def list_agents(self) -> List[dict]:
        """列出 relay 上所有注册的 agent"""
        try:
            r = self._get("/agents")
            return r.get("agents", [])
        except AgentError:
            return []

    # ── 高级：消息循环 ─────────────────────────────────────────────────

    def message_loop(self, handler, poll_interval: float = 3.0, max_iterations: int = None):
        """
        简单的消息处理循环。
        handler(msg: dict) -> None，被调用处理每条消息。
        按 Ctrl+C 停止。
        """
        iteration = 0
        print(f"[{self.agent_id}] 开始消息循环，relay={self.relay_url}，间隔={poll_interval}s")
        try:
            while True:
                iteration += 1
                if max_iterations and iteration > max_iterations:
                    break
                messages = self.check_inbox()
                for msg in messages:
                    try:
                        handler(msg)
                    except Exception as ex:
                        print(f"[{self.agent_id}] 处理消息出错: {ex}")
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print(f"\n[{self.agent_id}] 消息循环停止")


class AgentError(Exception):
    """AgentClient 操作异常"""
    pass


# ── 快捷函数 ───────────────────────────────────────────────────────────

def send_message(relay_url: str, from_agent: str, to_agent: str, content: str) -> dict:
    """一行发送消息"""
    client = AgentClient(relay_url, from_agent)
    return client.send_to(to_agent, content)


def check_messages(relay_url: str, agent_id: str) -> List[dict]:
    """一行检查消息"""
    client = AgentClient(relay_url, agent_id)
    return client.check_inbox()
