# Changelog

All notable changes to ClawSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] - 2026-04-15

### Added
- **
oles.py** (NEW): Agent 角色系统
  - 6 个预定义角色：Researcher / Writer / Coder / Analyzer / Reviewer / Planner
  - RoleRegistry 全局注册表：register / create_agent / load_from_file
  - AgentProfile：角色实例（role/goal/backstory/tools/memory）
  - system_prompt()：自动生成 LLM system prompt
  - preset teams: create_research_team() / create_dev_team()

- **llm.py** (NEW): LLM 抽象层
  - 4 个 Provider：OpenAI / Anthropic / Gemini / Ollama
  - 统一接口：LLMProvider / Message / ChatResponse
  - chat() 快捷函数：单次对话
  - 5 个预置工具定义：web_search / web_fetch / code_execute / file_read / file_write
  - 工厂函数 create_llm_client() 自动选择 Provider

- **memory.py** (NEW): Agent 记忆系统
  - ShortTermMemory：ring buffer 对话历史，自动摘要压缩
  - LongTermMemory：持久化 JSONL，BM25 关键词搜索，跨会话
  - WorkingMemory：TaskContext 管理当前任务状态和中间产物
  - MemoryStore：统一接口，short + long + working 三层记忆

- **Orchestrator LLM 驱动**：TaskDecomposer LLM 智能分解 + ResultAggregator LLM 聚合

### Changed
- orchestrator.py：重构，LLM 智能分解（降级到规则引擎 fallback）
- orchestrator.py：改进 ResultAggregator，优先 LLM 合成报告
- classify_task()：加权评分（词频 + 关键词长度）

### Testing
- 新增 test_v040.py：27 个测试，覆盖 roles / llm / memory / orchestrator
- 全量测试 49/49 通过

---

---

## [0.3.0] - 2026-04-15

### Added
- **`orchestrator.py`** (NEW): 任务编排器，核心模块
  - `TaskDecomposer`: 规则引擎分解高层任务为 DAG，自动注入依赖
  - `ResultWatcher`: watchdog 实时监听 results/ 目录，新结果立即通知
  - `ResultAggregator`: 收集子任务结果，聚合成结构化报告
  - `Orchestrator.run(description)`: 一句话端到端执行
- **`watchdog push 模式**: `swarm_node` 监听 queue/ 目录，任务出现立刻执行（无需轮询等待）
- **executor 真实执行**:
  - `fetch` 模式: aiohttp 真实抓取网页，含 HTML→纯文本 去标签
  - `exec` 模式: asyncio.create_subprocess_shell 真实执行系统命令
  - `python` 模式: exec() 执行 Python 代码，捕获 stdout/stderr
  - `spawn` 模式: 尝试调用 openclaw CLI，降级为占位符
- **`cli.py run` 命令**: 编排执行高层任务，完整输出聚合结果
- **命令行 UTF-8 编码**: Windows 环境下正确输出中文

### Changed
- `swarm_node.py`: watchdog push 模式 + asyncio 引入 + executor 真实执行接入
- `executor.py`: 所有执行方法从占位符升级为真实实现
- `run_node.py`: 使用 paths.py 替代硬编码
- `cli.py`: 全文重写（PowerShell -replace 损坏中文），新增 start-cluster / run 命令

### Fixed
- `executor.TaskStatus` 枚举值在测试中断言失败 → 统一用字符串比较
- `swarm_node._execute_spawn` 无 prompt 抛异常 → 降级为占位符
- `swarm_node` 无法导入 executor (`ExecutionMode` 已移除) → 修复 import
- `swarm_node.execute_task` prompt→URL fallback 路径缺失 → 修复
- `cli.py add-task` AttributeError → 修复参数引用

### Removed
- `start_cluster.py` 合并到 `cli.py start-cluster` 命令

### Performance
- 任务响应从 poll_interval 秒级降至毫秒级（watchdog push）
- executor 并行执行 100 个任务 < 10 秒

### Testing
- 全量测试 22/22 通过
- 端到端验证: fetch httpbin.org → HTTP 200 → 真实内容 → 结果写入 ✓

---

## [0.2.0] - 2026-04-15

### Breaking Changes
- `BASE_DIR` 不再硬编码为 `D:\claw\swarm`，改为通过 `paths.py` 动态解析：
  1. 环境变量 `CLAWSWARM_HOME`
  2. `swarm_config.json` 中的 `base_dir` 字段
  3. 默认 `./swarm_data/`（项目目录下，已加入 .gitignore）

### Added
- **`paths.py`**: 集中路径管理 + 能力映射 + 节点选择函数
  - `can_node_handle(task_type, node_capabilities)`: 能力匹配
  - `find_best_node(task_type, online_nodes)`: 最优节点选择（负载最低优先）
  - `CAPABILITY_MAP`: 8 种任务类型的能力需求定义
- **能力感知调度**: `swarm_scheduler.create_task()` 自动匹配合适节点，写入 `assigned_to`
- **能力过滤抢占**: `swarm_node.poll_task()` 根据节点能力过滤任务，避免无效抢占
- **executor 集成**: `swarm_node.execute_task()` 接入 executor 模块，根据 task.type 分发执行

### Changed
- `swarm_scheduler.py`: 移除硬编码路径，导入 paths；Scheduler 类不再修改全局变量
- `swarm_node.py`: 移除硬编码路径和重复的 Guard/审计代码，统一使用 paths
- `executor.py`: 移除重复枚举定义，统一从 models.py 导入 TaskStatus/TaskMode
- `api.py`: 移除重复的 Task/Node/TaskStatus 定义，统一从 models.py 导入
- `config.py`: pyyaml 改为可选依赖（缺少时优雅降级）
- `monitor.py`: psutil 改为可选依赖（缺少时 MonitorService 降级运行）
- `requirements.txt`: 添加 pyyaml, psutil
- `pyproject.toml`: 版本号更新为 0.2.0；添加 monitor optional deps

### Removed
- 删除 `clawswarm-v0.1.zip`（不应提交到仓库）
- 删除 `test_write.txt`（临时文件）

### Fixed
- `.gitignore` 新增 `swarm_data/`, `*.zip`, `*.tar.gz`, `test_write.txt`
- 修复 `Scheduler` 类修改全局变量的副作用问题
- 修复 `swarm_node` 中 `_dirs()` 动态路径函数与模块级路径常量不一致
- 测试全部通过 (22/22)

---

## [0.1.0] - 2026-04-15

### Added
- 🎉 Initial release
- Multi-node task queue system
- Node heartbeat monitoring
- Task lifecycle management (pending → running → done/failed)
- Atomic file operations for race condition prevention
- Basic task recovery for stale tasks
- CLI tools: add_task, status, batch_add
- 3-node demo cluster (claw_alpha, claw_beta, claw_gamma)
- Documentation: ARCHITECTURE, EVOLUTION, TASK-FORMAT, NODE-CONFIG, API

### Features
- **Task Distribution**: One command distributes to multiple nodes
- **Capability Routing**: Auto-assign tasks based on node capabilities
- **Result Aggregation**: Collect results from all nodes
- **Persistence**: Queue persists, nodes resume after restart
- **Cross-machine Support**: Works across LAN via shared storage

### Node Capabilities
| Node | Capabilities |
|------|--------------|
| claw_alpha | search, write, code |
| claw_beta | read, write |
| claw_gamma | search, analyze, report |

---

## [0.2.0] - Planned

### Planned Features
- [ ] Capability-based smart scheduling
- [ ] Real task execution integration (sessions_spawn, web_fetch)
- [ ] Task dependency graph
- [ ] Priority queue support
- [ ] Result aggregation pipeline
- [ ] Web dashboard

---

## [1.0.0] - Planned (MVP Release)

### Planned Features
- [ ] Complete task orchestration engine
- [ ] Multi-machine deployment (SMB/REST)
- [ ] Failure recovery and retry logic
- [ ] Comprehensive test suite
- [ ] OpenClaw Skill integration

---

## [2.0.0] - Planned (Product-Ready)

### Planned Features
- [ ] Cloud-native deployment
- [ ] Web API (REST + WebSocket)
- [ ] Task DAG DSL
- [ ] Advanced scheduling (affinity, load balancing)
- [ ] Monitoring dashboard
- [ ] Commercial license option

---

## Version History

| Version | Date | Status |
|---------|------|--------|
| 0.1.0 | 2026-04-15 | ✅ Released |
| 0.2.0 | TBD | 🔄 In Progress |
| 1.0.0 | TBD | 📋 Planned |
| 2.0.0 | TBD | 📋 Planned |

---

## Migration Guides

### Upgrading to 0.2.0

TBD

### Upgrading to 1.0.0

TBD
