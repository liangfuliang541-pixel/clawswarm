#!/usr/bin/env python3
"""ClawSwarm Orchestrate - One prompt commands the swarm

This is the CLI entry point for the lobster commander.
Usage: python orchestrate.py "search AI news and write a report"

This script handles:
1. Decompose: rule engine or LLM (OPENAI_API_KEY) breaks task into sub-tasks
2. Enqueue: each sub-task written to swarm_data/queue/
3. Spawn: prints sessions_spawn commands for AI to execute
4. Poll: waits for sub-tasks to complete
5. Aggregate: merges outputs into final report

The AI uses this as its "left hand" - handles file I/O and polling,
while the AI handles sessions_spawn calls.
"""

import json, os, re, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

QUEUE_DIR   = BASE_DIR / "swarm_data" / "queue"
RESULTS_DIR = BASE_DIR / "swarm_data" / "results"
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Fix stdout encoding for emoji on Windows GBK console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except:
    pass

# ── Task Decomposition ────────────────────────────────────────────────

DECOMPOSE_PROMPT = """You are a task planner. Decompose this into 2-5 parallel sub-tasks.
Output JSON only, no markdown:
[{"id":"step_1","type":"fetch|analyze|report|code|general","description":"...","depends_on":[]}]"""

TASK_TYPES = {
    "fetch":   ["search","scrape","fetch","web","url","search","scrape"],
    "analyze": ["analyze","compare","evaluate","analyse","analyze"],
    "report":  ["report","write","summarize","draft","write","report"],
    "code":    ["code","implement","function","function","code"],
}

def classify(text: str) -> str:
    text_lower = text.lower()
    for t, keywords in TASK_TYPES.items():
        for kw in keywords:
            if kw in text_lower:
                return t
    return "general"


def llm_decompose(task_desc: str) -> Optional[List[Dict]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": DECOMPOSE_PROMPT + "\n\nTask: " + task_desc}],
            temperature=0.3, max_tokens=2048)
        text = resp.choices[0].message.content.strip()
        text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        print(f"[warn] LLM decompose failed: {e}", file=sys.stderr)
        return None


def rule_decompose(task_desc: str) -> List[Dict]:
    # Split by common separators
    separators = re.compile(r'[,，;；\u3002\uff0c\uff1b]|(?:然后|接着|之后|并|并且|同时|and|also|, and|, then)')
    segments = [s.strip() for s in separators.split(task_desc) if s.strip()]
    if len(segments) <= 1:
        segments = [task_desc]

    subs = []
    for i, seg in enumerate(segments):
        subs.append({
            "id": f"sub_{i}",
            "type": classify(seg),
            "description": seg,
            "depends_on": [],
        })

    # report/analyze tasks depend on prior fetch tasks
    for i, sub in enumerate(subs):
        if sub["type"] in ("report", "analyze"):
            for j in range(i):
                if subs[j]["type"] == "fetch" and subs[j]["id"] not in sub["depends_on"]:
                    sub["depends_on"].append(subs[j]["id"])

    return subs


def decompose(task_desc: str) -> List[Dict]:
    print("[orchestrate] decomposing task...", file=sys.stderr)
    result = llm_decompose(task_desc)
    if result:
        print(f"[orchestrate] LLM: {len(result)} sub-tasks", file=sys.stderr)
        return result
    print("[orchestrate] falling back to rule engine", file=sys.stderr)
    return rule_decompose(task_desc)


# ── Task Enqueue ────────────────────────────────────────────────────

def submit(prompt: str, task_type: str = "general",
          label: str = None, priority: int = 5) -> tuple:
    ts = int(time.time() * 1000)
    task_id = f"task_{label or task_type}_{ts}"
    result_file = str(RESULTS_DIR / f"r_{task_id}.json")
    task = {
        "id": task_id,
        "type": task_type,
        "prompt": prompt,
        "priority": priority,
        "created_at": datetime.now().isoformat(),
    }
    with open(QUEUE_DIR / f"{task_id}.json", "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    return task_id, result_file


# ── Result Polling ──────────────────────────────────────────────────

def poll_result(result_file: str, timeout: int = 120) -> Optional[dict]:
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(result_file):
            try:
                with open(result_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        time.sleep(2)
    return None


def poll_all(result_files: Dict[str, str], timeout: int = 120) -> Dict[str, Optional[dict]]:
    results = {}
    pending = list(result_files.items())
    start = time.time()
    while pending and time.time() - start < timeout:
        for label, rf in pending[:]:
            if os.path.exists(rf):
                try:
                    with open(rf, encoding="utf-8") as f:
                        results[label] = json.load(f)
                    pending.remove((label, rf))
                except Exception:
                    pass
        if pending:
            time.sleep(2)
    for label, rf in pending:
        results[label] = {"status": "timeout"}
    return results


# ── Result Aggregation ───────────────────────────────────────────────

def aggregate(subs: List[Dict], results: Dict[str, Optional[dict]]) -> str:
    emoji = {"fetch": "S", "analyze": "A", "report": "R", "code": "C", "general": "G"}
    sections = []
    for s in subs:
        r = results.get(s["id"])
        out = r.get("output", r.get("result", "")) if r else ""
        if isinstance(out, dict):
            out = json.dumps(out, ensure_ascii=False, indent=2)
        elif not isinstance(out, str):
            out = str(out)
        if len(out) > 3000:
            out = out[:3000] + "\n... (truncated)"
        prefix = emoji.get(s["type"], "?")
        sections.append(f"[{prefix}] {s['description']}\n{out}")
    return "\n\n---\n\n".join(sections)


# ── Main Orchestration Loop ────────────────────────────────────────

def orchestrate(description: str, timeout: int = 300) -> Dict:
    start = time.time()

    print()
    print("=" * 60)
    print("ClawSwarm Orchestrate - One prompt commands the swarm")
    print(f"Task: {description[:80]}")
    print("=" * 60)

    # 1. Decompose
    subs = decompose(description)
    print(f"\n[#] {len(subs)} sub-tasks decomposed:")
    for s in subs:
        deps = f" (depends on {s['depends_on']})" if s["depends_on"] else ""
        print(f"   [{s['id']}] {s['type']:8s}{deps}  {s['description'][:50]}")

    # 2. Enqueue parallel tasks
    result_files: Dict[str, str] = {}
    spawn_hints: List[Dict] = []
    for s in subs:
        if not s.get("depends_on"):
            tid, rf = submit(s["description"], s.get("type", "general"), s["id"])
            result_files[s["id"]] = rf
            spawn_hints.append({
                "id": s["id"],
                "type": s.get("type", "general"),
                "result_file": rf,
                "spawn": f'sessions_spawn(message="Execute: {s["id"]}: {s["description"]}", result_file="{rf}", timeout={timeout})',
            })
            print(f"\n[Q] [{s['id']}] enqueued -> {tid}")
            print(f"    -> sessions_spawn(result_file=\"{rf}\")")

    # 3. Print summary for AI
    print(f"\n{'=' * 60}")
    print("AI INSTRUCTIONS - Execute these sessions_spawn calls:")
    print("=" * 60)
    for h in spawn_hints:
        print(f"\n# [{h['id']}] ({h['type']})")
        print(f"sessions_spawn(")
        print(f"    message=\"Execute task {h['id']}: write result to {h['result_file']}\",")
        print(f"    result_file=\"{h['result_file']}\",")
        print(f"    timeout={timeout})")

    # 4. Poll
    print(f"\n[~] Waiting for {len(result_files)} tasks (timeout={timeout}s)...")
    results = poll_all(result_files, timeout=timeout)

    # 5. Handle dependent tasks
    for s in subs:
        if s.get("depends_on"):
            deps_ok = all(
                results.get(d, {}).get("status") == "success"
                for d in s["depends_on"]
            )
            if deps_ok:
                dep_results = {d: results.get(d, {}).get("output", "") for d in s["depends_on"]}
                enhanced = f"{s['description']}\n\nPrior results:\n{json.dumps(dep_results, ensure_ascii=False)}"
                tid, rf = submit(enhanced, s.get("type", "general"), s["id"])
                print(f"\n[Q] [{s['id']}] deps met, enqueued")
                r = poll_result(rf, timeout=timeout)
                results[s["id"]] = r or {"status": "timeout"}

    # 6. Aggregate
    final_output = aggregate(subs, results)
    duration = time.time() - start
    success = all(r and r.get("status") == "success" for r in results.values())

    ok = sum(1 for r in results.values() if r and r.get("status") == "success")
    print(f"\n{'OK' if success else 'PARTIAL'} done in {duration:.1f}s ({ok}/{len(results)} sub-tasks)")

    return {
        "description": description,
        "sub_tasks": subs,
        "spawn_hints": spawn_hints,
        "results": results,
        "final_output": final_output,
        "duration": duration,
        "success": success,
    }


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("ClawSwarm Orchestrate - One prompt commands the swarm")
        print()
        print("Usage:")
        print("  python orchestrate.py \"search AI news and write a report\"")
        print("  python orchestrate.py \"compare Claude vs GPT agents\"")
        print()
        print("Environment:")
        print("  OPENAI_API_KEY - set for LLM-driven task decomposition")
        print("                - unset for rule-engine fallback")
        print()
        print("Output: structured sub-tasks + sessions_spawn hints for AI")
        sys.exit(1)

    description = " ".join(sys.argv[1:])

    if not os.environ.get("OPENAI_API_KEY"):
        print("[info] OPENAI_API_KEY not set - using rule engine", file=sys.stderr)

    result = orchestrate(description, timeout=300)

    print()
    print("=" * 60)
    print("FINAL OUTPUT")
    print("=" * 60)
    print(result["final_output"])

    out_file = RESULTS_DIR / f"orchestrate_{int(time.time())}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nFull result saved: {out_file}")


if __name__ == "__main__":
    main()
