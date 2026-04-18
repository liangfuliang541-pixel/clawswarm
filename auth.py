"""
auth.py — 认证与授权系统
支持 API Key、JWT、RBAC 权限控制
"""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable
import threading


class Permission(Enum):
    """权限枚举"""
    # 任务权限
    TASK_READ = "task:read"
    TASK_CREATE = "task:create"
    TASK_CANCEL = "task:cancel"
    TASK_ADMIN = "task:admin"
    
    # 节点权限
    NODE_READ = "node:read"
    NODE_EXECUTE = "node:execute"
    NODE_MANAGE = "node:manage"
    
    # 系统权限
    SYSTEM_READ = "system:read"
    SYSTEM_CONFIG = "system:config"
    SYSTEM_ADMIN = "system:admin"


# 预定义角色
ROLES = {
    "admin": set(Permission),
    "operator": {
        Permission.TASK_READ, Permission.TASK_CREATE, Permission.TASK_CANCEL,
        Permission.NODE_READ, Permission.NODE_EXECUTE,
        Permission.SYSTEM_READ,
    },
    "viewer": {
        Permission.TASK_READ, Permission.NODE_READ, Permission.SYSTEM_READ,
    },
    "agent": {
        Permission.TASK_READ, Permission.TASK_CREATE,
        Permission.NODE_READ, Permission.NODE_EXECUTE,
    },
}


@dataclass
class APIKey:
    """API Key 定义"""
    key_id: str
    key_hash: str  # 存储哈希，不存明文
    name: str
    role: str
    permissions: Set[Permission]
    created_at: float
    expires_at: Optional[float]
    last_used: Optional[float]
    rate_limit: int  # 每分钟请求数
    enabled: bool
    metadata: Dict


@dataclass
class JWTToken:
    """JWT Token 数据"""
    sub: str  # subject (user_id)
    role: str
    permissions: List[str]
    iat: float  # issued at
    exp: float  # expiration
    jti: str  # token id


class AuthManager:
    """认证管理器"""
    
    def __init__(self, storage_path: Optional[Path] = None, jwt_secret: Optional[str] = None):
        self._storage_path = storage_path
        self._jwt_secret = jwt_secret or secrets.token_hex(32)
        self._api_keys: Dict[str, APIKey] = {}
        self._key_index: Dict[str, str] = {}  # hash -> key_id 映射
        self._revoked_tokens: Set[str] = set()
        self._lock = threading.RLock()
        self._rate_limits: Dict[str, List[float]] = {}  # key_id -> timestamps
        
        if storage_path:
            self._load()
    
    def create_api_key(
        self,
        name: str,
        role: str = "agent",
        expires_days: Optional[int] = None,
        rate_limit: int = 1000,
        metadata: Optional[Dict] = None
    ) -> tuple[str, str]:
        """
        创建新的 API Key
        返回: (key_id, 明文key) - 明文key只显示一次
        """
        with self._lock:
            key_id = f"ak_{secrets.token_hex(8)}"
            plaintext = f"claw_{secrets.token_hex(32)}"
            key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
            
            now = time.time()
            api_key = APIKey(
                key_id=key_id,
                key_hash=key_hash,
                name=name,
                role=role,
                permissions=ROLES.get(role, ROLES["viewer"]),
                created_at=now,
                expires_at=now + expires_days * 86400 if expires_days else None,
                last_used=None,
                rate_limit=rate_limit,
                enabled=True,
                metadata=metadata or {}
            )
            
            self._api_keys[key_id] = api_key
            self._key_index[key_hash] = key_id
            self._persist()
            
            return key_id, plaintext
    
    def validate_api_key(self, key: str) -> Optional[APIKey]:
        """验证 API Key"""
        with self._lock:
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            key_id = self._key_index.get(key_hash)
            
            if not key_id:
                return None
            
            api_key = self._api_keys.get(key_id)
            if not api_key or not api_key.enabled:
                return None
            
            # 检查过期
            if api_key.expires_at and time.time() > api_key.expires_at:
                return None
            
            # 检查速率限制
            if not self._check_rate_limit(key_id, api_key.rate_limit):
                return None
            
            # 更新最后使用时间
            api_key.last_used = time.time()
            
            return api_key
    
    def revoke_api_key(self, key_id: str) -> bool:
        """吊销 API Key"""
        with self._lock:
            api_key = self._api_keys.get(key_id)
            if not api_key:
                return False
            
            api_key.enabled = False
            del self._key_index[api_key.key_hash]
            self._persist()
            return True
    
    def list_api_keys(self) -> List[Dict]:
        """列出所有 API Keys"""
        with self._lock:
            return [
                {
                    "key_id": k.key_id,
                    "name": k.name,
                    "role": k.role,
                    "created_at": k.created_at,
                    "expires_at": k.expires_at,
                    "last_used": k.last_used,
                    "enabled": k.enabled,
                    "rate_limit": k.rate_limit,
                }
                for k in self._api_keys.values()
            ]
    
    def create_jwt(self, user_id: str, role: str = "operator", expires_hours: int = 24) -> str:
        """创建 JWT Token"""
        now = time.time()
        token_data = JWTToken(
            sub=user_id,
            role=role,
            permissions=[p.value for p in ROLES.get(role, ROLES["viewer"])],
            iat=now,
            exp=now + expires_hours * 3600,
            jti=secrets.token_hex(16)
        )
        
        # 简单的 JWT 实现 (header.payload.signature)
        header = json.dumps({"alg": "HS256", "typ": "JWT"})
        payload = json.dumps({
            "sub": token_data.sub,
            "role": token_data.role,
            "permissions": token_data.permissions,
            "iat": token_data.iat,
            "exp": token_data.exp,
            "jti": token_data.jti,
        })
        
        header_b64 = self._b64_encode(header)
        payload_b64 = self._b64_encode(payload)
        
        signature = hmac.new(
            self._jwt_secret.encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{header_b64}.{payload_b64}.{signature}"
    
    def validate_jwt(self, token: str) -> Optional[JWTToken]:
        """验证 JWT Token"""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            
            header_b64, payload_b64, signature = parts
            
            # 验证签名
            expected_sig = hmac.new(
                self._jwt_secret.encode(),
                f"{header_b64}.{payload_b64}".encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_sig):
                return None
            
            # 解析 payload
            payload_json = self._b64_decode(payload_b64)
            data = json.loads(payload_json)
            
            # 检查是否吊销
            if data.get("jti") in self._revoked_tokens:
                return None
            
            # 检查过期
            if time.time() > data.get("exp", 0):
                return None
            
            return JWTToken(
                sub=data["sub"],
                role=data["role"],
                permissions=data["permissions"],
                iat=data["iat"],
                exp=data["exp"],
                jti=data["jti"]
            )
        except Exception:
            return None
    
    def revoke_jwt(self, token: str) -> bool:
        """吊销 JWT Token"""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return False
            
            payload_b64 = parts[1]
            payload_json = self._b64_decode(payload_b64)
            data = json.loads(payload_json)
            jti = data.get("jti")
            
            if jti:
                self._revoked_tokens.add(jti)
                return True
            return False
        except Exception:
            return False
    
    def check_permission(self, api_key: APIKey, permission: Permission) -> bool:
        """检查权限"""
        return permission in api_key.permissions
    
    def require_permission(self, permission: Permission):
        """装饰器：要求特定权限"""
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                # 这里假设 api_key 在 kwargs 中
                api_key = kwargs.get('api_key') or getattr(args[0] if args else None, 'api_key', None)
                if not api_key or not self.check_permission(api_key, permission):
                    raise PermissionError(f"Permission denied: {permission.value}")
                return func(*args, **kwargs)
            return wrapper
        return decorator
    
    def _check_rate_limit(self, key_id: str, limit: int) -> bool:
        """检查速率限制"""
        now = time.time()
        window = 60  # 1分钟窗口
        
        if key_id not in self._rate_limits:
            self._rate_limits[key_id] = []
        
        timestamps = self._rate_limits[key_id]
        # 清理过期时间戳
        timestamps[:] = [t for t in timestamps if now - t < window]
        
        if len(timestamps) >= limit:
            return False
        
        timestamps.append(now)
        return True
    
    def _b64_encode(self, data: str) -> str:
        """Base64 URL 安全编码"""
        import base64
        return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")
    
    def _b64_decode(self, data: str) -> str:
        """Base64 URL 安全解码"""
        import base64
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data).decode()
    
    def _persist(self):
        """持久化"""
        if not self._storage_path:
            return
        
        try:
            data = {
                "api_keys": [
                    {
                        "key_id": k.key_id,
                        "key_hash": k.key_hash,
                        "name": k.name,
                        "role": k.role,
                        "permissions": [p.value for p in k.permissions],
                        "created_at": k.created_at,
                        "expires_at": k.expires_at,
                        "last_used": k.last_used,
                        "rate_limit": k.rate_limit,
                        "enabled": k.enabled,
                        "metadata": k.metadata,
                    }
                    for k in self._api_keys.values()
                ],
                "revoked_tokens": list(self._revoked_tokens),
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Auth] Persist error: {e}")
    
    def _load(self):
        """加载"""
        if not self._storage_path or not self._storage_path.exists():
            return
        
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            
            for k in data.get("api_keys", []):
                api_key = APIKey(
                    key_id=k["key_id"],
                    key_hash=k["key_hash"],
                    name=k["name"],
                    role=k["role"],
                    permissions={Permission(p) for p in k.get("permissions", [])},
                    created_at=k["created_at"],
                    expires_at=k.get("expires_at"),
                    last_used=k.get("last_used"),
                    rate_limit=k.get("rate_limit", 1000),
                    enabled=k.get("enabled", True),
                    metadata=k.get("metadata", {}),
                )
                self._api_keys[api_key.key_id] = api_key
                self._key_index[api_key.key_hash] = api_key.key_id
            
            self._revoked_tokens = set(data.get("revoked_tokens", []))
            print(f"[Auth] Loaded {len(self._api_keys)} API keys")
        except Exception as e:
            print(f"[Auth] Load error: {e}")


# 全局实例
_auth_manager: Optional[AuthManager] = None


def get_auth_manager(storage_path: Optional[Path] = None) -> AuthManager:
    """获取全局认证管理器"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager(storage_path)
    return _auth_manager
