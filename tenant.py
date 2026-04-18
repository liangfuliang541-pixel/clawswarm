"""
tenant.py — 多租户与命名空间隔离
支持多个团队共用集群，任务和节点按命名空间隔离
"""

import json
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from enum import Enum


class Role(Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass
class Tenant:
    """租户"""
    tenant_id: str
    name: str
    display_name: str
    owner: str
    created_at: float
    updated_at: float
    settings: Dict = field(default_factory=dict)
    quotas: Dict = field(default_factory=lambda: {
        "max_nodes": 10,
        "max_tasks_per_day": 1000,
        "max_concurrent_tasks": 50,
    })
    tags: List[str] = field(default_factory=list)


class Namespace:
    """命名空间 - 租户下的逻辑隔离区"""
    def __init__(self, tenant_id: str, name: str):
        self.tenant_id = tenant_id
        self.name = name
        self.created_at = time.time()
        self.isolated = True


class TenantManager:
    """多租户管理器"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._tenants: Dict[str, Tenant] = {}
        self._namespaces: Dict[str, Namespace] = {}  # namespace_id -> Namespace
        self._members: Dict[str, Dict[str, str]] = {}  # user_id -> {tenant_id: role}
        self._permissions: Dict[str, Dict[str, Set[str]]] = {}  # tenant_id -> {role: Set[perm]}
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._default_perms = {
            Role.OWNER.value: {"task:read", "task:create", "task:cancel", "task:admin",
                               "node:read", "node:execute", "node:manage",
                               "system:read", "system:config", "system:admin",
                               "tenant:read", "tenant:admin", "member:manage"},
            Role.ADMIN.value: {"task:read", "task:create", "task:cancel",
                              "node:read", "node:execute",
                              "system:read", "member:manage"},
            Role.MEMBER.value: {"task:read", "task:create",
                              "node:read", "node:execute"},
            Role.VIEWER.value: {"task:read", "node:read", "system:read"},
        }
        if storage_path:
            self._load()
    
    def create_tenant(self, name: str, display_name: str, owner: str, quotas: Optional[Dict] = None) -> Tenant:
        tenant_id = f"t_{name.lower().replace(' ', '_')}_{int(time.time()) % 100000:05d}"
        tenant = Tenant(
            tenant_id=tenant_id, name=name, display_name=display_name,
            owner=owner, created_at=time.time(), updated_at=time.time(),
            quotas={**self._default_quotas(), **(quotas or {})},
        )
        with self._lock:
            self._tenants[tenant_id] = tenant
            self._namespaces[tenant_id] = Namespace(tenant_id, name)
            self._members[owner] = {tenant_id: Role.OWNER.value}
            self._persist()
        return tenant
    
    def add_member(self, tenant_id: str, user_id: str, role: str = "member") -> bool:
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                return False
            self._members[user_id] = {tenant_id: role}
            tenant.updated_at = time.time()
            self._persist()
            return True
    
    def remove_member(self, user_id: str, tenant_id: str) -> bool:
        with self._lock:
            if user_id not in self._members:
                return False
            info = self._members[user_id]
            if info.get(tenant_id) != tenant_id:
                return False
            del self._members[user_id]
            self._persist()
            return True
    
    def check_permission(self, user_id: str, tenant_id: str, permission: str) -> bool:
        with self._lock:
            if user_id not in self._members:
                return False
            info = self._members[user_id]
            if info.get(tenant_id) != tenant_id:
                return False
            role = info.get(tenant_id)
            perms = self._permissions.get(tenant_id, self._default_perms.get(role, set()))
            return permission in perms
    
    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)
    
    def list_tenants(self, user_id: Optional[str] = None) -> List[Tenant]:
        with self._lock:
            if user_id:
                user_tenants = [tid for tid, info in self._members.get(user_id, {}).items()]
                return [self._tenants[tid] for tid in user_tenants if tid in self._tenants]
            return list(self._tenants.values())
    
    def check_quota(self, tenant_id: str, quota_type: str, current: int = 0, delta: int = 1) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        limit = tenant.quotas.get(f"max_{quota_type}", 0)
        if limit <= 0:
            return True
        return current + delta <= limit
    
    def delete_tenant(self, tenant_id: str) -> bool:
        with self._lock:
            if tenant_id not in self._tenants:
                return False
            del self._tenants[tenant_id]
            self._namespaces.pop(tenant_id, None)
            for uid, info in list(self._members.items()):
                info.pop(tenant_id, None)
            self._persist()
            return True
    
    def _default_quotas(self) -> Dict:
        return {"max_nodes": 10, "max_tasks_per_day": 1000, "max_concurrent_tasks": 50}
    
    def _persist(self):
        if not self._storage_path:
            return
        try:
            data = {
                "tenants": [
                    {**{k: v for k, v in t.__dict__.items() if not isinstance(v, set)}}
                    for t in self._tenants.values()
                ],
                "members": self._members,
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"[Tenant] Persist error: {e}")
    
    def _load(self):
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for t in data.get("tenants", []):
                tenant = Tenant(**t)
                self._tenants[tenant.tenant_id] = tenant
                self._namespaces[tenant.tenant_id] = Namespace(tenant.tenant_id, tenant.name)
            self._members = data.get("members", {})
            print(f"[Tenant] Loaded {len(self._tenants)} tenants")
        except Exception as e:
            print(f"[Tenant] Load error: {e}")
