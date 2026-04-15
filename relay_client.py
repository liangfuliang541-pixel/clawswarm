"""
ClawSwarm Relay Client — 跨公网节点通信客户端

通过 HTTP Relay 中转，实现对远程 OpenClaw 节点的命令控制。

原理：
    我的 Windows → HTTPS POST /cmd → serveo.net 隧道 → Kimi Claw(Ubuntu)
                          ↓
                     /result 轮询 ← 我的 Windows

使用场景：
    - 远程节点 gateway 在 loopback，无法直连
    - 两台机器不在同一局域网
    - 需要 AI Agent 之间跨公网协作

用法：
    from relay_client import RemoteRelay, RemoteNode

    # 方式1：直接命令
    relay = RemoteRelay("https://xxxx.serveo.net")
    result = relay.exec("echo hello")
    print(result)

    # 方式2：作为节点注册到集群
    node = RemoteNode(
        node_id="kimi-claw-01",
        relay_url="https://xxxx.serveo.net",
        capabilities=["shell", "openclaw", "web"]
    )
    node.register()
    result = node.exec("openclaw gateway status")
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, List, Any
from pathlib import Path


# ── 配置文件路径 ─────────────────────────────────────────────────────────

RELAY_CONFIG_DIR = Path(__file__).parent / "swarm_data" / "remote_nodes"
RELAY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = 60  # 命令执行超时（秒）
POLL_INTERVAL = 2    # 轮询间隔（秒）


# ── 核心 Relay 客户端 ────────────────────────────────────────────────────

class RelayError(Exception):
    """Relay 相关错误"""
    pass


class RemoteRelay:
    """
    HTTP Relay 客户端
    
    通过 HTTP POST /cmd 发送命令，GET /result 获取结果。
    命令在远程端执行，结果通过同一 Relay 中转返回。
    """

    def __init__(self, relay_url: str, timeout: int = DEFAULT_TIMEOUT):
        """
        Args:
            relay_url: Relay 服务的公网地址，例如 https://xxxx.serveo.net
            timeout: 命令执行超时（秒）
        """
        self.relay_url = relay_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, data: str) -> str:
        """POST 数据到 relay"""
        url = f"{self.relay_url}{path}"
        try:
            req = urllib.request.Request(
                url,
                data=data.encode("utf-8"),
                method="POST"
            )
            req.add_header("Content-Type", "text/plain")
            req.add_header("Content-Length", str(len(data)))
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise RelayError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RelayError(f"Connection failed: {e.reason}")
        except Exception as e:
            raise RelayError(f"Unexpected error: {e}")

    def _get(self, path: str) -> str:
        """GET 数据从 relay"""
        url = f"{self.relay_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""  # 空结果是正常的
            raise RelayError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RelayError(f"Connection failed: {e.reason}")
        except Exception as e:
            raise RelayError(f"Unexpected error: {e}")

    def ping(self) -> bool:
        """测试 relay 连通性"""
        try:
            cursor = self._get("/poll")
            return True
        except RelayError:
            return False

    def exec(
        self,
        command: str,
        wait: bool = True,
        poll_interval: float = POLL_INTERVAL,
        cwd: str = "/root",
        timeout: int = None,
    ) -> Dict[str, Any]:
        """
        发送命令到远程节点并获取结果

        Args:
            command: 要执行的 shell 命令
            wait: 是否等待结果（True=同步阻塞，False=只发送）
            poll_interval: 轮询间隔（秒）
            cwd: 远程工作目录
            timeout: 命令执行超时（秒），覆盖默认值

        Returns:
            dict: {
                "status": "ok"|"error"|"timeout",
                "output": 命令输出,
                "elapsed": 耗时（秒）,
                "command": 原命令
            }
        """
        start = time.time()
        max_wait = timeout if timeout is not None else self.timeout

        # 构建带 cwd 的包装命令
        wrapped_cmd = f'cd {cwd} && {command}'

        try:
            resp = self._post("/cmd", wrapped_cmd)
            if resp != "OK":
                raise RelayError(f"Remote rejected command: {resp}")
        except RelayError:
            raise

        if not wait:
            return {
                "status": "sent",
                "command": command,
                "elapsed": round(time.time() - start, 3),
            }

        # 轮询等待结果
        deadline = start + max_wait
        while time.time() < deadline:
            result = self._get("/result")
            if result:
                elapsed = round(time.time() - start, 3)
                return {
                    "status": "ok",
                    "output": result,
                    "elapsed": elapsed,
                    "command": command,
                }
            time.sleep(poll_interval)

        return {
            "status": "timeout",
            "output": "",
            "elapsed": max_wait,
            "command": command,
        }

    def get_status(self) -> Dict[str, Any]:
        """获取 relay 和远程节点状态"""
        relay_ok = self.ping()
        cursor = self._get("/poll") if relay_ok else ""

        return {
            "relay_url": self.relay_url,
            "relay_reachable": relay_ok,
            "pending_command": cursor,
        }


# ── 远程节点 ────────────────────────────────────────────────────────────

class RemoteNode:
    """
    远程 OpenClaw 节点（通过 Relay 通信）
    
    将远程节点注册为 ClawSwarm 集群的一员，
    支持命令执行、状态查询、任务分发。
    """

    def __init__(
        self,
        node_id: str,
        relay_url: str,
        name: str = None,
        capabilities: List[str] = None,
        gateway_port: int = 18789,
    ):
        """
        Args:
            node_id: 节点唯一ID
            relay_url: HTTP Relay 公网地址
            name: 节点显示名
            capabilities: 节点能力列表
            gateway_port: 远程 OpenClaw gateway 端口（默认 18789）
        """
        self.node_id = node_id
        self.name = name or node_id
        self.relay = RemoteRelay(relay_url)
        self.capabilities = capabilities or ["shell", "general"]
        self.gateway_port = gateway_port
        self.config_file = RELAY_CONFIG_DIR / f"{node_id}.json"

    def register(self) -> Dict[str, Any]:
        """将节点注册到 ClawSwarm 本地节点列表"""
        config = {
            "node_id": self.node_id,
            "name": self.name,
            "type": "remote",           # 区别于本地节点
            "relay_url": self.relay.relay_url,
            "capabilities": self.capabilities,
            "gateway_port": self.gateway_port,
            "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return {"status": "registered", "node_id": self.node_id, "config": str(self.config_file)}

    def unregister(self) -> None:
        """从集群注销节点"""
        if self.config_file.exists():
            self.config_file.unlink()

    def exec(self, command: str, wait: bool = True) -> Dict[str, Any]:
        """
        在远程节点上执行命令（通过 Relay）

        Returns:
            dict: {"status": "ok"|"error"|"timeout", "output": ..., "elapsed": ...}
        """
        # 先更新 last_seen
        self._touch()
        return self.relay.exec(command, wait=wait)

    def get_openclaw_status(self) -> Dict[str, Any]:
        """获取远程 OpenClaw gateway 状态"""
        result = self.exec("openclaw gateway status", wait=True)
        if result["status"] == "ok":
            return {
                "node_id": self.node_id,
                "gateway_status": "ok",
                "output": result["output"],
            }
        return {
            "node_id": self.node_id,
            "gateway_status": "error",
            "error": result.get("output", result.get("status")),
        }

    def get_info(self) -> Dict[str, Any]:
        """获取节点详细信息"""
        relay_status = self.relay.get_status()
        return {
            "node_id": self.node_id,
            "name": self.name,
            "type": "remote",
            "relay_url": self.relay.relay_url,
            "capabilities": self.capabilities,
            "gateway_port": self.gateway_port,
            "relay_reachable": relay_status["relay_reachable"],
            "pending_command": relay_status["pending_command"],
            "config_file": str(self.config_file),
        }

    def _touch(self) -> None:
        """更新最后访问时间"""
        if self.config_file.exists():
            try:
                config = json.loads(self.config_file.read_text(encoding="utf-8"))
                config["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass


# ── 远程节点管理器 ────────────────────────────────────────────────────────

class RemoteNodeManager:
    """管理所有远程节点（从配置文件加载）"""

    def __init__(self):
        self.nodes: Dict[str, RemoteNode] = {}
        self._load_all()

    def _load_all(self) -> None:
        """加载所有已注册的远程节点"""
        for cfg_file in RELAY_CONFIG_DIR.glob("*.json"):
            try:
                config = json.loads(cfg_file.read_text(encoding="utf-8"))
                node = RemoteNode(
                    node_id=config["node_id"],
                    relay_url=config["relay_url"],
                    name=config.get("name"),
                    capabilities=config.get("capabilities"),
                    gateway_port=config.get("gateway_port", 18789),
                )
                self.nodes[node.node_id] = node
            except Exception:
                pass

    def register(self, node: RemoteNode) -> Dict[str, Any]:
        """注册新节点"""
        result = node.register()
        self.nodes[node.node_id] = node
        return result

    def list_nodes(self) -> List[Dict[str, Any]]:
        """列出所有远程节点"""
        return [n.get_info() for n in self.nodes.values()]

    def get_node(self, node_id: str) -> Optional[RemoteNode]:
        return self.nodes.get(node_id)

    def exec_on_node(self, node_id: str, command: str) -> Dict[str, Any]:
        """在指定节点执行命令"""
        node = self.nodes.get(node_id)
        if not node:
            return {"error": f"Node not found: {node_id}"}
        return node.exec(command)


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def quick_exec(relay_url: str, command: str, wait: bool = True) -> Dict[str, Any]:
    """
    一行代码执行远程命令（最简用法）
    
    Example:
        result = quick_exec("https://xxxx.serveo.net", "echo hello")
        print(result["output"])
    """
    relay = RemoteRelay(relay_url)
    return relay.exec(command, wait=wait)


# ── 测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("RemoteRelay 测试")
    print("=" * 50)

    # 读取本地配置（如果存在）
    config_file = RELAY_CONFIG_DIR / "kimi-claw-01.json"
    if config_file.exists():
        config = json.loads(config_file.read_text(encoding="utf-8"))
        relay_url = config["relay_url"]
        node_id = config["node_id"]
        print(f"找到已注册节点: {node_id}")
    else:
        print("未找到已注册节点，使用默认配置")
        relay_url = "https://dd99b12fac29647c-82-157-104-41.serveousercontent.com"
        node_id = "test-remote"

    # 测试 relay
    relay = RemoteRelay(relay_url)
    print(f"\nRelay URL: {relay_url}")
    print(f"连通性测试: {'✅' if relay.ping() else '❌'}")

    # 测试执行
    print("\n执行测试命令...")
    result = relay.exec("echo 'Hello from Remote!' && date && hostname && uname -a | head -1")
    print(f"状态: {result['status']}")
    print(f"耗时: {result['elapsed']}s")
    print(f"输出:\n{result['output']}")

    print("\n测试完成!")
