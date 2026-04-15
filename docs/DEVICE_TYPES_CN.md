# ClawSwarm 设备类型与异构龙虾群

[English](DEVICE_TYPES.md) | 中文版

> "龙虾群最强之处，在于多样性。"

---

## 🏭 设备分类

```
ClawSwarm 集群 (异构龙虾群)
│
├── 🖥️ 桌面节点
│   ├── 操作系统: Windows, macOS, Linux
│   ├── 能力: code, search, write, analyze, exec
│   ├── 资源: 8+ 核心, 16GB+ 内存
│   └── 运行时间: 桌面时段 (8-24点)
│
├── 📱 移动节点
│   ├── 操作系统: iOS, Android (通过 OpenClaw 伴侣 App)
│   ├── 能力: 摄像头, GPS, 麦克风, 传感器
│   ├── 资源: 移动 ARM, 4-8GB 内存
│   └── 运行时间: 按需 (非持续在线)
│
├── 🍓 边缘节点
│   ├── 操作系统: Linux (树莓派, Jetson Nano 等)
│   ├── 能力: GPIO, I2C, 串口, 传感器
│   ├── 资源: 1-4 核心, 1-8GB 内存
│   └── 运行时间: 常驻 (7×24)
│
└── ☁️ 云节点
    ├── 操作系统: Linux (VPS, 容器)
    ├── 能力: 网络, 存储, 计算
    ├── 资源: 可扩展
    └── 运行时间: 常驻 (7×24)
```

---

## 🎯 能力矩阵

| 能力 | 桌面 | 移动 | 边缘 | 云 |
|------|------|------|------|-----|
| **code** | ✅ 完整 | ⚠️ 有限 | ❌ | ✅ 完整 |
| **search** | ✅ | ✅ | ❌ | ✅ |
| **write** | ✅ | ⚠️ 短文本 | ❌ | ✅ |
| **exec** | ✅ | ⚠️ 受限 | ⚠️ gpio | ✅ |
| **camera** | ⚠️ 外接 | ✅ 原生 | ⚠️ USB | ❌ |
| **gps** | ❌ | ✅ 原生 | ⚠️ GPS模块 | ❌ |
| **microphone** | ⚠️ 外接 | ✅ 原生 | ⚠️ USB | ❌ |
| **gpio** | ❌ | ❌ | ✅ 原生 | ❌ |
| **sensors** | ❌ | ✅ | ✅ | ❌ |
| **always_on** | ❌ | ❌ | ✅ | ✅ |

---

## 📡 通信模式

### 1. 直连 (同一网络)

```
Master ──────── WebSocket ──────── Node
(本地局域网)   (持久连接)        (桌面/树莓派)
```

### 2. 云中继 (远程)

```
Master ──HTTPS──► 云中继 ──WebSocket──► Node
                 (服务器)        (持久连接)  (任意位置)
```

### 3. 消息队列 (异步)

```
Master ──► 队列 ──► Node
          (文件)    (轮询)
```

---

## 📱 移动节点 (OpenClaw 伴侣)

### iOS/Android App

OpenClaw 伴侣应用运行在移动设备上：

```swift
// iOS - OpenClaw 伴侣
class MobileAgent {
    // 常驻后台 Agent
    // 能力:
    // - 摄像头拍照
    // - 定位服务
    // - 麦克风录音
    // - 传感器数据 (加速度计等)
    // - 推送通知
}
```

### 使用场景

| 场景 | 设备 | 任务 |
|------|------|------|
| 📸 拍摄白板照片 | 移动 | 拍照 → 发送给桌面 OCR |
| 🌍 获取位置上下文 | 移动 | 获取 GPS → 发送给云分析 |
| 🎤 语音笔记 | 移动 | 录音 → 云端转写 |
| 🏠 家居自动化 | 边缘(Pi) | 控制灯光、读取传感器 |
| 📊 日报生成 | 桌面 | 汇总所有数据生成报告 |

---

## 🍓 边缘节点 (树莓派)

### 安装

```bash
# 在树莓派上
pip install clawswarm
clawswarm-node --device-type edge --capabilities gpio,i2c,serial
```

### GPIO 任务

```json
{
  "task_id": "t_abc123",
  "type": "iot_control",
  "payload": {
    "action": "turn_on",
    "pin": 17,
    "device": "led_strip"
  }
}
```

---

## ☁️ 云节点

### 使用场景

| 场景 | 为什么用云 |
|------|------------|
| 7×24 监控 | 常驻，无需本地机器 |
| 重计算 | 可扩展 CPU 并行处理 |
| 网络任务 | Webhook、API 调用 |
| 数据聚合 | 收集所有节点结果 |

---

## 🧠 智能任务路由

调度器根据设备能力路由任务：

```python
class SmartRouter:
    """将任务路由到最优设备"""
    
    def route(self, task):
        required_caps = task.required_capabilities()
        available = self.find_nodes_with_capabilities(required_caps)
        
        # 选择最佳匹配
        if task.urgency == "high":
            return self.lowest_latency(available)
        elif task.complexity == "high":
            return self.most_powerful(available)
        else:
            return self.balanced(available)
```

---

## 🔄 离线/在线处理

### 移动节点

```
移动设备离线 ──► 任务暂停 ──► 移动设备恢复 ──► 恢复任务
               (in_progress)        ✓                  ✓
```

### 边缘节点

```
边缘常驻 ──► 可靠
          (建议关键任务用它)
```

---

## 📋 配置示例

### 桌面节点

```json
{
  "node_id": "desktop_alpha",
  "device_type": "desktop",
  "os": "windows",
  "capabilities": ["code", "search", "write", "analyze", "exec"],
  "resources": {"cpu_cores": 8, "ram_gb": 32},
  "preferences": {
    "max_concurrent_tasks": 3,
    "working_hours": "09:00-22:00"
  }
}
```

### 移动节点

```json
{
  "node_id": "mobile_zhangsan",
  "device_type": "mobile",
  "os": "ios",
  "capabilities": ["camera", "gps", "microphone", "sensors"],
  "resources": {"cpu_cores": 6, "ram_gb": 6},
  "preferences": {
    "only_when_charging": false,
    "wifi_only": true,
    "background_mode": true
  }
}
```

### 边缘节点

```json
{
  "node_id": "pi_home",
  "device_type": "edge",
  "os": "linux",
  "capabilities": ["gpio", "i2c", "serial"],
  "hardware": {"model": "raspberry_pi_4", "gpio_pins": 40},
  "preferences": {
    "always_on": true,
    "max_concurrent_tasks": 1
  }
}
```

---

## 🚀 实现路线图

| 阶段 | 设备 | 特性 |
|------|------|------|
| **v0.1** | 仅桌面 | 基础队列、轮询 |
| **v0.2** | + 云 | WebSocket 中继 |
| **v0.3** | + 移动 | 摄像头、GPS 任务 |
| **v1.0** | + 边缘(Pi) | GPIO、传感器 |
| **v2.0** | 全部 | 自动路由、负载均衡 |

---

## 📝 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) - 系统架构
- [NODE-CONFIG.md](NODE-CONFIG.md) - 节点配置
- [SANDBOX.md](SANDBOX.md) - 隔离与安全
