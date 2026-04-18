"""
edge.py — 边缘计算适配器
支持 HTTP/MQTT IoT 设备接入集群作为轻量 Agent
"""

import json
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class DeviceProtocol(Enum):
    HTTP = "http"
    MQTT = "mqtt"
    WEBSOCKET = "websocket"
    COAP = "coap"


class DeviceStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    SLEEPING = "sleeping"
    ERROR = "error"


@dataclass
class EdgeDevice:
    """边缘设备"""
    device_id: str
    name: str
    protocol: DeviceProtocol
    endpoint: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_seen: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    heartbeat_interval: float = 30.0
    data_format: str = "json"  # json, protobuf, binary
    max_payload_size: int = 1024 * 1024  # 1MB
    location: Optional[Dict] = None


@dataclass
class EdgeTask:
    """边缘任务"""
    task_id: str
    device_id: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    status: str = "pending"
    timeout: float = 60.0
    retry_count: int = 0
    max_retries: int = 3


class EdgeAdapter:
    """边缘计算适配器 — 将 IoT 设备接入 ClawSwarm 作为轻量 Agent"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._devices: Dict[str, EdgeDevice] = {}
        self._tasks: Dict[str, EdgeTask] = {}
        self._task_results: Dict[str, List[Any]] = defaultdict(list)
        self._subscriptions: Dict[str, List[str]] = defaultdict(list)  # topic -> device_ids
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._heartbeat_thread: Optional[threading.Thread] = None
        _running = False
        self._on_data_callbacks: Dict[str, List[Callable]] = {}
        if storage_path:
            self._load()
    
    def register_device(self, device_id: str, name: str, protocol: str,
                        endpoint: str, capabilities: Optional[List[str]] = None,
                        metadata: Optional[Dict] = None,
                        heartbeat_interval: float = 30.0,
                        max_payload_size: int = 1024 * 1024) -> EdgeDevice:
        device = EdgeDevice(
            device_id=device_id, name=name,
            protocol=DeviceProtocol(protocol),
            endpoint=endpoint,
            capabilities=capabilities or ["sensor"],
            metadata=metadata or {},
            heartbeat_interval=heartbeat_interval,
            max_payload_size=max_payload_size,
        )
        with self._lock:
            self._devices[device_id] = device
            device.status = DeviceStatus.ONLINE
            device.last_seen = time.time()
            self._persist()
        return device
    
    def unregister_device(self, device_id: str) -> bool:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return False
            device.status = DeviceStatus.OFFLINE
            self._persist()
            return True
    
    def submit_task(self, device_id: str, payload: Dict, timeout: float = 60.0) -> Optional[str]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device or device.status == DeviceStatus.OFFLINE:
                return None
            task_id = f"edge_{device_id}_{int(time.time()) % 100000:05d}"
            task = EdgeTask(
                task_id=task_id, device_id=device_id,
                payload=payload, timeout=timeout,
            )
            self._tasks[task_id] = task
            self._persist()
            return task_id
    
    def complete_task(self, task_id: str, result: Any) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.status = "completed"
            task.completed_at = time.time()
            task.result = result
            self._task_results[task.device_id].append(result)
            self._persist()
            return True
    
    def fail_task(self, task_id: str, error: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = "pending"  # 重新排队
            else:
                task.status = "failed"
            self._persist()
            return True
    
    def publish(self, topic: str, data: Any, qos: int = 0):
        """向订阅了该 topic 的设备推送数据"""
        with self._lock:
            device_ids = self._subscriptions.get(topic, [])
            for did in device_ids:
                device = self._devices.get(did)
                if device and device.status == DeviceStatus.ONLINE:
                    self._send_to_device(device, {"topic": topic, "data": data, "qos": qos})
    
    def subscribe(self, topic: str, device_id: str):
        with self._lock:
            if device_id not in self._subscriptions[topic]:
                self._subscriptions[topic].append(device_id)
    
    def on_data(self, topic: str, callback: Callable):
        """注册数据接收回调"""
        if topic not in self._on_data_callbacks:
            self._on_data_callbacks[topic] = []
        self._on_data_callbacks[topic].append(callback)
    
    def check_heartbeats(self):
        """检查设备心跳，超时标记离线"""
        now = time.time()
        with self._lock:
            for device in self._devices.values():
                if device.last_seen and now - device.last_seen > device.heartbeat_interval * 3:
                    device.status = DeviceStatus.OFFLINE
            # 重试超时任务
            for task in self._tasks.values():
                if task.status == "pending":
                    device = self._devices.get(task.device_id)
                    if device and device.status == DeviceStatus.ONLINE:
                        self._send_to_device(device, task.payload)
    
    def get_device(self, device_id: str) -> Optional[EdgeDevice]:
        return self._devices.get(device_id)
    
    def list_devices(self, status: Optional[DeviceStatus] = None) -> List[EdgeDevice]:
        with self._lock:
            devices = list(self._devices.values())
            if status:
                devices = [d for d in devices if d.status == status]
            return devices
    
    def get_metrics(self) -> Dict:
        with self._lock:
            return {
                "total_devices": len(self._devices),
                "online": len([d for d in self._devices.values() if d.status == DeviceStatus.ONLINE]),
                "offline": len([d for d in self.devices.values() if d.status == DeviceStatus.OFFLINE]),
                "sleeping": len([d for d in self.devices.values() if d.status == DeviceStatus.SLEEPING]),
                "pending_tasks": len([t for t in self._tasks.values() if t.status == "pending"]),
                "completed_tasks": len([t for t in self._tasks.values() if t.status == "completed"]),
                "subscriptions": {k: len(v) for k, v in self._subscriptions.items()},
            }
    
    def _send_to_device(self, device: EdgeDevice, data: Any):
        """发送数据到设备（实际实现中会用 HTTP POST / MQTT publish）"""
        # 实际实现根据 device.protocol 选择发送方式
        endpoint = device.endpoint
        try:
            import requests
            if device.protocol == DeviceProtocol.HTTP:
                resp = requests.post(
                    f"{endpoint}/task",
                    json={"data": data, "timestamp": time.time()},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception:
            device.status = DeviceStatus.ERROR
        return False
    
    def start_heartbeat_monitor(self, interval: float = 10.0):
        """启动心跳监控线程"""
        def _monitor():
            while self._running:
                self.check_heartbeats()
                time.sleep(interval)
        self._running = True
        self._heartbeat_thread = threading.Thread(target=_monitor, daemon=True)
        self._heartbeat_thread.start()
    
    def stop_heartbeat_monitor(self):
        self._running = False
    
    def _persist(self):
        if not self._storage_path:
            return
        try:
            data = {"devices": []}
            for d in self._devices.values():
                dev_info = {}
                for k, v in d.__dict__.items():
                    dev_info[k] = v.value if isinstance(v, DeviceProtocol) else v
                dev_info["subscriptions"] = self._subscriptions
                data["devices"].append(dev_info)
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Edge] Persist error: {e}")
    
    def _load(self):
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for d in data.get("devices", []):
                dev = EdgeDevice(
                    device_id=d["device_id"], name=d["name"],
                    protocol=DeviceProtocol(d["protocol"]),
                    endpoint=d["endpoint"],
                    capabilities=d.get("capabilities", []),
                    metadata=d.get("metadata", {}),
                    heartbeat_interval=d.get("heartbeat_interval", 30.0),
                    max_payload_size=d.get("max_payload_size", 1048576),
                )
                dev.last_seen = d.get("last_seen")
                if dev.last_seen:
                    dev.status = DeviceStatus.ONLINE
                self._devices[dev.device_id] = dev
            self._subscriptions = data.get("subscriptions", {})
            print(f"[Edge] Loaded {len(self._devices)} devices")
        except Exception as e:
            print(f"[Edge] Load error: {e}")
