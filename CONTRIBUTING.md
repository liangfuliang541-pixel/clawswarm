# Contributing to ClawSwarm

English | [中文](CONTRIBUTING_CN.md)

Welcome! We're excited that you're interested in contributing to ClawSwarm. This guide will help you get started.

---

## 🤝 How to Contribute

### 1. Report Bugs

Found a bug? Please open an issue with:
- Clear title
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version)

### 2. Suggest Features

Have a great idea? Open a feature request and describe:
- What problem does it solve?
- Proposed solution
- Alternative solutions considered

### 3. Pull Requests

We welcome code contributions! Here's how:

1. **Fork** the repository
2. **Create** a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make** your changes
4. **Test** your changes
5. **Commit** with clear messages:
   ```bash
   git commit -m 'Add: New feature for task dependency'
   ```
6. **Push** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
7. **Create** a Pull Request

---

## 📋 Pull Request Guidelines

### Code Style

- Use **Python 3.8+**
- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Use meaningful variable names
- Add docstrings to new functions

### Commit Messages

Use conventional commits:

```
feat:     # New feature
fix:      # Bug fix
docs:     # Documentation
refactor: # Code refactoring
test:     # Tests
chore:    # Maintenance
```

Example:
```
feat: Add capability-based task routing

- Implemented skill matching between tasks and nodes
- Added load balancing for nodes with same capabilities
- Updated scheduler to support priority queue
```

### Testing

Before submitting a PR:

```bash
# Test locally
python -m pytest tests/ -v

# Run specific tests
python -m pytest tests/test_v060.py -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=html
```

All 84 tests must pass (including v0.6 checkpoint + observability tests).
New modules must include tests in `tests/test_{module}.py`.

---

## 🌍 Development Setup

Before adding new modules, read [MODULES.md](MODULES.md) for the full module index.

---

## 🏠 Module-Specific Guidelines

### HITL Checkpoint (`checkpoint.py`)

When adding new checkpoint types or policies:
1. Add type/policy constants with docstrings
2. Update `HITLPolicy.should_require()` logic
3. Add notification handler (WebSocket/Webhook/OpenClaw)
4. Add corresponding CLI command in `cli.py`
5. Add tests covering all policy combinations

### Observability (`observability.py`)

When adding new metrics or spans:
1. Use `@traced` decorator for all public functions
2. Emit events via `events.emit()` for significant state changes
3. Add Prometheus metric with descriptive labels
4. Update `MODULES.md` with new metric names
5. No `print()` — use `from observability import log`

### WebSocket Events (`events.py`)

When adding new event types:
1. Define type constant in `observability.py` EventType enum
2. Emit via `events.emit(type, data)` in relevant modules
3. Document in `docs/DEPLOY.md` WebSocket protocol section
4. Add listener test in `tests/test_v060.py`

### LLM Providers (`llm.py`)

When adding a new LLM provider:
1. Create provider class inheriting `BaseLLMClient`
2. Implement `chat()`, `tools()`, `chat_stream()` methods
3. Register in `LLM_REGISTRY` dictionary
4. Add tools definitions for the provider's tool-calling format
5. Add tests with mock API responses
6. Update `MODULES.md` provider table

### OpenClaw Integration

When adding OpenClaw-specific features:
1. Check `openclaw help` for available commands
2. Use `sessions_spawn` for spawning sub-agents
3. Wrap OpenClaw calls in try/except for graceful degradation
4. Test on both local and remote OpenClaw instances

---

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/clawswarm.git
cd clawswarm

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest
```

---

## 📖 Documentation

We need help improving documentation! You can:

- Fix typos or unclear explanations
- Translate docs to other languages
- Add examples and tutorials
- Create diagrams and flowcharts

---

## 💬 Join the Community

- 📖 [Documentation](docs/)
- 🐛 [Issue Tracker](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- 💬 [Discussions](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

## ⭐ Recognition

Every contributor will be recognized! Contributors list will be added to README.

Thank you for making ClawSwarm better! 🦞
