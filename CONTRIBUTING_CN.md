# 贡献指南

[English](CONTRIBUTING.md) | 中文版

感谢你对 ClawSwarm 感兴趣！我们欢迎各种形式的贡献。

---

## 🤝 如何贡献

### 1. 报告 Bug

发现 bug？请提交 Issue，包含：
- 清晰的标题
- 复现步骤
- 预期行为 vs 实际行为
- 环境信息（操作系统、Python 版本）

### 2. 功能建议

有好点子？请提交 Feature Request：
- 解决的问题
- 建议的解决方案
- 考虑过的替代方案

### 3. 提交 Pull Request

我们欢迎代码贡献！步骤如下：

1. **Fork** 本仓库
2. **创建** 功能分支：
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **编写** 你的代码
4. **测试** 你的修改
5. **提交** 并写明修改内容：
   ```bash
   git commit -m 'Add: 新增任务依赖功能'
   ```
6. **推送** 到你的 Fork：
   ```bash
   git push origin feature/your-feature-name
   ```
7. **创建** Pull Request

---

## 📋 Pull Request 规范

### 代码风格

- 使用 **Python 3.8+**
- 遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- 使用有意义的变量名
- 为新函数添加文档字符串

### 提交信息

使用语义化提交：

```
feat:     # 新功能
fix:      # Bug 修复
docs:     # 文档更新
refactor: # 代码重构
test:     # 测试相关
chore:    # 维护工作
```

示例：
```
feat: 新增基于能力的任务路由

- 实现任务与节点的能力匹配
- 添加同能力节点的负载均衡
- 更新调度器支持优先级队列
```

### 测试

提交 PR 前请测试：

```bash
# 本地测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_scheduler.py -v
```

---

## 🌍 开发环境搭建

```bash
# 克隆你的 Fork
git clone https://github.com/YOUR_USERNAME/clawswarm.git
cd clawswarm

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest
```

---

## 📖 文档贡献

我们需要帮助改进文档！你可以：

- 修正拼写或不清楚的解释
- 翻译文档到其他语言
- 添加示例和教程
- 创建图表和流程图

---

## 💬 社区交流

- 📖 [文档](docs/)
- 🐛 [问题追踪](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- 💬 [讨论区](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

## ⭐ 贡献者致谢

每位贡献者都会被记录在案！贡献者列表将添加到 README 中。

感谢你让 ClawSwarm 变得更好！ 🦞
