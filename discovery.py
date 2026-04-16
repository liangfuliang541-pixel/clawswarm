"""
ClawSwarm Node Discovery - 鑺傜偣鍙︿竴鍙戠幆鑺傜偣鍙楃悊

鑱岃嚜鍔ㄥ彂鐜板苟璁板綍鍏朵粬 OpenClaw 鑺傜偣锛岀粺涓€鏄剧ず銆?
浣跨敤鏂瑰紡:
    from discovery import ClawDiscovery

    disc = ClawDiscovery(
        relay_url="http://localhost:18080",
        node_id="my-claw",
        gateway_url="http://localhost:28789",
        token="xxx",
        capabilities=["shell", "code"]
    )
    disc.register()
    disc.start_heartbeat(interval=30)

    online = disc.get_online_nodes()
    print(online)
"""

import json
import os
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── 璺緞閰嶇疆 ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent / "swarm_data"
AGENTS_DIR = BASE_DIR / "agents"
REMOTE_NODES_DIR = BASE_DIR / "remote_nodes"
QUEUE_DIR = BASE_DIR / "queue"
RESULTS_DIR = BASE_DIR / "results"

AGENTS_DIR.mkdir(parents=True, exist_ok=True)
REMOTE_NODES_DIR.mkdir(parents=True, exist_ok=True)


# ── 鏋氫妇绫?────────────────────────────────────────────────────────────────

class DiscoveryError(Exception):
    """Discovery 鐩稿叧閿欒瘧"""
    pass


class ClawDiscovery:
    """
    鑺傜偣鍙︿竴鍙戠幆銆佸湪绾胯妭鐐瑰彂鐜扮被銆?

    鏀堕泿鏃跺€欙細
    1. register() - 灏嗚嚜韬～鍐欏叆 agents/ 鏂囦欢
    2. start_heartbeat() - 鍚姩鍙︿竴绾跨▼涓烘湰鑺傜偣鍙戦€佸熬蹇冭烦
    3. get_online_nodes() / discover_nodes() - 鍙戠幇鍏朵粬鑺傜偣

    涓诲姟鏃跺€欙細
    1. get_online_nodes() - 鑾峰緱褰撳墠鍦ㄧ嚎鑺傜偣锛堝寘鍚?澶栭檷鍜岃嚜韬э級
    2. discover_nodes() - 鍙戠幇鎵€鏈夎妭鐐癸紙涓嶅惈鎯呭喌涓ユ牸妫€鏌ワ級
    """

    DEFAULT_HEARTBEAT_INTERVAL = 30  # 绉掞紙瓒呮椂鍒ゆ柇涓?120s锛?

    def __init__(
        self,
        relay_url: str = "",
        node_id: str = "",
        gateway_url: str = "http://localhost:28789",
        token: str = "",
        capabilities: List[str] = None,
        name: str = None,
    ):
        self.relay_url = relay_url
        self.node_id = node_id or f"node-{os.getpid()}"
        self.gateway_url = gateway_url
        self.token = token
        self.capabilities = capabilities or ["general"]
        self.name = name or self.node_id

        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        self._agent_file = AGENTS_DIR / f"{self.node_id}.json"

    # ── 娉ㄥ唽涓庡熬蹇冭烦 ────────────────────────────────────────────────

    def register(self) -> Dict[str, Any]:
        """
        灏嗚妭鐐逛俊鎭疉gents/ 鏂囦欢锛岀粦瀵硷紱
        濡傛灉 relay_url 鏈夋晥锛岃〃绀烘槸閫氳繃 relay 璁よ瘉鐨勮繙绋嬭妭鐐广€?
        """
        is_remote = bool(self.relay_url)
        record = {
            "node_id": self.node_id,
            "name": self.name,
            "type": "remote" if is_remote else "local",
            "relay_url": self.relay_url,
            "gateway_url": self.gateway_url,
            "token": self.token,
            "capabilities": self.capabilities,
            "registered_at": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat(),
            "is_remote": is_remote,
        }

        with open(self._agent_file, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        return {
            "status": "registered",
            "node_id": self.node_id,
            "agent_file": str(self._agent_file),
        }

    def start_heartbeat(self, interval: int = None) -> None:
        """
        鍚姩鍙︿竴涓哄熬蹇冭烦绾跨▼锛屾瘡 interval 绉掓洿鏂颁俊鎭€?

        Args:
            interval: 蹇冭烦闂撮殧锛屼粎鏃堕檺锛屼粠 DEFAULT_HEARTBEAT_INTERVAL 銆?
        """
        if interval is None:
            interval = self.DEFAULT_HEARTBEAT_INTERVAL

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return  # 宸茬粡鍚姩

        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            daemon=True,
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        """鍋滄蹇冭烦绾跨▼"""
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def _heartbeat_loop(self, interval: int) -> None:
        """鍙︿竴绾跨▼涓烘湰鍦拌妭鐐瑰彂閫佸熬蹇冿紝姣忓崟鐙煎紑涓€涓?

        濡傛灉鏄繙绋嬭妭鐐癸紝鍒欓€氳繃 relay 涓€鍙戠幇锛?
        濡傛灉鏄疉PI Mode锛岃〃绀烘湰鍦拌捣鑹茬粦瀵硅薄銆?
        """
        while not self._stop_heartbeat.wait(interval):
            self._touch()

    def _touch(self) -> None:
        """鏇存柊 last_heartbeat 鏃堕棿"""
        if self._agent_file.exists():
            try:
                data = json.loads(self._agent_file.read_text(encoding="utf-8"))
                data["last_heartbeat"] = datetime.now().isoformat()
                self._agent_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    # ── 鑺傜偣鍙戠幇 ──────────────────────────────────────────────────────

    def discover_nodes(self) -> List[Dict[str, Any]]:
        """
        鍙戠幇鎵€鏈夎妭鐐癸紙涓嶅惈鐘舵€佹槸鍚︿紬鍙楦э級銆?

        鍖呭惈:
        - 鏈湴鑺傜偣锛氫粠 agents/ 鍒锋柊
        - 杩滅▼鑺傜偣锛氫粠 remote_nodes/ 鍒锋柊

        涓嶆槇鍊掓牴鎹甪nline_nodes銆?
        """
        from relay_client import RemoteNodeManager

        nodes = []
        now = datetime.now()

        # 鏈湴鑺傜偣
        if AGENTS_DIR.exists():
            for fname in os.listdir(AGENTS_DIR):
                if not fname.endswith(".json"):
                    continue
                try:
                    agent = json.loads((AGENTS_DIR / fname).read_text(encoding="utf-8"))
                    nodes.append(agent)
                except Exception:
                    pass

        # 杩滅▼鑺傜偣锛坸emote_nodes/锛?
        try:
            mgr = RemoteNodeManager()
            for node_info in mgr.list_nodes():
                nodes.append({
                    "node_id": node_info["node_id"],
                    "name": node_info.get("name", node_info["node_id"]),
                    "type": "remote",
                    "capabilities": node_info.get("capabilities", []),
                    "relay_url": node_info.get("relay_url", ""),
                    "is_remote": True,
                })
        except ImportError:
            pass

        return nodes

    def get_online_nodes(self, threshold_sec: int = 120) -> List[Dict[str, Any]]:
        """
        鑾峰緱鍦ㄧ嚎鑺傜偣锛堟湁鏃堕檺鍐呰捣蹇冭烦锛岃嚜宸变篃鍦ㄥ崟銆?

        Args:
            threshold_sec: 蹇冭烦瓒呰繃杩欎綑绉掑垽瀹氫负 offline銆?

        Returns:
            鍦ㄧ嚎鑺傜偣鍒楄〃锛屽寘鍚?澶栭檷鍜岃嚜韬э紙闄ゆ眰鑷繁锛?
        """
        now = datetime.now()
        all_nodes = self.discover_nodes()
        online = []

        for node in all_nodes:
            # 闄よ嚜韬?
            if node.get("node_id") == self.node_id:
                continue

            if node.get("is_remote"):
                # 杩滅▼鑺傜偣锛氭牴鎹?relay_reachable 鍒ゆ柇
                try:
                    from relay_client import RemoteNodeManager
                    mgr = RemoteNodeManager()
                    info = mgr.list_nodes()
                    reachable = any(
                        n["node_id"] == node["node_id"] and n.get("relay_reachable")
                        for n in info
                    )
                    if reachable:
                        online.append(node)
                except Exception:
                    pass
            else:
                # 鏈湴鑺傜偣锛氭牴鎹?qdratbeat 鏃堕棿鍒ゆ柇
                last_seen_str = node.get("last_heartbeat")
                if not last_seen_str:
                    continue
                try:
                    last_seen = datetime.fromisoformat(last_seen_str)
                    age = (now - last_seen).total_seconds()
                    if age < threshold_sec:
                        online.append(node)
                except Exception:
                    pass

        return online

    # ── 杩愮▼鎵ц€冿細鍙︿竴涓€鑺傜偣銆佸湪璇ヨ妭鐐逛笂鎵ц€? ───────────────

    def exec_on_node(
        self,
        target_node_id: str,
        command: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        鍦ㄨ创建鎸囧畾鑺傜偣涓婅繍琛屽懡浠わ紙閫氳繃 relay銆?

        Args:
            target_node_id: 鐩 goal 鑺傜偣 ID
            command: 瑕乻r缁撶殑鍛戒护
            timeout: 瓒呮椂锛堢锛?

        Returns:
            {
                "status": "ok"|"error"|"timeout",
                "output": str,
                "elapsed": float,
                "node_id": str,
            }
        """
        from relay_client import RemoteNode, RemoteNodeManager

        # 鍒涘缓 RemoteNode
        if self.relay_url:
            # 鑷繁鏄繙绋嬭妭鐐癸紝寮哄埗浣跨敤 relay
            node = RemoteNode(
                node_id=self.node_id,
                relay_url=self.relay_url,
                capabilities=self.capabilities,
            )
            return node.exec(command, wait=True, timeout=timeout)

        # 灏濊瘯浠?swarms_nodes/ 涓烘尋 Node
        mgr = RemoteNodeManager()
        target = None
        for n in mgr.list_nodes():
            if n["node_id"] == target_node_id:
                target = RemoteNode(
                    node_id=n["node_id"],
                    relay_url=n.get("relay_url", ""),
                    name=n.get("name"),
                    capabilities=n.get("capabilities"),
                )
                break

        if not target:
            return {
                "status": "error",
                "output": f"Node not found: {target_node_id}",
                "elapsed": 0,
                "node_id": target_node_id,
            }

        return target.exec(command, wait=True, timeout=timeout)

    def exec_task_async(
        self,
        target_node_id: str,
        task_id: str,
        prompt: str,
        timeout: int = 60,
        task_type: str = "general",
    ) -> None:
        """
        鍦ㄨ创建鎸囧畾鑺傜偣涓婇潪鍚屾仮鎴愭湇鍔★紝
        缁撴灉鍐欏叆 results/r_{task_id}.json锛?

        Args:
            target_node_id: 鐩 goal 鑺傜偣 ID
            task_id: 浠诲姟 ID锛岀敤浜庡～鍏?results/
            prompt: 浠诲姟鎻忚堪锛?
            timeout: 瓒呮椂锛堢锛?
            task_type: 浠诲姟绫诲瀷
        """
        from relay_client import RemoteNode, RemoteNodeManager, exec_task_async_via_relay

        mgr = RemoteNodeManager()
        node_dict = None
        for n in mgr.list_nodes():
            if n["node_id"] == target_node_id:
                node_dict = {
                    "node_id": n["node_id"],
                    "relay_url": n.get("relay_url", ""),
                    "name": n.get("name"),
                    "capabilities": n.get("capabilities"),
                }
                break

        if not node_dict:
            # 濡傛灉鑺傜偣涓嶆湁锛屼娇鐢ㄦ湰鏈鸿В鏋愶紝浠诲姟璁℃崟涓哄け璐?
            result_file = RESULTS_DIR / f"r_{task_id}.json"
            try:
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "task_id": task_id,
                        "status": "error",
                        "result": f"Node not found: {target_node_id}",
                        "node_type": "remote",
                        "node_id": target_node_id,
                    }, f, ensure_ascii=False)
            except Exception:
                pass
            return

        exec_task_async_via_relay(
            task_id=task_id,
            prompt=prompt,
            node_or_dict=node_dict,
            timeout=timeout,
            task_type=task_type,
        )
