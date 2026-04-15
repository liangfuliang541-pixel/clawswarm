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
python -m pytest tests/

# Run specific tests
python -m pytest tests/test_scheduler.py -v
```

---

## 🌍 Development Setup

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
