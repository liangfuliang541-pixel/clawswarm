"""
ClawSwarm Guard - 安全隔离模块
提供路径验证、命令白名单、审计日志功能

用法: from guard import Guard
"""

import os
import fnmatch
import json
from pathlib import Path
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────────────

# 允许的根目录（节点只能访问自己的目录）
ALLOWED_ROOTS = [
    "{base}/queue",
    "{base}/in_progress", 
    "{base}/results",
    "{base}/agents",
    "{base}/workspace/{node_id}",
]

# 禁止的路径模式
FORBIDDEN_PATTERNS = [
    "..",
    "~/.ssh",
    "~/.aws",
    "C:\\Windows",
    "C:\\Program Files",
    "/etc/passwd",
    "*system32*",
    "*cmd.exe*",
    "*powershell.exe*",
]

# 审计日志
AUDIT_FILE = "{base}/audit.log"


class Guard:
    """安全守卫：验证路径、记录审计"""
    
    def __init__(self, base_dir: str, node_id: str):
        self.base_dir = base_dir
        self.node_id = node_id
        self.workspace = os.path.join(base_dir, "workspace", node_id)
        
        # 确保工作目录存在
        os.makedirs(self.workspace, exist_ok=True)
    
    def validate_path(self, path: str) -> bool:
        """
        验证路径是否安全
        返回: True=允许, False=禁止
        """
        try:
            # 转换为绝对路径
            abs_path = os.path.abspath(path).lower()
            
            # 检查禁止模式
            for pattern in FORBIDDEN_PATTERNS:
                if fnmatch.fnmatch(abs_path, pattern.lower()):
                    return False
            
            # 检查是否在允许的根目录下
            allowed = [
                os.path.abspath(p.format(base=self.base_dir, node_id=self.node_id)).lower()
                for p in ALLOWED_ROOTS
            ]
            allowed.append(os.path.abspath(self.workspace).lower())
            
            for root in allowed:
                if abs_path.startswith(root):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def validate_command(self, cmd: str) -> bool:
        """
        验证命令是否允许执行
        返回: True=允许, False=禁止
        """
        cmd_lower = cmd.lower()
        
        # 高危命令黑名单
        dangerous = [
            "rm -rf /",
            "format c:",
            "del /f /s /q",
            ">>",
            ">",
            "|",
            "&&",
            ";;",
            "powershell",
            "cmd.exe",
            "wscript",
            "cscript",
        ]
        
        for d in dangerous:
            if d in cmd_lower:
                return False
        
        return True
    
    def audit(self, event: str, details: dict = None):
        """记录审计日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "node": self.node_id,
            "event": event,
            "details": details or {}
        }
        
        audit_path = AUDIT_FILE.format(base=self.base_dir)
        
        try:
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 审计失败不中断
    
    def safe_read(self, relative_path: str) -> str:
        """安全读取文件"""
        if not self.validate_path(relative_path):
            raise PermissionError(f"路径禁止访问: {relative_path}")
        
        full_path = os.path.join(self.workspace, relative_path)
        
        if not self.validate_path(full_path):
            raise PermissionError(f"路径禁止访问: {full_path}")
        
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def safe_write(self, relative_path: str, content: str):
        """安全写入文件"""
        if not self.validate_path(relative_path):
            raise PermissionError(f"路径禁止访问: {relative_path}")
        
        full_path = os.path.join(self.workspace, relative_path)
        
        if not self.validate_path(full_path):
            raise PermissionError(f"路径禁止访问: {full_path}")
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        self.audit("file_write", {"path": relative_path, "size": len(content)})


# ── 便捷函数 ─────────────────────────────────────────────────────────

def create_guard(base_dir: str, node_id: str) -> Guard:
    """创建守卫实例"""
    return Guard(base_dir, node_id)


if __name__ == "__main__":
    # 测试
    g = Guard("D:\\claw\\swarm", "test-node")
    print(f"工作目录: {g.workspace}")
    print(f"路径验证测试: {g.validate_path('D:\\claw\\swarm\\queue\\test.json')}")
    print(f"命令验证测试: {g.validate_command('ls -la')}")
    print("Guard 模块加载成功!")
