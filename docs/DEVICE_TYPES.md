# ClawSwarm Device Types & Heterogeneous Swarm

English | [中文](DEVICE_TYPES_CN.md)

> "A lobster swarm is most powerful when it includes diversities."

---

## 🏭 Device Taxonomy

```
ClawSwarm Cluster (异构龙虾群)
│
├── 🖥️ Desktop Node (桌面节点)
│   ├── OS: Windows, macOS, Linux
│   ├── Capabilities: code, search, write, analyze, exec
│   ├── Resources: 8+ cores, 16GB+ RAM
│   └── Uptime: Desktop hours (8-24)
│
├── 📱 Mobile Node (移动节点)
│   ├── OS: iOS, Android (via OpenClaw companion)
│   ├── Capabilities: camera, gps, microphone, sensors
│   ├── Resources: Mobile ARM, 4-8GB RAM
│   └── Uptime: Intermittent (on-demand)
│
├── 🍓 Edge Node (边缘节点)
│   ├── OS: Linux (Raspberry Pi, Jetson Nano, etc.)
│   ├── Capabilities: gpio, i2c, serial, sensors
│   ├── Resources: 1-4 cores, 1-8GB RAM
│   └── Uptime: Always-on (7×24)
│
└── ☁️ Cloud Node (云节点)
    ├── OS: Linux (VPS, container)
    ├── Capabilities: network, storage, compute
    ├── Resources: Scalable
    └── Uptime: Always-on (7×24)
```

---

## 🎯 Capability Matrix

| Capability | Desktop | Mobile | Edge | Cloud |
|------------|---------|--------|------|-------|
| **code** | ✅ Full | ⚠️ Limited | ❌ | ✅ Full |
| **search** | ✅ Full | ✅ | ❌ | ✅ Full |
| **write** | ✅ Full | ⚠️ Small | ❌ | ✅ Full |
| **exec** | ✅ Full | ⚠️ Restricted | ⚠️ gpio only | ✅ |
| **camera** | ⚠️ Webcam | ✅ Native | ⚠️ USB | ❌ |
| **gps** | ❌ | ✅ Native | ⚠️ GPS hat | ❌ |
| **microphone** | ⚠️ Mic | ✅ Native | ⚠️ USB | ❌ |
| **gpio** | ❌ | ❌ | ✅ Native | ❌ |
| **sensors** | ❌ | ✅ | ✅ | ❌ |
| **always_on** | ❌ | ❌ | ✅ | ✅ |

---

## 📡 Communication Patterns

### 1. Direct Connect (Same Network)

```
Master ──────── WebSocket ──────── Node
(local LAN)   (persistent)      (desktop/pi)
```

### 2. Cloud Relay (Remote)

```
Master ──HTTPS──► Cloud Relay ──WebSocket──► Node
                 (server)         (persistent)  (anywhere)
```

### 3. Message Queue (Async)

```
Master ──► Queue ──► Node
          (file)    (polls)
```

---

## 🔌 Device Discovery

```python
class DeviceRegistry:
    """Central registry for all swarm devices."""
    
    # Each device registers with its capabilities
    DEVICE_TYPES = {
        "desktop": {
            "os": ["windows", "macos", "linux"],
            "min_resources": {"cpu": 4, "ram_gb": 8},
            "typical_capabilities": ["code", "search", "write", "analyze"],
        },
        "mobile": {
            "os": ["ios", "android"],
            "min_resources": {"cpu": 2, "ram_gb": 2},
            "typical_capabilities": ["camera", "gps", "microphone"],
            "special": ["sensors", "push_notification"],
        },
        "edge": {
            "os": ["linux"],
            "min_resources": {"cpu": 1, "ram_gb": 1},
            "typical_capabilities": ["gpio", "i2c", "serial"],
            "special": ["always_on", "low_power"],
        },
        "cloud": {
            "os": ["linux"],
            "min_resources": {"cpu": 1, "ram_gb": 1},
            "typical_capabilities": ["network", "storage"],
            "special": ["scalable", "always_on"],
        }
    }
```

---

## 📱 Mobile Node (OpenClaw Companion)

### iOS/Android App

The OpenClaw companion app runs on mobile devices:

```swift
// iOS - OpenClaw Companion
class MobileAgent {
    // Always-on background agent
    // Capabilities:
    // - Camera capture
    // - Location services
    // - Microphone recording
    // - Sensor data (accelerometer, etc.)
    // - Push notifications
}
```

### Use Cases

| Scenario | Device | Task |
|----------|--------|------|
| 📸 Take photo of whiteboard | Mobile | Capture, then send to Desktop for OCR |
| 🌍 Check location context | Mobile | Get GPS, send to Cloud for analysis |
| 🎤 Voice note to task | Mobile | Record, transcribe via Cloud |
| 🏠 Home automation | Edge (Pi) | Control lights, read sensors |
| 📊 Daily report | Desktop | Aggregate all data, generate report |

---

## 🍓 Edge Node (Raspberry Pi)

### Setup

```bash
# On Raspberry Pi
pip install clawswarm
clawswarm-node --device-type edge --capabilities gpio,i2c,serial
```

### GPIO Tasks

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

## ☁️ Cloud Node

### Use Cases

| Scenario | Why Cloud |
|----------|-----------|
| 24/7 monitoring | Always-on, no local machine needed |
| Heavy compute | Scale up CPU cores for parallel processing |
| Network tasks | Webhooks, API calls |
| Data aggregation | Collect results from all nodes |

---

## 🧠 Smart Task Routing

The scheduler routes tasks based on device capabilities:

```python
class SmartRouter:
    """Route tasks to optimal device."""
    
    def route(self, task):
        required_caps = task.required_capabilities()
        available = self.find_nodes_with_capabilities(required_caps)
        
        # Select best fit
        if task.urgency == "high":
            return self.lowest_latency(available)
        elif task.complexity == "high":
            return self.most_powerful(available)
        else:
            return self.balanced(available)
```

---

## 🔄 Offline/Online Handling

### Mobile Nodes

```
Mobile goes offline ──► Task paused ──► Mobile comes back ──► Resume
                        (in_progress)          ✓                   ✓
```

### Edge Nodes

```
Edge is always-on ──► Reliable
                     (recommended for critical tasks)
```

---

## 📋 Configuration Examples

### Desktop Node

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

### Mobile Node

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

### Edge Node

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

## 🚀 Implementation Roadmap

| Phase | Devices | Features |
|-------|---------|----------|
| **v0.1** | Desktop only | Basic queue, polling |
| **v0.2** | + Cloud | WebSocket relay |
| **v0.3** | + Mobile | Camera, GPS tasks |
| **v1.0** | + Edge (Pi) | GPIO, sensors |
| **v2.0** | All | Auto-routing, load balancing |

---

## 📝 Related Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [NODE-CONFIG.md](NODE-CONFIG.md) - Node configuration
- [SANDBOX.md](SANDBOX.md) - Isolation & security
