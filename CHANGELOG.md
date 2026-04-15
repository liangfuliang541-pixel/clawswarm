# Changelog

All notable changes to ClawSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
