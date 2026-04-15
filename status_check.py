import os, json
from paths import BASE_DIR, RESULTS_DIR, QUEUE_DIR, AGENTS_DIR

results = os.listdir(RESULTS_DIR)
queue = os.listdir(QUEUE_DIR)
agents = os.listdir(AGENTS_DIR)

print('=== results ===')
for f in results:
    fp = os.path.join(RESULTS_DIR, f)
    d = json.load(open(fp, encoding='utf-8'))
    print(f'  {f}: node={d.get("node")}, completed={d.get("completed_at","")[:19]}')

print()
print('=== queue ===')
for f in queue:
    fp = os.path.join(QUEUE_DIR, f)
    d = json.load(open(fp, encoding='utf-8'))
    print(f'  {f}: status={d.get("status")}')

print()
print('=== agents ===')
for f in agents:
    fp = os.path.join(AGENTS_DIR, f)
    d = json.load(open(fp, encoding='utf-8'))
    hb = d.get('last_heartbeat', '')
    print(f'  {f}: status={d.get("status")}, heartbeat={hb[:19]}')