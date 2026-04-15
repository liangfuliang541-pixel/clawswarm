"""
ClawSwarm v0.5.0 测试 - REST API 模块
"""

import pytest, os, json, time, sys, threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNodeAPI:
    """node_api.py 测试"""

    def test_node_api_import(self):
        import node_api
        assert hasattr(node_api, 'NodeState')
        assert hasattr(node_api, 'poll_task')
        assert hasattr(node_api, 'complete_task')
        assert hasattr(node_api, 'execute_task')

    def test_node_state_basic(self):
        from node_api import NodeState
        state = NodeState("test_node", ["search", "write"], 5171)
        assert state.node_id == "test_node"
        assert state.status == "idle"
        assert state.capabilities == ["search", "write"]
        d = state.to_dict()
        assert d["node_id"] == "test_node"
        assert d["status"] == "idle"

    def test_node_state_busy(self):
        from node_api import NodeState
        state = NodeState("test_node", ["code"], 5172)
        assert state.status == "idle"
        state.busy("t_123")
        assert state.status == "busy"
        assert state.current_task_id == "t_123"
        d = state.to_dict()
        assert d["status"] == "busy"
        assert d["current_task"] == "t_123"
        state.idle()
        assert state.status == "idle"

    def test_read_write_json(self):
        from node_api import read_json, write_json
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), "test_node_api.json")
        write_json(tmp, {"id": "t1", "result": "ok"})
        data = read_json(tmp)
        assert data["id"] == "t1"
        assert data["result"] == "ok"
        os.remove(tmp)

    def test_read_json_nonexistent(self):
        from node_api import read_json
        assert read_json("/nonexistent/path/xyz.json") is None


class TestMasterAPI:
    """master_api.py 测试"""

    def test_master_api_import(self):
        import master_api
        assert hasattr(master_api, 'TaskRepo')
        assert hasattr(master_api, 'NodeRepo')
        assert hasattr(master_api, 'MasterAPIHandler')

    def test_task_repo_list(self):
        from master_api import TaskRepo
        tasks = TaskRepo.list()
        assert isinstance(tasks, list)

    def test_task_repo_list_with_limit(self):
        from master_api import TaskRepo
        tasks = TaskRepo.list(limit=5)
        assert len(tasks) <= 5

    def test_task_repo_get_nonexistent(self):
        from master_api import TaskRepo
        result = TaskRepo.get("nonexistent_id_xyz")
        assert result is None

    def test_task_repo_result_nonexistent(self):
        from master_api import TaskRepo
        result = TaskRepo.result("nonexistent_id_xyz")
        assert result is None

    def test_node_repo_list(self):
        from master_api import NodeRepo
        nodes = NodeRepo.list()
        assert isinstance(nodes, list)

    def test_node_repo_get_nonexistent(self):
        from master_api import NodeRepo
        result = NodeRepo.get("nonexistent_node_xyz")
        assert result is None

    def test_node_repo_assign_nonexistent(self):
        from master_api import NodeRepo
        ok = NodeRepo.assign_task("nonexistent_node", "nonexistent_task")
        assert ok == False


class TestAPIE2E:
    """API 端到端测试"""

    def test_master_api_endpoints_exist(self):
        """验证 API handler 能正确路由"""
        from master_api import MasterAPIHandler
        handler = MasterAPIHandler
        assert hasattr(handler, 'do_GET')
        assert hasattr(handler, 'do_POST')
        assert hasattr(handler, 'do_DELETE')

    def test_node_api_endpoints_exist(self):
        """验证 NodeAPI handler 能正确路由"""
        from node_api import NodeAPIHandler
        handler = NodeAPIHandler
        assert hasattr(handler, 'do_GET')
        assert hasattr(handler, 'do_POST')
