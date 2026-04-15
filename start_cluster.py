import os, sys, time, json, subprocess

os.environ["PYTHONIOENCODING"] = "utf-8"
BASE = r"D:\claw\swarm"

nodes = [
    ("claw_alpha", "search", "write", "code"),
    ("claw_beta",  "read",   "write"),
    ("claw_gamma", "search", "analyze", "report"),
]

procs = {}
for node_id, *caps in nodes:
    print(f"Starting {node_id}...")
    p = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "swarm_node.py"), node_id] + caps,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=BASE
    )
    procs[node_id] = p
    print(f"  PID {p.pid}")

print(f"\nAll {len(nodes)} nodes started.")
time.sleep(8)

# Verify registration
agents_dir = os.path.join(BASE, "agents")
for node_id, *caps in nodes:
    af = os.path.join(agents_dir, f"{node_id}.json")
    if os.path.exists(af):
        d = json.load(open(af, encoding="utf-8"))
        print(f"OK {node_id}: status={d['status']}, hb={d['last_heartbeat'][11:19]}, caps={d['capabilities']}")
    else:
        print(f"MISSING {node_id}")

print("\nAll nodes ready. Use 'add_task.py' to queue tasks.")
print("Use 'status_check.py' to monitor.")