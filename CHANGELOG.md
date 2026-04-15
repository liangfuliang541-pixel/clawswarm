# Changelog

All notable changes to ClawSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
