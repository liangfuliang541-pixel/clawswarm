# ClawSwarm 沙箱 - 隔离与防污染规范

[English](SANDBOX.md) | 中文版

> "任何任务都不能污染另一个任务的宇宙"

---

## 🏗️ 设计原则

### 1. 爆炸范围 (Blast Radius)

每个任务都在一个**受限的爆炸范围内**运行：

```
任务爆炸范围
┌────────────────────────────────────────┐
│           允许区域                      │
│  ┌──────────────────────────────────┐  │
│  │  /claw/nodes/{node}/tasks/{id}/ │  │
│  │   ├── input/    (只读)           │  │
│  │   ├── output/   (写入)           │  │
│  │   ├── temp/     (写入, 自动清理)  │  │
│  │   └── .env      (隔离环境)        │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ❌ 禁止区域：                           │
│  - ../sibling_tasks/                    │
│  - ../../other_nodes/                   │
│  - C:\Windows, /etc, ~/.ssh             │
└────────────────────────────────────────┘
```

### 2. 隔离层级

| 层级 | 隔离粒度 | 适用场景 |
|------|----------|----------|
| **L1: 节点级** | 每个节点独立工作目录 | 不同机器 |
| **L2: 任务级** | 每个任务独立目录 | 任务间隔离 |
| **L3: 操作级** | exec/网络白名单 | 安全边界 |

---

## 📁 目录结构

```
D:\claw\swarm\
├── swarm_config.json
├── swarm_node.py
├── swarm_scheduler.py
│
├── nodes/                          # ⬅️ L1: 节点隔离
│   ├── claw_alpha/
│   │   ├── config.json             # 节点配置
│   │   ├── workspace/              # 节点工作目录
│   │   │   └── tasks/
│   │   │       ├── t_001/
│   │   │       │   ├── input/      # 任务输入（只读）
│   │   │       │   ├── output/     # 任务产出
│   │   │       │   ├── temp/       # 临时文件（自动清理）
│   │   │       │   ├── logs/       # 执行日志
│   │   │       │   └── sandbox.cfg # 任务约束
│   │   │       │
│   │   │       └── t_002/
│   │   │           └── ...
│   │   │
│   │   └── .node_lock              # 防止双重执行
│   │
│   ├── claw_beta/
│   └── claw_gamma/
│
└── shared/                         # 共享（任务只读）
    ├── queue/                     # Master → Nodes
    ├── results/                   # Nodes → Master
    └── artifacts/                  # 共享资源
```

---

## 🔒 沙箱执行机制

### 1. 路径白名单

```python
class Sandbox:
    """强制执行爆炸范围边界"""
    
    # 绝对白名单 - 任务只能访问这些路径
    ALLOWED_PATHS = [
        "{node_root}/tasks/{task_id}/",  # 自己的任务目录
        "{node_root}/shared/artifacts/", # 共享资源
    ]
    
    # 禁止模式 - 绝不允许
    FORBIDDEN_PATHS = [
        r"..",                          # 父目录穿越
        r"~\.ssh",                       # SSH 密钥
        r"C:\Windows",                   # 系统目录
        r"/etc/passwd",                  # Linux 系统文件
        r"*\nodes\claw_*",              # 其他节点（动态）
        r"*\tasks\t_[0-9a-f]{12}",      # 其他任务（动态）
    ]
```

### 2. Exec 命令白名单

```python
class ExecSandbox:
    """限制可执行的命令"""
    
    # 允许执行的命令
    ALLOWED_COMMANDS = {
        # 只读操作
        "git clone": {"max_time": 300, "max_output": "10MB"},
        "git pull": {},
        "curl": {"args": ["-s", "-L", "--max-time"]},
        
        # Python 执行
        "python": {"args": ["-c", "script.py"]},
        "pip install": {"args": ["--quiet", "-r"]},
        
        # 本地文件操作
        "mkdir": {},
        "cp": {"src": "local", "dst": "local"},
    }
    
    # 绝对禁止的命令
    FORBIDDEN_COMMANDS = [
        "rm -rf /",           # 核弹选项
        "del /f /s /q C:\\", # Windows 核弹
        "format",             # 格式化
        "shutdown",           # 关机
        "powershell -c",     # 任意 PowerShell
    ]
```

---

## 🛡️ 防污染机制

### 1. 原子操作

```python
class AtomicTask:
    """原子性执行任务"""
    
    def execute(self):
        # 步骤 1: 原子性抢占任务
        self.reserve_task()  # queue/ → in_progress/
        
        try:
            # 步骤 2: 创建沙箱
            sandbox = self.create_sandbox()
            
            # 步骤 3: 在沙箱内执行
            result = self.run_in_sandbox(sandbox)
            
            # 步骤 4: 原子性提交结果
            self.commit_result(result)  # in_progress/ → results/
            
        except Exception as e:
            # 步骤 5: 原子性回滚
            self.rollback()
            raise
        finally:
            # 步骤 6: 清理临时文件
            self.cleanup_temp()
```

### 2. 资源泄漏防护

```python
class ResourceGuard:
    """确保资源被正确释放"""
    
    def __init__(self):
        self.open_files = []
    
    def open(self, path, mode):
        fd = os.open(path, mode)
        self.open_files.append(fd)
        return fd
    
    def __exit__(self):
        # 即使代码忘记关闭，也要全部关闭
        for fd in self.open_files:
            try:
                os.close(fd)
            except:
                pass
```

### 3. 环境变量隔离

```python
class EnvSandbox:
    """隔离环境变量"""
    
    # 任务可以修改的变量
    ALLOWED_VARS = [
        "PATH",
        "PYTHONPATH",
        "TASK_ID",
        "NODE_ID",
    ]
    
    # 禁止修改的变量
    FORBIDDEN_VARS = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_KEY",
        "OPENCLAW_API_KEY",
        "DATABASE_URL",
    ]
```

---

## 📊 日志与审计

### 操作日志

每个文件/网络/exec 操作都会被记录：

```json
{
  "timestamp": "2026-04-15T10:30:00Z",
  "task_id": "t_7b1df909df3a",
  "node_id": "claw_alpha",
  "operation": "file_write",
  "path": "D:\\claw\\swarm\\nodes\\claw_alpha\\tasks\\t_7b1df909df3a\\output\\result.json",
  "size_bytes": 1024,
  "status": "success"
}
```

### 违规日志

违规尝试会被记录和告警：

```json
{
  "timestamp": "2026-04-15T10:30:00Z",
  "task_id": "t_7b1df909df3a",
  "node_id": "claw_alpha",
  "violation": "PATH_TRAVERSAL",
  "attempted_path": "D:\\claw\\swarm\\nodes\\claw_beta\\tasks\\t_002\\input\\secret.txt",
  "action": "BLOCKED"
}
```

---

## ⚡ 快速参考

| 机制 | 作用 | 实现方式 |
|------|------|----------|
| **爆炸范围** | 限制任务影响 | 路径白名单 |
| **原子操作** | 防止中间态 | rename() 而非 copy+delete |
| **资源守卫** | 防止资源泄漏 | 自动关闭文件描述符 |
| **环境沙箱** | 防止环境变量污染 | 快照/恢复环境 |
| **Exec 白名单** | 防止命令注入 | 命令白名单 |
| **审计日志** | 追踪违规 | JSON 日志 |

---

## 🚀 实现优先级

| 优先级 | 特性 | 复杂度 | 影响 |
|--------|------|--------|------|
| **P0** | 任务目录隔离 | 中 | 关键 |
| **P0** | 路径穿越防护 | 高 | 关键 |
| **P1** | Exec 白名单 | 中 | 高 |
| **P1** | 环境变量隔离 | 低 | 中 |
| **P2** | 审计日志 | 低 | 中 |
| **P3** | 网络访问控制 | 高 | 低 |

---

## 📝 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) - 系统架构
- [NODE-CONFIG.md](NODE-CONFIG.md) - 节点配置
- [TASK-FORMAT.md](TASK-FORMAT.md) - 任务规范
