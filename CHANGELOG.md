# Changelog

All notable changes to ClawSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

---

## [0.6.0] - 2026-04-15

### Added
- **`checkpoint.py`** (NEW): Human-in-the-Loop 检查点系统
  - CheckpointManager：全局检查点管理（创建/等待/批准/拒绝）
  - Checkpoint：审批点（approval/review/confirm/escalate）
  - HITLPolicy：审批策略（always_approve / always_require / by_priority / by_task_type）
  - 通知方式：Webhook / OpenClaw消息 / WebSocket / CLI
  - CLI 命令：approve / reject / list / stats / set-policy / test
  - 文件持久化：pending/approved/rejected 三层目录

- **`observability.py`** (NEW): 可观察性模块（OpenTelemetry 集成）
  - tracer：分布式追踪（OpenTelemetry span，支持 OTLP 导出）
  - MetricsCollector：Counter/Gauge/Histogram，支持 Prometheus 格式导出
  - StructuredLogger：JSON 结构化日志，带 trace_id
  - EventEmitter：事件发射器（task.* / checkpoint.* / node.*）
  - 优雅降级：无 OpenTelemetry 包时自动切换到 NoOp 实现
  - @traced 装饰器：自动追踪函数执行

- **`events.py`** (NEW): WebSocket 实时事件服务器
  - EventServer：异步 WebSocket 服务器（端口 8765）
  - 事件订阅：支持 glob 风格过滤（task.* / checkpoint.*）
  - 指标推送：定期推送 Prometheus 格式指标
  - 历史事件：最近 100 条事件缓存
  - HTTP 端点：/health / /stats / /ws
  - 优雅降级：无 websockets 包时模块可导入但服务不可启动

### Changed
- `observability.py`：修复 warn() 弃用警告 → 使用 warning()

### Deployment (NEW)
- **`Dockerfile`**：多阶段构建，Python 3.12 slim，暴露 5000/5171/8765 端口
- **`docker-compose.yml`**：master + events + node-alpha + node-beta 一键启动
- **`.env.template`**：所有环境变量模板（LLM / OpenTelemetry / WebSocket / HITL）
- **`deploy.sh`**：一键部署脚本（local / docker / status / stop / install-deps）
- **`requirements.txt`**：补全所有依赖（aiohttp / opentelemetry / websockets）
- **`.gitignore`**：完善，exclude .env / queue/ / in_progress/ 等运行时文件

### Testing
- 新增 test_v060.py：20 个测试（checkpoint / observability）
- 全量测试 84/84 全部通过（0 warnings）

---

## [0.5.0] - 2026-04-15

### Added
- **`node_api.py`** (NEW): 节点 HTTP API 服务
  - 每个节点运行轻量 HTTP 服务（默认 5171+ 端口）
  - GET /status — 节点状态（能力/当前任务/运行时间）
  - GET /health — 健康检查
  - GET /tasks — 列出节点当前任务
  - POST /poll — 节点主动拉取任务（能力匹配）
  - POST /complete — 提交任务结果
  - POST /execute — 主龙虾推送任务直接执行
  - POST /shutdown — 优雅关闭
  - 心跳线程（10 秒自动更新）
  - 注册/注销节点到 agents/ 目录

- **`master_api.py`** (NEW): 主龙虾 HTTP API 服务
  - 主服务器运行 REST API（默认 5000 端口）
  - CORS 支持，允许跨域访问
  - **任务 API**: POST/GET/DELETE /tasks，GET /tasks/{id}/result，POST /tasks/{id}/retry
  - **节点 API**: GET /nodes，GET /nodes/{id}，POST /nodes/{id}/assign，POST /nodes/{id}/wake
  - **系统 API**: GET /health，GET /stats，POST /shutdown
  - TaskRepo：基于文件系统，queue/in_progress/results 三层覆盖
  - NodeRepo：agents/ 目录，支持在线状态检测（心跳 30 秒超时）

- **CLI 升级**: 新增 `start-node-api` / `start-master-api` 命令

### Testing
- 新增 test_v050.py：15 个测试（node_api / master_api / API E2E）
- 全量测试 64/64 全部通过

---

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
