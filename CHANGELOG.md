# Changelog

All notable changes to ClawSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.12.0] - 2026-04-19

### Added
- **`task_queue.py`** (NEW): 高级任务队列 — 优先级排序、指数退避重试、延迟执行、死信队列、磁盘持久化、事件回调
- **`auth.py`** (NEW): 认证授权系统 — API Key（SHA256 哈希）、JWT（HS256 签名）、RBAC 4 角色权限、速率限制
- **`metrics.py`** (NEW): Prometheus 兼容指标收集 — Counter/Gauge/Histogram/Summary、注册表、Prometheus 文本导出
- **`tenant.py`** (NEW): 多租户隔离 — 命名空间、成员管理、配额限制、权限检查
- **`federated.py`** (NEW): 联邦学习协调器 — FedAvg/FedProx 聚合、轮次管理、节点更新、全局模型
- **`edge.py`** (NEW): 边缘计算适配器 — HTTP/MQTT/WebSocket/CoAP 协议、心跳监控、发布订阅
- **`autoscale.py`** (NEW): 自动扩缩容 — 负载感知、冷却策略、弹性伸缩、事件历史

### Changed
- **`dashboard.py`**: `/api/nodes` 从 Hub 获取已注册 Agent，合并 Monitor + Hub 节点列表
- **`dashboard/index.html`**: v3.0 功能丰富版 — 任务详情 Modal、节点终端、全局搜索、任务过滤、设置面板、日志标签页

### Stats
- Python source: **23,001 行** (69 文件)
- Test code: **2,081 行** (8 文件, 164 tests)
- Dashboard HTML: **945 行**
- Documentation: **8,983 行**
- **Total: 35,010 行**

---

## [0.11.0] - 2026-04-18

### Added
- **`agent_adapter.py`** (NEW): 异构 Agent 适配器基类 — `AgentAdapter` 抽象类 + `@register_adapter` 注册装饰器 + `get_adapter()` 工厂函数
- **`hermes_adapter.py`** (NEW): Hermes ACP 协议适配器 — stdin/stdout JSON-RPC 2.0，完整 ACP 握手（//ready → initialize → authenticate → session/new → session/prompt）
- **`evolver_adapter.py`** (NEW): Evolver 适配器 — 优先 `sessions_send` 注入，回退文件轮询 `.clawswarm_evolver_tasks/`
- **`openclaw_adapter.py`** (NEW): 原生 OpenClaw 适配器 — HTTP Hub 注册 + 轮询
- **`networking.py`** (UPDATED): HubAgent 集成 adapter — `adapter_type` + `adapter_config` 参数，`execute_task()` 委托给适配器，`start()/stop()` 管理适配器生命周期，CLI `--adapter-type` 和 `--adapter-config` 参数
- **`master_api.py`** (UPDATED): Hub 嵌入 + ThreadingTCPServer 修复 + `--hub-port` 参数

### Tests
- `tests/test_agent_adapter.py`: 45 单元测试（适配器基类、注册表、Hermes、Evolver、OpenClaw）
- `tests/test_hub_agent_adapter.py`: 11 集成测试（HubAgent + adapter 端到端：注册→任务下发→执行→结果提交）
- Total: 164/164 passed, zero regressions

---

## [0.10.0] - 2026-04-17

### Added
- **`networking.py`** (NEW): Hub-Spoke 跨公网通信模块 — `HubServer`(Hub端) + `HubAgent`(Agent端 HTTP client) + `HubClient`(主控端)，无需 tunnel/SSH/公网 IP
- **`spawn_manager.py`** (REWRITTEN): 文件队列 + 后台线程 spawn 管理
- **`inter_agent_protocol.py`** (NEW): Agent 间通信协议库
- **`clawchat.py`** (NEW): Agent 间实时聊天 — SQLite + FastAPI + WebSocket + RelayBridge
- **`demo_viral.py`** (NEW): 3 机并行 viral demo
- **License**: AGPL → MIT (commit 2fb5556)

### Fixed
- `swarm_scheduler.py` + `swarm_node.py`: 4 critical bugs — `type` builtin shadowing, stale spawn loop, KeyError `task["id"]`, capability map fetch
- `executor._execute_fetch`: URL extraction from prompt (was concatenating prompt as URL)
- `master_api.py`: HTTPServer → ThreadingTCPServer (single-threaded blocking fix), serve_forever() try/except

---

## [0.8.5] - 2026-04-16

### Added
- **`dead_letter.py`** (NEW): 死信队列 — enqueue/list/retry/purge/stats
- **`health_scorer.py`** (NEW): 节点健康评分 — 5 维加权（heartbeat/success_rate/load/response_time/error_rate）
  - 4 级健康：healthy/degraded/warning/critical
  - 熔断建议 + 任务优先级限制
- **`result_pipeline.py`** (NEW): 结果聚合流水线 — 5 阶段（collect/filter/transform/aggregate/export）
- **MCP Server**: 6 → 8 tools
  - `clawswarm_dead_letter`: 死信队列管理（list/retry/purge/stats）
  - `clawswarm_health`: 节点健康评分（5 维分解 + 熔断建议）
- **`paths.py`**: 新增 `DEAD_LETTER_DIR` + `PIPELINE_DIR`
- **README.md / README_CN.md**: 顶部 badge + Features 重写

### Tests
- `tests/test_v085.py`: 23 new tests (DLQ: 7, Health: 6, Pipeline: 7, MCP: 3)
- Total: 84 → 107 tests, all passing

---

## [0.8.0] - 2026-04-16

### Added
- **`mcp_server.py`** (NEW): MCP Server 实现 — 6个 MCP tools（spawn/poll/submit/status/nodes/aggregate）
  - 基于 stdio 的 JSON-RPC 实现，符合 Anthropic MCP 协议（protocolVersion: 2024-11-05）
  - 其他 Agent 可通过 MCP 协议调用 ClawSwarm
  - 核心定位：**让龙虾间互相调用工具**
- **`skill/SKILL.md`** (UPDATED): MCP Server 集成到 Skill
  - 新增方式 B：通过 `mcporter call clawswarm.*` 调用 MCP tools
  - 方式 A（sessions_spawn）+ 方式 B（MCP）双模式编排
  - 方式选择指南表
- **`dashboard/`** (NEW): Web UI 监控面板
  - FastAPI + WebSocket 实时推送
  - 任务 DAG 可视化 + 节点状态 + 事件日志
  - `python dashboard/dashboard.py --port 5000`
- **`.github/workflows/ci.yml`** (NEW): GitHub Actions CI/CD
  - pytest 多版本测试（Python 3.10/3.11/3.12）
  - ruff/mypy linting
  - Dashboard 启动测试
  - MCP Server 初始化测试
- **`examples/`**: 新增示例脚本
  - `01_quickstart.py`: 快速上手（提交 + 轮询）
  - `02_parallel.py`: 并行任务 + 结果聚合
  - `04_mcp_demo.py`: MCP 协议调用示例

### Fixed
- `executor.py`: `RESULTS_DIR` 从字符串改为 `Path` 对象

---

## [0.7.0] - 2026-04-15

### Added
- **`skill/`** (NEW): OpenClaw Skill 包 — 一键安装到 OpenClaw
  - `SKILL.md`：ClawSwarm 编排指令（给 AI 读的说明文档）
  - `scripts/spawn.py`：Agent 启动脚本（通过 sessions_spawn）
  - `scripts/poll.py`：结果轮询脚本
  - `scripts/aggregate.py`：结果聚合脚本

- **`executor._execute_spawn`** (重构): 真正的 sessions_spawn 集成
  - 写入任务文件到 queue/，session_spawn 读取并执行
  - 返回 task_file、result_file 路径供 AI 后续处理

### Changed
- `executor._execute_spawn`：移除 openclaw CLI fallback 逻辑
- `executor.py`：导入 paths.RESULTS_DIR / QUEUE_DIR

### Architecture
- `sessions_spawn` 是 OpenClaw LLM tool，只能在 AI session 内部调用
- Python 进程通过文件队列与 AI 协作
- Skill 目录可在 `~/.openclaw/workspace/skills/clawswarm/` 安装

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

