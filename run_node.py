import os, sys, time, json, uuid, subprocess, threading

# Force UTF-8 output for this launcher
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

BASE = r"D:\claw\swarm"

if len(sys.argv) < 2:
    print("Usage: python run_node.py <node_id> [capability1] ...")
    sys.exit(1)

node_id = sys.argv[1]
caps = sys.argv[2:] or ["general"]

# Launch node in background with UTF-8 encoding forced
proc = subprocess.Popen(
    [sys.executable, os.path.join(BASE, "swarm_node.py"), node_id] + caps,
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    cwd=BASE
)

print(f"Node [{node_id}] started as PID {proc.pid}")

# Wait for registration
time.sleep(6)

# Check agents directory
agents_dir = os.path.join(BASE, "agents")
agent_file = os.path.join(agents_dir, f"{node_id}.json")
if os.path.exists(agent_file):
    data = json.load(open(agent_file, encoding="utf-8"))
    print(f"Node registered: status={data.get('status')}, heartbeat={data.get('last_heartbeat','')[:19]}")
    print(f"Capabilities: {data.get('capabilities')}")
else:
    print("WARNING: Node did not register. Check queue/agents/ directory.")

print(f"Node is running. Tasks in queue will be picked up automatically.")
print(f"Monitor: python status_check.py")