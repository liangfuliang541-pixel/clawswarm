"""
测试 spawn_manager 的完整流程（不依赖 LLM）
"""
import json, time, sys
from pathlib import Path

# 添加 clawswarm 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))
from spawn_manager import (
    SPAWN_QUEUE_DIR, SPAWN_RESULTS_DIR,
    spawn_via_agent, complete_spawn, get_pending_spawns, check_spawn_results
)

def test_spawn_queue_flow():
    """测试文件队列的完整流程"""
    
    # 1. spawn_via_agent 写入队列
    spawn_id, meta = spawn_via_agent(
        task="echo queue test && whoami",
        task_id="test_queue_001",
        timeout=30,
        label="queue-test"
    )
    assert spawn_id == "test_queue_001"
    assert meta["status"] == "pending"
    print(f"OK spawn_via_agent wrote queue file: {spawn_id}")
    
    # 2. 检查队列文件存在
    queue_file = SPAWN_QUEUE_DIR / f"{spawn_id}.json"
    assert queue_file.exists(), f"Queue file not found: {queue_file}"
    print(f"OK Queue file exists: {queue_file}")
    
    # 3. 读取队列文件内容
    with open(queue_file, encoding="utf-8") as f:
        req = json.load(f)
    assert req["task"] == "echo queue test && whoami"
    assert req["label"] == "queue-test"
    assert req["timeout"] == 30
    print(f"OK Queue file content valid: {req['task'][:30]}")
    
    # 4. get_pending_spawns 返回队列中的请求
    pending = get_pending_spawns()
    assert any(p["spawn_id"] == spawn_id for p in pending)
    print(f"OK get_pending_spawns found {len(pending)} pending")
    
    # 5. spawn_via_agent 启动后台线程处理
    #    后台线程会调用 sessions HTTP API（可能失败但至少会调用 complete_spawn）
    time.sleep(3)  # 等待后台线程启动并调用 complete_spawn
    
    # 5. check_spawn_results 不阻塞（可能有结果也可能没有，取决于 Gateway 是否可达）
    results = check_spawn_results([spawn_id])
    # 如果后台线程写入了结果（Gateway可达），会包含 spawn_id
    # 如果后台线程失败（Gateway 不可达），结果可能还在队列中
    if spawn_id in results:
        print(f"OK check_spawn_results found background result: {results[spawn_id]['status']}")
    else:
        print(f"OK check_spawn_results (no result yet, worker may be retrying)")
    
    # 6. complete_spawn 写入结果文件（可覆盖后台线程的结果）
    complete_spawn(
        spawn_id,
        child_session_key="agent:test:sub:test-123",
        result="queue test output",
        status="success"
    )
    print(f"OK complete_spawn wrote result")
    
    # 7. check_spawn_results 可以检测到结果
    results = check_spawn_results([spawn_id])
    assert spawn_id in results
    assert results[spawn_id]["status"] == "success"
    assert results[spawn_id]["childSessionKey"] == "agent:test:sub:test-123"
    print(f"OK check_spawn_results found result: {results[spawn_id]['status']}")
    
    # 8. 队列文件被删除
    assert not queue_file.exists(), "Queue file should be deleted after complete_spawn"
    print(f"OK Queue file deleted after complete")
    
    # 9. ResultWatcher 可检测到的文件也写入了
    results_file = Path(__file__).parent.parent / "swarm_data" / "results" / f"r_{spawn_id}.json"
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            r = json.load(f)
        assert r["task_id"] == spawn_id
        assert r["status"] == "success"
        print(f"OK Results file for ResultWatcher exists: {results_file}")
    else:
        print(f"WARN Results file not found: {results_file}")
    
    # 10. 清理
    result_file = SPAWN_RESULTS_DIR / f"{spawn_id}.json"
    if result_file.exists():
        result_file.unlink()
    if results_file.exists():
        results_file.unlink()
    
    print("\nAll spawn_manager tests passed!")

if __name__ == "__main__":
    test_spawn_queue_flow()
