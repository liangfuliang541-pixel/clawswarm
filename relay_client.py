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

    # ── 节点注册与发现（Relay 新端点）────────────────────────────────

    def register(
        self,
        node_id: str,
        gateway_url: str,
        token: str,
        capabilities: List[str],
        name: str = None,
    ) -> Dict[str, Any]:
        """
        向 Relay Server 注册本节点

        Args:
            node_id: 节点唯一ID
            gateway_url: 节点 gateway URL
            token: 认证 token
            capabilities: 节点能力列表
            name: 显示名称

        Returns:
            dict: 注册结果（Relay 返回，不含 token）
        """
        payload = {
            "node_id": node_id,
            "gateway_url": gateway_url,
            "token": token,
            "capabilities": capabilities,
        }
        if name:
            payload["name"] = name

        url = f"{self.relay_url}/register"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result
        except urllib.error.HTTPError as e:
            raise RelayError(f"HTTP {e.code}: {e.read().decode('utf-8')}")
        except urllib.error.URLError as e:
            raise RelayError(f"Connection failed: {e.reason}")

    def heartbeat(self, node_id: str) -> bool:
        """
        向 Relay Server 发送心跳

        Args:
            node_id: 节点ID

        Returns:
            bool: 是否成功
        """
        url = f"{self.relay_url}/heartbeat/{node_id}"
        try:
            req = urllib.request.Request(url, data=b"{}", method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("status") == "ok"
        except Exception:
            return False

    def discover(self) -> List[Dict[str, Any]]:
        """
        从 Relay 发现所有已注册的节点

        Returns:
            list: 节点列表（不含 token）
        """
        url = f"{self.relay_url}/nodes"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                nodes = result.get("nodes", [])
                # 剔除 token 字段
                return [{k: v for k, v in n.items() if k != "token"} for n in nodes]
        except urllib.error.HTTPError as e:
            raise RelayError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RelayError(f"Connection failed: {e.reason}")


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

        # 测试 relay 连通性
        connection_ok = self.relay.ping()
        return {
            "status": "registered",
            "node_id": self.node_id,
            "config": str(self.config_file),
            "connection_test": "ok" if connection_ok else "failed",
        }

    def unregister(self) -> None:
        """从集群注销节点"""
        if self.config_file.exists():
            self.config_file.unlink()

    def exec(self, command: str, wait: bool = True, timeout: int = None) -> Dict[str, Any]:
        """
        在远程节点上执行命令（通过 Relay）

        Returns:
            dict: {"status": "ok"|"error"|"timeout", "output": ..., "elapsed": ...}
        """
        # 先更新 last_seen
        self._touch()
        return self.relay.exec(command, wait=wait, timeout=timeout)

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

    def check_health(self, node_id: str = None) -> Dict[str, Any]:
        """
        对已注册的远程节点执行健康检查。

        检查内容：
        - Relay 连通性（ping）
        - 远程 OpenClaw gateway 状态
        - 响应时间测量

        检查结果写入 health/{node_id}.json（每节点一个文件）。

        Args:
            node_id: 指定节点 ID（不传则检查所有已注册节点）

        Returns:
            dict: {
                "total": int,       # 检查的节点总数
                "healthy": int,     # 健康节点数
                "unhealthy": int,   # 不健康节点数
                "nodes": [          # 每节点详细结果
                    {
                        "node_id": str,
                        "node_name": str,
                        "relay_reachable": bool,
                        "gateway_status": str,   # "ok" | "error" | "unreachable"
                        "response_time_ms": float,
                        "last_heartbeat": str,   # ISO timestamp
                        "capabilities": list,
                        "health_file": str,       # 写入路径
                    }
                ]
            }
        """
        HEALTH_DIR = BASE_DIR / "health"
        HEALTH_DIR.mkdir(parents=True, exist_ok=True)

        # 确定要检查的节点列表
        if node_id:
            target_nodes = [self.nodes[node_id]] if node_id in self.nodes else []
        else:
            target_nodes = list(self.nodes.values())

        results = []
        healthy_count = 0
        unhealthy_count = 0

        for node in target_nodes:
            start = time.time()
            relay_reachable = False
            gateway_status = "unreachable"
            response_time_ms = None

            try:
                # 1. 测试 relay 连通性（ping）
                relay_reachable = node.relay.ping()
                response_time_ms = round((time.time() - start) * 1000, 1)

                if relay_reachable:
                    # 2. 尝试获取远程 gateway 状态
                    try:
                        status_result = node.exec("openclaw gateway status", wait=True, timeout=10)
                        if status_result.get("status") == "ok":
                            gateway_status = "ok"
                        else:
                            gateway_status = "error"
                    except Exception:
                        gateway_status = "error"
                else:
                    gateway_status = "unreachable"

            except Exception:
                relay_reachable = False
                gateway_status = "unreachable"

            # 判断健康状态
            is_healthy = relay_reachable and gateway_status == "ok"

            # 构建健康报告
            health_file = HEALTH_DIR / f"{node.node_id}.json"
            health_record = {
                "node_id": node.node_id,
                "node_name": node.name,
                "relay_reachable": relay_reachable,
                "gateway_status": gateway_status,
                "response_time_ms": response_time_ms,
                "last_check": time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_healthy": is_healthy,
                "capabilities": node.capabilities,
                "relay_url": node.relay.relay_url,
            }

            # 写入健康状态文件
            try:
                with open(health_file, "w", encoding="utf-8") as f:
                    json.dump(health_record, f, ensure_ascii=False, indent=2)
                health_file_path = str(health_file)
            except Exception as e:
                health_file_path = f"WRITE_ERROR: {e}"

            if is_healthy:
                healthy_count += 1
            else:
                unhealthy_count += 1

            results.append({
                "node_id": node.node_id,
                "node_name": node.name,
                "relay_reachable": relay_reachable,
                "gateway_status": gateway_status,
                "response_time_ms": response_time_ms,
                "last_heartbeat": time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_healthy": is_healthy,
                "capabilities": node.capabilities,
                "health_file": health_file_path,
            })

        return {
            "total": len(target_nodes),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
            "nodes": results,
        }


# ── 远程任务执行器 ────────────────────────────────────────────────────────

def create_task_via_relay(
    task_id: str,
    prompt: str,
    node: "RemoteNode",
    timeout: int = 60,
    task_type: str = "general",
) -> Dict[str, Any]:
    """
    在远程节点上执行 ClawSwarm 任务。

    Args:
        task_id:    任务ID（用于写入本地 results/ 目录）
        prompt:     任务描述
        node:       RemoteNode 实例
        timeout:    执行超时（秒）
        task_type:  任务类型（shell/fetch/general/code等）
                    shell 类型会包装为 bash -c "..." 格式

    Returns:
        dict: {"status": "ok"|"error"|"timeout"|"sent", "output": ..., "elapsed": ...}
    """
    start = time.time()

    # 根据 task_type 包装命令
    if task_type == "shell":
        # 避免单引号干扰，使用双引号并转义内部双引号
        escaped_prompt = prompt.replace('"', '\\"')
        command = f'bash -c "{escaped_prompt}"'
    else:
        command = prompt

    # 发送任务到远程节点
    result = node.exec(command, wait=True, timeout=timeout)

    # 写入本地 results/ 目录，供 orchestrator 的 ResultWatcher 读取
    from paths import RESULTS_DIR
    import os as _os
    result_file = _os.path.join(RESULTS_DIR, f"r_{task_id}.json")
    output_data = {
        "task_id": task_id,
        "status": result.get("status", "done"),
        "result": result.get("output", ""),
        "elapsed": result.get("elapsed", 0),
        "node_type": "remote",
        "node_id": node.node_id,
    }
    try:
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass  # 非关键错误，不影响返回

    result["node_type"] = "remote"
    result["node_id"] = node.node_id
    return result


def exec_task_async_via_relay(
    task_id: str,
    prompt: str,
    node_or_dict,
    timeout: int = 60,
    task_type: str = "general",
) -> None:
    """
    后台线程执行远程任务（不阻塞 orchestrator 主流程）。
    任务完成后自动写入 results/r_{task_id}.json。

    Args:
        node_or_dict: RemoteNode 实例或 dict（from get_online_nodes 返回）
        task_id:     任务ID
        prompt:      任务描述/命令
        node:        RemoteNode 实例
        timeout:     执行超时（秒）
        task_type:   任务类型（shell/fetch/general/code等）
    """
    import threading

    def _run():
        try:
            # 转换 dict → RemoteNode
            if isinstance(node_or_dict, dict):
                actual_node = RemoteNode(
                    node_id=node_or_dict["node_id"],
                    relay_url=node_or_dict["relay_url"],
                    name=node_or_dict.get("name"),
                    capabilities=node_or_dict.get("capabilities"),
                )
            else:
                actual_node = node_or_dict
            create_task_via_relay(task_id, prompt, actual_node, timeout, task_type=task_type)
        except Exception as e:
            from paths import RESULTS_DIR
            import os as _os
            result_file = _os.path.join(RESULTS_DIR, f"r_{task_id}.json")
            node_id_for_result = getattr(actual_node, 'node_id', 'unknown')
            try:
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "task_id": task_id,
                        "status": "error",
                        "result": str(e),
                        "node_type": "remote",
                        "node_id": node_id_for_result,
                    }, f, ensure_ascii=False)
            except Exception:
                pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()


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

# ── 增强: 兼容新版 relay_server.py 的高级客户端 ──────────────────────────

import urllib.request
import urllib.error


class RelayClient:
    """
    高级 Relay 客户端：自动注册 + 心跳保活 + 节点发现 + 任务调度。
    
    与 relay_server.py 配合使用，提供完整的节点生命周期管理。
    
    用法:
        client = RelayClient(
            relay_url="http://localhost:18080",
            node_id="my-claw",
            gateway_url="http://localhost:28789",
            token="your-gateway-token",
            capabilities=["shell", "code", "search"],
        )
        client.register()
        client.start_heartbeat(interval=30)
        
        # 发现集群节点
        nodes = client.discover_nodes()
        for n in nodes:
            print(f"  {n['node_id']}: {n['capabilities']}")
        
        # 在远程节点执行任务
        result = client.exec_on_node("kimi-claw-01", "echo hello from claw!")
        print(result)
        
        # 停止
        client.stop()
    """

    def __init__(
        self,
        relay_url: str,
        node_id: str,
        gateway_url: str,
        token: str,
        capabilities: list,
        name: str = None,
    ):
        self.relay_url = relay_url.rstrip("/")
        self.node_id = node_id
        self.gateway_url = gateway_url
        self.token = token
        self.capabilities = capabilities
        self.name = name or node_id
        
        self._heartbeat_thread: threading.Thread = None
        self._heartbeat_interval = 30
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── 底层 HTTP ───────────────────────────────────────────────────────

    def _post_json(self, path: str, data: dict = None) -> dict:
        url = f"{self.relay_url}{path}"
        body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else b""
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8"))
                return err
            except Exception:
                return {"error": f"HTTP {e.code}", "message": str(e)}
        except Exception as e:
            return {"error": "CONNECTION_FAILED", "message": str(e)}

    def _get_json(self, path: str) -> dict:
        url = f"{self.relay_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8"))
                return err
            except Exception:
                return {"error": f"HTTP {e.code}"}
        except Exception as e:
            return {"error": "CONNECTION_FAILED", "message": str(e)}

    def _get_text(self, path: str) -> str:
        url = f"{self.relay_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            return ""

    def _post_text(self, path: str, data: str) -> str:
        url = f"{self.relay_url}{path}"
        body = data.encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "text/plain")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            return str(e)

    # ── 节点注册 ────────────────────────────────────────────────────────

    def register(self) -> dict:
        """
        向 Relay Server 注册本节点。
        注册后其他节点可以发现本节点。
        """
        result = self._post_json("/register", {
            "node_id": self.node_id,
            "name": self.name,
            "gateway_url": self.gateway_url,
            "token": self.token,
            "capabilities": self.capabilities,
        })
        if "error" not in result:
            print(f"[RelayClient] 已注册到 {self.relay_url}，节点: {self.node_id}")
        else:
            print(f"[RelayClient] 注册失败: {result}")
        return result

    def unregister(self) -> dict:
        """注销本节点"""
        return self._post_json(f"/unregister/{self.node_id}")

    def heartbeat(self) -> bool:
        """发送心跳，返回是否成功"""
        result = self._post_json(f"/heartbeat/{self.node_id}")
        return "error" not in result

    # ── 心跳后台线程 ──────────────────────────────────────────────────

    def start_heartbeat(self, interval: int = 30) -> None:
        """启动后台心跳线程（自动重连）"""
        self._heartbeat_interval = interval
        self._stop_event.clear()
        
        def run():
            consecutive_failures = 0
            while not self._stop_event.wait(interval):
                try:
                    ok = self.heartbeat()
                    if ok:
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            # 连续失败，尝试重新注册
                            print(f"[RelayClient] 心跳连续失败，尝试重新注册...")
                            self.register()
                            consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        print(f"[RelayClient] 心跳异常: {e}，尝试重新注册...")
                        self.register()
                        consecutive_failures = 0
        
        t = threading.Thread(target=run, daemon=True, name=f"heartbeat-{self.node_id}")
        t.start()
        self._heartbeat_thread = t
        print(f"[RelayClient] 心跳线程启动，间隔 {interval}s")

    def stop_heartbeat(self) -> None:
        """停止心跳"""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            self._heartbeat_thread = None

    # ── 节点发现 ──────────────────────────────────────────────────────

    def discover_nodes(self) -> list:
        """
        从 Relay 发现所有已注册节点（不含自己）。
        返回: [{node_id, name, gateway_url, capabilities, status}, ...]
        """
        result = self._get_json("/nodes")
        nodes = result.get("nodes", [])
        # 过滤掉自己
        return [n for n in nodes if n.get("node_id") != self.node_id]

    def get_online_nodes(self) -> list:
        """获取所有在线节点（status=online）"""
        nodes = self.discover_nodes()
        return [n for n in nodes if n.get("status") == "online"]

    def get_node(self, node_id: str) -> Optional[dict]:
        """获取指定节点信息"""
        result = self._get_json(f"/discover/{node_id}")
        return result.get("node")

    def get_best_node_for_task(self, task_type: str) -> Optional[dict]:
        """
        根据任务类型找到最优节点。
        使用 paths.py 的能力映射进行匹配。
        """
        from paths import required_capabilities, can_node_handle, find_best_node
        online = self.get_online_nodes()
        if not online:
            return None
        return find_best_node(task_type, online)

    # ── 远程执行 ───────────────────────────────────────────────────────

    def exec_on_node(
        self,
        target_node_id: str,
        command: str,
        timeout: int = 60,
        cwd: str = "/root",
    ) -> dict:
        """
        在指定远程节点执行命令（通过 relay 中转）。
        
        流程：POST /cmd/{node_id} → 节点 poll → 执行 → done → 本机 get_result
        """
        # 1. 发送命令
        wrapped = f'cd {cwd} && {command}'
        resp = self._post_json(f"/cmd/{target_node_id}", {
            "command": wrapped,
            "timeout": timeout,
        })
        
        if "error" in resp and "NODE_NOT_FOUND" not in str(resp):
            return {"status": "error", "output": str(resp), "node_id": target_node_id}
        
        # 2. 等待结果
        deadline = time.time() + timeout
        poll_interval = 1.0
        
        while time.time() < deadline:
            result_data = self._get_json(f"/result/{target_node_id}")
            if result_data and "result" in result_data:
                return {
                    "status": result_data.get("status", "ok"),
                    "output": result_data.get("result", ""),
                    "node_id": target_node_id,
                }
            time.sleep(poll_interval)
        
        return {
            "status": "timeout",
            "output": "",
            "node_id": target_node_id,
        }

    def exec_task_async(
        self,
        target_node_id: str,
        task_id: str,
        prompt: str,
        timeout: int = 120,
    ) -> None:
        """
        异步执行远程任务，结果写入 RESULTS_DIR。
        供 orchestrator ResultWatcher 捕获。
        """
        def _run():
            try:
                from paths import RESULTS_DIR
                import os
                # 包装命令
                escaped = prompt.replace('"', '\\"')
                cmd = f'bash -c "{escaped}"'
                result = self.exec_on_node(target_node_id, cmd, timeout=timeout)
                
                result_file = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
                output_data = {
                    "task_id": task_id,
                    "status": result.get("status", "done"),
                    "result": result.get("output", ""),
                    "node_type": "remote",
                    "node_id": target_node_id,
                }
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[RelayClient] exec_task_async 失败: {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ── 兼容旧协议 ─────────────────────────────────────────────────────

    def ping(self) -> bool:
        """测试 relay 连通性"""
        try:
            r = self._get_json("/health")
            return r.get("status") == "ok"
        except Exception:
            return False

    def get_status(self) -> dict:
        """获取 relay 服务状态"""
        return self._get_json("/health")

    def exec_raw(self, command: str, wait: bool = True, timeout: int = 60) -> dict:
        """兼容旧接口：通过 relay 执行原始命令（自己执行）"""
        return self.exec_on_node(self.node_id, command, timeout=timeout, cwd="/root")

    # ── 生命周期 ───────────────────────────────────────────────────────

    def stop(self) -> None:
        """停止所有后台活动"""
        self.stop_heartbeat()
        self.unregister()
        print(f"[RelayClient] 已停止: {self.node_id}")


# ── 一键启动本地节点的便捷函数 ─────────────────────────────────────────

def auto_start_local(
    relay_url: str = None,
    node_id: str = None,
    gateway_url: str = "http://localhost:28789",
    token: str = None,
    capabilities: list = None,
) -> RelayClient:
    """
    自动从环境变量/配置文件加载配置并启动本地节点。
    
    自动探测：
    - CLAWSWARM_RELAY_URL → relay_url
    - CLAWSWARM_NODE_ID → node_id  
    - CLAWSWARM_GATEWAY_URL → gateway_url
    - CLAWSWARM_GATEWAY_TOKEN → token
    - CLAWSWARM_CAPABILITIES → capabilities (逗号分隔)
    """
    import os
    
    relay_url = relay_url or os.environ.get("CLAWSWARM_RELAY_URL", "")
    node_id = node_id or os.environ.get("CLAWSWARM_NODE_ID", "local-agent")
    token = token or os.environ.get("CLAWSWARM_GATEWAY_TOKEN", "")
    capabilities = capabilities or os.environ.get("CLAWSWARM_CAPABILITIES", "read,write,code,search").split(",")

    if not relay_url:
        raise ValueError("relay_url 未设置，请设置 CLAWSWARM_RELAY_URL 环境变量")

    client = RelayClient(
        relay_url=relay_url,
        node_id=node_id,
        gateway_url=gateway_url,
        token=token,
        capabilities=[c.strip() for c in capabilities],
    )
    
    result = client.register()
    if "error" not in result:
        client.start_heartbeat(interval=30)
    
    return client


if __name__ == "__main__":
    print("=" * 50)
    print("RelayClient 诊断工具")
    print("=" * 50)
    
    import os
    relay_url = os.environ.get("CLAWSWARM_RELAY_URL", "")
    node_id = os.environ.get("CLAWSWARM_NODE_ID", "diagnostic-agent")
    token = os.environ.get("CLAWSWARM_GATEWAY_TOKEN", "")
    
    if not relay_url:
        print("⚠️  CLAWSWARM_RELAY_URL 未设置")
        print()
        # 尝试读 kimi-claw-01 配置
        config_file = RELAY_CONFIG_DIR / "kimi-claw-01.json"
        if config_file.exists():
            config = json.loads(config_file.read_text(encoding="utf-8"))
            relay_url = config.get("relay_url", "")
            print(f"  从 kimi-claw-01.json 读取: {relay_url}")
    
    if relay_url:
        client = RelayClient(
            relay_url=relay_url,
            node_id=node_id,
            gateway_url="http://localhost:28789",
            token=token,
            capabilities=["diagnostic"],
        )
        
        print(f"\n1. Relay 健康检查...")
        print(f"   URL: {relay_url}")
        print(f"   状态: {'✅ 在线' if client.ping() else '❌ 离线'}")
        
        print(f"\n2. 服务指标...")
        status = client.get_status()
        for k, v in status.items():
            print(f"   {k}: {v}")
        
        print(f"\n3. 已注册节点...")
        nodes = client.discover_nodes()
        for n in nodes:
            print(f"   [{n.get('node_id')}] {n.get('name')} - {n.get('capabilities')}")
        
        print(f"\n4. 测试远程执行 (kimi-claw-01)...")
        result = client.exec_on_node("kimi-claw-01", "echo 'hello from claw' && hostname && uptime", timeout=30)
        print(f"   状态: {result.get('status')}")
        print(f"   输出: {result.get('output', '')[:200]}")
    else:
        print("无法连接到 relay")

