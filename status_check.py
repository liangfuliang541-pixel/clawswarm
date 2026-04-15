import os, json

BASE = r'D:\claw\swarm'

results = os.listdir(os.path.join(BASE, 'results'))
queue = os.listdir(os.path.join(BASE, 'queue'))
agents = os.listdir(os.path.join(BASE, 'agents'))

print('=== results ===')
for f in results:
    fp = os.path.join(BASE, 'results', f)
    d = json.load(open(fp, encoding='utf-8'))
    print(f'  {f}: node={d.get("node")}, completed={d.get("completed_at","")[:19]}')

print()
print('=== queue ===')
for f in queue:
    fp = os.path.join(BASE, 'queue', f)
    d = json.load(open(fp, encoding='utf-8'))
    print(f'  {f}: status={d.get("status")}')

print()
print('=== agents ===')
for f in agents:
    fp = os.path.join(BASE, 'agents', f)
    d = json.load(open(fp, encoding='utf-8'))
    hb = d.get('last_heartbeat', '')
    print(f'  {f}: status={d.get("status")}, heartbeat={hb[:19]}')