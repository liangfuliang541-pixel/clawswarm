# ClawSwarm Sandbox - 隔离与防污染规范

English | [中文](SANDBOX_CN.md)

> "No task shall pollute another task's universe."

---

## 🏗️ 设计原则

### 1. 爆炸范围 (Blast Radius)

Every task operates within a **contained blast radius**:

```
Task Blast Radius
┌────────────────────────────────────────┐
│           Allowed Zone                 │
│  ┌──────────────────────────────────┐  │
│  │  /claw/nodes/{node}/tasks/{id}/ │  │
│  │  ├── input/    (read-only)       │  │
│  │  ├── output/   (write)           │  │
│  │  ├── temp/     (write, cleanup)  │  │
│  │  └── .env      (isolated env)     │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ❌ Forbidden:                         │
│  - ../sibling_tasks/                   │
│  - ../../other_nodes/                  │
│  - C:\Windows, /etc, ~/.ssh            │
└────────────────────────────────────────┘
```

### 2. 隔离层级

| Level | Isolation | Use Case |
|-------|-----------|----------|
| **L1: Node** | Separate workspace per node | Different machines |
| **L2: Task** | Separate directory per task | Task independence |
| **L3: Operation** | Whitelist for exec/web | Security boundary |

---

## 📁 Directory Structure

```
D:\claw\swarm\
├── swarm_config.json
├── swarm_node.py
├── swarm_scheduler.py
│
├── nodes/                          # ⬅️ L1: Node Isolation
│   ├── claw_alpha/
│   │   ├── config.json             # Node-specific settings
│   │   ├── workspace/              # Node's working directory
│   │   │   └── tasks/
│   │   │       ├── t_001/
│   │   │       │   ├── input/      # Task inputs (symlink/copy)
│   │   │       │   ├── output/     # Task outputs
│   │   │       │   ├── temp/       # Temp files (auto-clean)
│   │   │       │   ├── logs/       # Execution logs
│   │   │       │   └── sandbox.cfg # Task constraints
│   │   │       │
│   │   │       └── t_002/
│   │   │           └── ...
│   │   │
│   │   └── .node_lock              # Prevent dual execution
│   │
│   ├── claw_beta/
│   └── claw_gamma/
│
└── shared/                         # Shared (read-only for tasks)
    ├── queue/                     # Master → Nodes
    ├── results/                   # Nodes → Master
    └── artifacts/                  # Shared resources
```

---

## 🔒 Sandbox Enforcement

### Path Whitelist

```python
class Sandbox:
    """Enforces blast radius boundaries."""
    
    # Absolute whitelist - tasks CAN access ONLY these
    ALLOWED_PATHS = [
        "{node_root}/tasks/{task_id}/",  # Own task dir
        "{node_root}/shared/artifacts/", # Shared resources
    ]
    
    # Forbidden patterns - NEVER allow
    FORBIDDEN_PATHS = [
        r"..",                          # Parent directory traversal
        r"~\.ssh",                       # SSH keys
        r"C:\Windows",                  # System directories
        r"/etc/passwd",                  # Linux system files
        r"\*\nodes\claw_",              # Other nodes (dynamic)
        r"\*\tasks\t_[0-9a-f]{12}",     # Other tasks (dynamic)
    ]
    
    def validate_path(self, path: str) -> bool:
        """Check if path is within blast radius."""
        # 1. Check against forbidden patterns
        for pattern in self.FORBIDDEN_PATHS:
            if fnmatch(path, pattern):
                return False
        
        # 2. Ensure path is under allowed root
        task_root = f"{self.node_root}/tasks/{self.task_id}/"
        return path.startswith(task_root) or path.startswith(self.shared_root)
```

### Exec Command Whitelist

```python
class ExecSandbox:
    """Restricts what commands can be executed."""
    
    # Commands ALLOWED for task execution
    ALLOWED_COMMANDS = {
        # Read-only operations
        "git clone": {"max_time": 300, "max_output": "10MB"},
        "git pull": {},
        "curl": {"args": ["-s", "-L", "--max-time"]},
        "wget": {},
        
        # Python execution
        "python": {"args": ["-c", "script.py"]},
        "pip install": {"args": ["--quiet", "-r"]},
        
        # File operations (local only)
        "mkdir": {},
        "cp": {"src": "local", "dst": "local"},
        "mv": {"src": "local", "dst": "local"},
    }
    
    # Commands STRICTLY FORBIDDEN
    FORBIDDEN_COMMANDS = [
        "rm -rf /",           # Nuclear option
        "del /f /s /q C:\\", # Windows nuclear
        "format",             # Drive format
        "shutdown",           # System control
        "powershell -c",     # Arbitrary PS (too broad)
        "cmd /c",            # Arbitrary CMD
    ]
```

---

## 🛡️ Anti-Pollution Mechanisms

### 1. Atomic Operations

```python
class AtomicTask:
    """Execute task atomically."""
    
    def execute(self):
        # Step 1: Reserve task (atomic rename)
        self.reserve_task()  # queue/ → in_progress/
        
        try:
            # Step 2: Create sandbox
            sandbox = self.create_sandbox()
            
            # Step 3: Execute within bounds
            result = self.run_in_sandbox(sandbox)
            
            # Step 4: Atomically commit result
            self.commit_result(result)  # in_progress/ → results/
            
        except Exception as e:
            # Step 5: Atomic rollback
            self.rollback()
            raise
        finally:
            # Step 6: Cleanup temp files
            self.cleanup_temp()
```

### 2. File Descriptor Leaks Prevention

```python
class ResourceGuard:
    """Ensure resources are cleaned up."""
    
    def __init__(self):
        self.open_files = []
    
    def open(self, path, mode):
        fd = os.open(path, mode)
        self.open_files.append(fd)
        return fd
    
    def __exit__(self):
        # Close ALL files, even if code forgot
        for fd in self.open_files:
            try:
                os.close(fd)
            except:
                pass
```

### 3. Environment Isolation

```python
class EnvSandbox:
    """Isolate environment variables."""
    
    # Variables that CAN be modified by tasks
    ALLOWED_VARS = [
        "PATH",           # May need custom bins
        "PYTHONPATH",     # For local packages
        "TASK_ID",       # Task context
        "NODE_ID",       # Node context
    ]
    
    # Variables that are FORBIDDEN to modify
    FORBIDDEN_VARS = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_KEY",
        "OPENCLAW_API_KEY",
        "DATABASE_URL",
    ]
    
    def execute(self, task):
        # Save original env
        original = os.environ.copy()
        
        try:
            # Apply task-specific env
            task_env = self.load_task_env(task)
            os.environ.update(task_env)
            
            # Run task
            task.run()
            
        finally:
            # Restore original env (CRITICAL)
            os.environ.clear()
            os.environ.update(original)
```

---

## 📊 Logging & Auditing

### Operation Log

Every file/network/exec operation is logged:

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

### Violation Log

Attempted violations are logged and alerted:

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

## ⚡ Quick Reference

| Mechanism | Purpose | Implementation |
|-----------|---------|----------------|
| **Blast Radius** | Contain task effects | Path whitelist |
| **Atomic Ops** | Prevent partial states | rename() not copy+delete |
| **Resource Guard** | Prevent leaks | Auto-close file descriptors |
| **Env Sandbox** | Prevent env pollution | Snapshot/restore env |
| **Exec Whitelist** | Prevent command injection | Command whitelist |
| **Audit Log** | Track violations | JSON log per task |

---

## 🚀 Implementation Priority

| Priority | Feature | Complexity | Impact |
|----------|---------|------------|--------|
| **P0** | Task directory isolation | Medium | Critical |
| **P0** | Path traversal prevention | High | Critical |
| **P1** | Exec whitelist | Medium | High |
| **P1** | Environment isolation | Low | Medium |
| **P2** | Audit logging | Low | Medium |
| **P3** | Network access control | High | Low |

---

## 📝 Related Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [NODE-CONFIG.md](NODE-CONFIG.md) - Node configuration
- [TASK-FORMAT.md](TASK-FORMAT.md) - Task specification
