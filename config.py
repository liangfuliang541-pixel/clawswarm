"""
ClawSwarm Config - 配置管理
负责：配置加载、验证、合并、环境变量、配置模板

支持：
- JSON/YAML 配置文件
- 环境变量覆盖
- 配置验证
- 多环境配置
- 配置热重载
"""

import os
import json
import copy
import hashlib
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

# YAML 支持是可选的
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ── 配置源优先级 ─────────────────────────────────────────────────────────

class ConfigPriority(Enum):
    DEFAULT = 0      # 默认值
    FILE = 1         # 配置文件
    ENV = 2          # 环境变量
    RUNTIME = 3      # 运行时覆盖

# ── 配置模式 ─────────────────────────────────────────────────────────────

class ConfigSchema:
    """配置模式定义"""
    
    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
    
    def validate(self, config: Dict[str, Any]) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        self._validate_dict(config, self.schema, "", errors)
        return errors
    
    def _validate_dict(self, config: Dict, schema: Dict, path: str, errors: List):
        """递归验证字典"""
        for key, value in config.items():
            full_path = f"{path}.{key}" if path else key
            
            if key not in schema:
                errors.append(f"Unknown key: {full_path}")
                continue
            
            expected_type = schema[key].get("type")
            if expected_type and not isinstance(value, expected_type):
                errors.append(
                    f"Type error at {full_path}: "
                    f"expected {expected_type.__name__}, got {type(value).__name__}"
                )
            
            # 递归验证嵌套对象
            if isinstance(value, dict) and "properties" in schema[key]:
                self._validate_dict(value, schema[key]["properties"], full_path, errors)
    
    def get_default(self) -> Dict:
        """获取默认值"""
        return self._extract_defaults(self.schema)
    
    def _extract_defaults(self, schema: Dict) -> Dict:
        """提取默认值"""
        result = {}
        for key, value in schema.items():
            if "default" in value:
                result[key] = value["default"]
            if "properties" in value:
                result[key] = self._extract_defaults(value["properties"])
        return result


# ── 配置管理器 ─────────────────────────────────────────────────────────────

class ConfigManager:
    """
    配置管理器
    
    用法:
        config = ConfigManager("D:\\claw\\swarm")
        config.load("config.json")
        
        # 获取配置
        port = config.get("server.port", 8080)
        
        # 环境变量覆盖
        config.set_env_prefix("CLAW")
        config.load_env()
        
        # 热重载
        config.watch("config.json", callback)
    """
    
    def __init__(
        self,
        base_dir: str = None,
        env_prefix: str = "CLAW",
        watch_enabled: bool = False
    ):
        self.base_dir = base_dir or os.getcwd()
        self.env_prefix = env_prefix
        self.watch_enabled = watch_enabled
        
        # 配置存储（按优先级）
        self._configs: Dict[ConfigPriority, Dict] = {
            ConfigPriority.DEFAULT: {},
            ConfigPriority.FILE: {},
            ConfigPriority.ENV: {},
            ConfigPriority.RUNTIME: {},
        }
        
        # 模式
        self._schema: Optional[ConfigSchema] = None
        
        # 回调
        self._change_callbacks: List[Callable[[str, Any], None]] = []
        
        # 文件监控
        self._watched_files: Dict[str, float] = {}
        self._watch_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
    
    # ── 模式定义 ─────────────────────────────────────────────────────────
    
    def set_schema(self, schema: Dict[str, Any]):
        """设置配置模式"""
        self._schema = ConfigSchema(schema)
        
        # 应用默认值
        defaults = self._schema.get_default()
        self._configs[ConfigPriority.DEFAULT] = defaults
    
    # ── 加载配置 ─────────────────────────────────────────────────────────
    
    def load_file(self, path: str, priority: ConfigPriority = ConfigPriority.FILE):
        """从文件加载配置"""
        full_path = self._resolve_path(path)
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Config file not found: {full_path}")
        
        # 读取文件
        ext = os.path.splitext(full_path)[1].lower()
        
        with open(full_path, "r", encoding="utf-8") as f:
            if ext in [".json"]:
                config = json.load(f)
            elif ext in [".yaml", ".yml"] and HAS_YAML:
                config = yaml.safe_load(f)
            elif ext in [".yaml", ".yml"]:
                raise ValueError("YAML support requires pyyaml: pip install pyyaml")
            elif ext in [".ini"]:
                config = self._parse_ini(f.read())
            else:
                raise ValueError(f"Unsupported config format: {ext}")
        
        # 验证
        if self._schema:
            errors = self._schema.validate(config)
            if errors:
                raise ValueError(f"Config validation failed: {errors}")
        
        # 存储
        with self._lock:
            self._configs[priority] = config
        
        # 记录文件用于监控
        if self.watch_enabled:
            self._watched_files[full_path] = os.path.getmtime(full_path)
        
        return self
    
    def load_dict(self, config: Dict, priority: ConfigPriority = ConfigPriority.RUNTIME):
        """从字典加载配置"""
        with self._lock:
            self._configs[priority] = config
        return self
    
    def load_env(self, prefix: str = None):
        """从环境变量加载配置"""
        prefix = prefix or self.env_prefix
        
        env_config = {}
        
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            
            # 解析键名
            config_key = key[len(prefix):].lower().strip("_")
            parts = config_key.split("_")
            
            # 转换为嵌套字典
            current = env_config
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            current[parts[-1]] = self._parse_value(value)
        
        with self._lock:
            self._configs[ConfigPriority.ENV] = env_config
        
        return self
    
    # ── 获取配置 ─────────────────────────────────────────────────────────
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        支持点号分隔的键名:
            config.get("server.port")
            config.get("database.connection.host")
        """
        # 按优先级查找（从高到低）
        for priority in reversed(ConfigPriority):
            with self._lock:
                value = self._get_nested(self._configs[priority], key)
            
            if value is not None:
                return value
        
        return default
    
    def _get_nested(self, config: Dict, key: str) -> Any:
        """获取嵌套值"""
        parts = key.split(".")
        current = config
        
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        
        return current
    
    def set(self, key: str, value: Any, priority: ConfigPriority = ConfigPriority.RUNTIME):
        """设置配置值"""
        with self._lock:
            self._set_nested(self._configs[priority], key, value)
        
        # 触发回调
        for callback in self._change_callbacks:
            try:
                callback(key, value)
            except Exception:
                pass
    
    def _set_nested(self, config: Dict, key: str, value: Any):
        """设置嵌套值"""
        parts = key.split(".")
        current = config
        
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        current[parts[-1]] = value
    
    # ── 合并配置 ─────────────────────────────────────────────────────────
    
    def merge(self, other: "ConfigManager") -> "ConfigManager":
        """合并另一个配置管理器"""
        with self._lock:
            for priority in ConfigPriority:
                self._configs[priority] = self._deep_merge(
                    self._configs[priority],
                    other._configs[priority]
                )
        return self
    
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """深度合并字典"""
        result = copy.deepcopy(base)
        
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        
        return result
    
    # ── 完整配置 ─────────────────────────────────────────────────────────
    
    def to_dict(self) -> Dict:
        """获取完整配置（合并后）"""
        result = {}
        
        for priority in ConfigPriority:
            result = self._deep_merge(result, self._configs[priority])
        
        return result
    
    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def to_yaml(self) -> str:
        """导出为 YAML"""
        if not HAS_YAML:
            raise ValueError("YAML support requires pyyaml: pip install pyyaml")
        return yaml.dump(self.to_dict(), allow_unicode=True, default_flow_style=False)
    
    # ── 文件监控 ─────────────────────────────────────────────────────────
    
    def watch(self, path: str, callback: Callable[[str], None] = None):
        """监控配置文件变化"""
        full_path = self._resolve_path(path)
        
        if callback:
            self._change_callbacks.append(callback)
        
        if self.watch_enabled and full_path not in self._watched_files:
            self._watched_files[full_path] = os.path.getmtime(full_path)
            self._start_watch_thread()
    
    def _start_watch_thread(self):
        """启动监控线程"""
        if self._watch_thread and self._watch_thread.is_alive():
            return
        
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
    
    def _watch_loop(self):
        """监控循环"""
        while self._watched_files:
            time.sleep(1)
            
            for path, last_mtime in list(self._watched_files.items()):
                try:
                    current_mtime = os.path.getmtime(path)
                    if current_mtime != last_mtime:
                        # 文件变化，重新加载
                        self._watched_files[path] = current_mtime
                        self.load_file(path)
                        
                        # 触发回调
                        for callback in self._change_callbacks:
                            try:
                                callback(path, "reloaded")
                            except Exception:
                                pass
                except Exception:
                    pass
    
    # ── 工具方法 ─────────────────────────────────────────────────────────
    
    def _resolve_path(self, path: str) -> str:
        """解析路径"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)
    
    def _parse_value(self, value: str) -> Any:
        """解析字符串值"""
        # 布尔值
        if value.lower() in ["true", "yes", "1"]:
            return True
        if value.lower() in ["false", "no", "0"]:
            return False
        
        # 数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        # JSON
        if value.startswith("{") or value.startswith("["):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        
        # 字符串
        return value
    
    def _parse_ini(self, content: str) -> Dict:
        """解析 INI 格式"""
        result = {}
        current_section = None
        
        for line in content.split("\n"):
            line = line.strip()
            
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                result[current_section] = {}
                continue
            
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = self._parse_value(value.strip())
                
                if current_section:
                    result[current_section][key] = value
                else:
                    result[key] = value
        
        return result
    
    # ── 哈希 ─────────────────────────────────────────────────────────
    
    def get_hash(self) -> str:
        """获取配置哈希"""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def load_config(
    path: str,
    schema: Dict = None,
    env_prefix: str = "CLAW"
) -> ConfigManager:
    """快速加载配置"""
    manager = ConfigManager(env_prefix=env_prefix)
    
    if schema:
        manager.set_schema(schema)
    
    manager.load_file(path)
    manager.load_env()
    
    return manager


# ── 默认配置 ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG_SCHEMA = {
    "swarm": {
        "type": dict,
        "properties": {
            "name": {"type": str, "default": "ClawSwarm"},
            "base_dir": {"type": str, "default": "."},
            "max_nodes": {"type": int, "default": 10},
        }
    },
    "scheduler": {
        "type": dict,
        "properties": {
            "poll_interval": {"type": int, "default": 5},
            "max_retries": {"type": int, "default": 3},
            "task_timeout": {"type": int, "default": 300},
        }
    },
    "node": {
        "type": dict,
        "properties": {
            "heartbeat_interval": {"type": int, "default": 10},
            "stale_threshold": {"type": int, "default": 60},
            "offline_threshold": {"type": int, "default": 300},
        }
    },
    "executor": {
        "type": dict,
        "properties": {
            "max_workers": {"type": int, "default": 5},
            "default_timeout": {"type": int, "default": 300},
            "enable_parallel": {"type": bool, "default": True},
        }
    },
    "monitor": {
        "type": dict,
        "properties": {
            "enabled": {"type": bool, "default": True},
            "metrics_retention": {"type": int, "default": 60},
            "alert_webhook": {"type": str, "default": ""},
        }
    },
    "guard": {
        "type": dict,
        "properties": {
            "enabled": {"type": bool, "default": True},
            "allowed_paths": {"type": list, "default": []},
            "forbidden_paths": {"type": list, "default": []},
        }
    },
    "server": {
        "type": dict,
        "properties": {
            "host": {"type": str, "default": "0.0.0.0"},
            "port": {"type": int, "default": 8080},
            "cors": {"type": bool, "default": True},
        }
    },
}


# ── 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("ConfigManager 测试")
    print("=" * 50)
    
    # 创建配置管理器
    config = ConfigManager(base_dir=".")
    
    # 设置模式
    config.set_schema(DEFAULT_CONFIG_SCHEMA)
    
    # 加载默认配置
    print("\n默认配置:")
    print(json.dumps(config.to_dict(), indent=2))
    
    # 运行时覆盖
    config.set("swarm.name", "ClawSwarm-Pro")
    config.set("server.port", 9000)
    
    # 从环境变量（模拟）
    os.environ["CLAW_SERVER_PORT"] = "8888"
    config.load_env()
    
    print("\n合并后配置:")
    print(f"  swarm.name: {config.get('swarm.name')}")
    print(f"  server.port: {config.get('server.port')}")
    print(f"  scheduler.poll_interval: {config.get('scheduler.poll_interval')}")
    
    # 导出
    print("\nJSON 导出:")
    print(config.to_json()[:200] + "...")
    
    print("\n测试完成!")
