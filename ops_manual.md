# ClawSwarm 操作手册

**更新时间**：2026-04-18  
**版本**：v0.11.0

---

## 一、当前网络架构

### Hub-Spoke 模式（主力）

```
主控端（Hub，Windows）
  ├─ master_api.py :50010 (REST API)
  └─ HubServer     :18080 (嵌入 master_api.py)

远程 Agent（通过 HTTP 轮询 Hub）
  ├─ OpenClaw Agent (native)
  ├─ Hermes Agent (ACP adapter)
  └─ Evolver Agent (Skill adapter)
```

**关键点**：Hub 不需要公网 IP。Agent 主动轮询 Hub，只有 outbound HTTP。

### 旧 relay 模式（已废弃）

serveo / Cloudflare Tunnel + relay_server.py 已被 Hub-Spoke 取代，不再使用。

---

## 二、Hub HTTP API（:18080）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/hub/status` | Hub 状态（agents 数、任务数、结果数） |
| POST | `/hub/register` | Agent 注册（agent_id, capabilities） |
| GET | `/hub/agents` | 列出所有注册 Agent |
| GET | `/hub/queue/<agent_id>` | Agent 原子 pop 自己的任务 |
| POST | `/hub/submit_task` | 主控端下发任务到指定 Agent |
| POST | `/hub/submit/<task_id>` | Agent 提交任务结果 |
| GET | `/hub/result/<task_id>` | 获取任务结果 |

---

## 三、启动服务

### 主控端（Hub）

```bash
# 启动 master_api + Hub（两个服务同时运行）
python master_api.py --port 50010 --hub-port 18080
```

### Agent 节点

```bash
# 原生 OpenClaw Agent
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id local-01

# Hermes Agent（ACP 协议）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id hermes-01 \
  --adapter-type hermes \
  --adapter-config '{"hermes_bin":"hermes","model":"qwen2.5:72b"}'

# Evolver Agent（OpenClaw Skill）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id evolver-01 \
  --adapter-type evolver \
  --adapter-config '{"workspace":"~/.openclaw/workspace"}'
```

### 下发任务

```bash
# 通过 HubClient
python networking.py client --hub-url http://localhost:18080 \
  --task "Fetch https://httpbin.org/json" --task-type fetch

# 通过 Master API
curl -X POST http://localhost:50010/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"搜索AI最新进展","type":"research","priority":5}'
```

---

## 四、ClawChat（Agent 间聊天）

```bash
# 启动 ClawChat Server（端口 5002）
python clawchat.py --agent main-agent

# HTTP API
GET  /health              # 健康检查
GET  /inbox/{agent_id}    # 收件箱
GET  /conversation/{a}/{b}  # 双人聊天记录
POST /send/{from}/{to}    # 发消息
WebSocket /ws/{agent_id}  # 实时推送
```

Dashboard 右下角内置聊天面板。

---

## 五、Dashboard

```bash
# 启动 Dashboard（端口 5000）
python dashboard/dashboard.py --port 5000
# 打开 http://localhost:5000
```

功能：节点状态、任务 DAG、实时事件流、聊天面板、任务提交。

---

## 六、远程节点部署

### 方案 A：云安全组开端口（推荐）

1. 在云控制台为 VM 开放 Hub 端口（18080）的 inbound 访问
2. VM 上运行 `python networking.py agent --hub-url http://<你的公网IP>:18080 --agent-id vm-01`

### 方案 B：内网穿透

```bash
# ngrok
ngrok http 18080

# cpolar
cpolar http 18080

# Cloudflare Tunnel
cloudflared tunnel --url http://localhost:18080
```

将穿透得到的 URL 作为 Agent 的 `--hub-url`。

---

## 七、Python 通信库

```python
import sys
sys.path.insert(0, "/path/to/clawswarm")
from inter_agent_protocol import AgentClient

relay = AgentClient(
    relay_url="http://hub-ip:18080",
    agent_id="remote-01"
)

# 发消息
relay.send_to("main-agent", "Hub 连接成功！")

# 监听消息
def handle(msg):
    print(f"收到 {msg['from']}: {msg['content']}")
relay.message_loop(handler=handle, poll_interval=5)
```

---

## 八、已知问题

| 问题 | 状态 | 解决方案 |
|------|------|----------|
| VM 安全组端口全封 | 🔴 阻塞 | 云控制台开 18080 端口 |
| Hermes binary 未安装 | 🟡 待做 | 安装 hermes CLI |
| serveo 已废弃 | ✅ 已解决 | 使用 Hub-Spoke 替代 |
| relay_server.py regex bug | ✅ 已解决 | git pull 最新代码 |

---

## 九、资源

- **GitHub**：https://github.com/liangfuliang541-pixel/clawswarm
- **本地路径**：`clawswarm/`
- **Master API**：http://localhost:50010
- **Hub**：http://localhost:18080
- **Dashboard**：http://localhost:5000
- **ClawChat**：http://localhost:5002
