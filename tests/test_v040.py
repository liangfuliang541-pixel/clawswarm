"""
ClawSwarm v0.4.0 测试

测试新模块：roles / llm / memory / orchestrator LLM 能力
"""

import pytest, asyncio, time, json, os, sys

# ── roles.py 测试 ─────────────────────────────────────────────────────────

class TestRoles:
    def test_role_registry_init(self):
        from roles import RoleRegistry, DEFAULT_ROLES
        reg = RoleRegistry()
        assert len(reg.list_roles()) == len(DEFAULT_ROLES)
        assert "researcher" in reg.list_roles()
        assert "writer" in reg.list_roles()
        assert "coder" in reg.list_roles()

    def test_create_agent(self):
        from roles import get_registry
        reg = get_registry()
        agent = reg.create_agent("test_agent", "researcher", model="gpt-4o")
        assert agent.id == "test_agent"
        assert agent.role.name == "Researcher"
        assert agent.model == "gpt-4o"
        assert agent.memory_enabled == True
        assert "web_search" in agent.role.tools

    def test_research_team(self):
        from roles import get_registry
        reg = get_registry()
        team = reg.create_research_team(prefix="test_team")
        assert len(team) == 3
        assert {a.role.name for a in team} == {"Researcher", "Writer", "Reviewer"}

    def test_role_to_prompt(self):
        from roles import Role
        r = Role(
            name="Test",
            role="测试员",
            goal="测试目标",
            backstory="测试背景",
            tools=["tool1", "tool2"],
        )
        prompt = r.to_prompt()
        assert "测试员" in prompt
        assert "测试目标" in prompt
        assert "tool1, tool2" in prompt

    def test_agent_profile(self):
        from roles import get_registry
        reg = get_registry()
        agent = reg.create_agent("profile_test", "writer")
        profile = agent.to_dict()
        assert profile["id"] == "profile_test"
        assert "role_full" in profile
        assert profile["memory_enabled"] == True

    def test_role_serialization(self):
        from roles import Role
        r = Role(
            name="TestRole",
            role="测试",
            goal="目标",
            backstory="背景",
            tools=["t1"],
        )
        d = r.to_dict()
        r2 = Role.from_dict(d)
        assert r2.name == r.name
        assert r2.goal == r.goal


# ── llm.py 测试 ──────────────────────────────────────────────────────────

class TestLLM:
    def test_llm_providers_registered(self):
        from llm import _PROVIDERS
        assert "openai" in _PROVIDERS
        assert "anthropic" in _PROVIDERS
        assert "ollama" in _PROVIDERS
        assert "gemini" in _PROVIDERS

    def test_tool_map(self):
        from llm import TOOL_MAP
        assert "web_search" in TOOL_MAP
        assert "web_fetch" in TOOL_MAP
        assert "code_execute" in TOOL_MAP
        assert "file_read" in TOOL_MAP
        assert "file_write" in TOOL_MAP

    def test_create_llm_client_unknown_provider(self):
        from llm import create_llm_client
        with pytest.raises(ValueError, match="Unknown provider"):
            create_llm_client("unknown", "model-x")

    def test_message_serialization(self):
        from llm import Message
        m = Message("user", "Hello world")
        d = m.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello world"

    def test_message_with_tool(self):
        from llm import Message
        m = Message("assistant", "", tool_calls=[{"id": "1", "function": {"name": "test"}}])
        d = m.to_dict()
        assert d["tool_calls"][0]["function"]["name"] == "test"

    def test_chat_response(self):
        from llm import ChatResponse
        r = ChatResponse(content="Hello", model="gpt-4o", usage={"total": 10})
        assert r.content == "Hello"
        assert r.error is None

    def test_llm_tools_definitions(self):
        from llm import TOOL_WEB_SEARCH, TOOL_WEB_FETCH, TOOL_CODE_EXECUTE
        assert TOOL_WEB_SEARCH["function"]["name"] == "web_search"
        assert TOOL_WEB_FETCH["function"]["name"] == "web_fetch"
        assert TOOL_CODE_EXECUTE["function"]["name"] == "code_execute"


# ── memory.py 测试 ────────────────────────────────────────────────────────

class TestMemory:
    def test_short_term_memory_basic(self):
        from memory import ShortTermMemory
        m = ShortTermMemory(max_items=10)
        m.add_message("user", "Hello")
        m.add_message("assistant", "Hi there")
        assert len(m) == 2
        items = m.get_recent(1)
        assert items[-1].content == "Hi there"

    def test_short_term_memory_overflow(self):
        from memory import ShortTermMemory
        m = ShortTermMemory(max_items=3)
        for i in range(5):
            m.add_message("user", f"msg {i}")
        assert len(m) <= 3

    def test_short_term_memory_context(self):
        from memory import ShortTermMemory
        m = ShortTermMemory()
        m.add_message("user", "Hello")
        m.add_message("assistant", "Hi")
        ctx = m.get_context(n=2)
        assert "User" in ctx
        assert "Assistant" in ctx

    def test_working_memory_task(self):
        from memory import WorkingMemory
        w = WorkingMemory()
        ctx = w.start_task("t1", "测试任务", goal="完成测试")
        assert ctx.task_id == "t1"
        assert ctx.goal == "完成测试"
        assert w.get_current() is not None

    def test_working_memory_artifacts(self):
        from memory import WorkingMemory
        w = WorkingMemory()
        ctx = w.start_task("t1", "test")
        ctx.add_artifact("result", {"data": "test_value"})
        assert "result" in ctx.artifacts
        assert ctx.artifacts["result"]["value"]["data"] == "test_value"

    def test_memory_store(self):
        from memory import MemoryStore
        # 使用测试用的 agent ID，不创建真实文件
        m = MemoryStore("__test_agent__")
        m.short.add_message("user", "test")
        assert len(m.short) == 1

    def test_long_term_memory_search(self):
        from memory import LongTermMemory
        # 创建临时目录
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            m = LongTermMemory("__test_ltm__", base_dir=tmp)
            m.add("observation", "关键发现：增长30%")
            results = m.search("增长")
            assert len(results) > 0
            assert "30%" in results[0].content
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ── orchestrator LLM 能力测试 ─────────────────────────────────────────────

class TestOrchestrator:
    def test_orchestrator_init(self):
        from orchestrator import Orchestrator, HAS_LLM
        orc = Orchestrator(timeout=10)
        assert orc.timeout == 10
        assert orc.use_llm == True

    def test_rule_decompose_simple(self):
        from orchestrator import TaskDecomposer
        d = TaskDecomposer(use_llm=False)
        subs = d.decompose("搜索深圳天气并写一份报告")
        assert len(subs) == 2
        assert {s.type for s in subs} == {"fetch", "report"}

    def test_rule_decompose_single(self):
        from orchestrator import TaskDecomposer
        d = TaskDecomposer(use_llm=False)
        subs = d.decompose("分析这个数据")
        assert len(subs) == 1
        assert subs[0].type == "analyze"

    def test_classify_task(self):
        from orchestrator import classify_task
        assert classify_task("search X") == "fetch"
        assert classify_task("write report") == "report"
        assert classify_task("analyze data") == "analyze"
        assert classify_task("programming task") == "code"

    def test_result_aggregator_template(self):
        from orchestrator import ResultAggregator, SubTask
        agg = ResultAggregator(use_llm=False)
        subs = [
            SubTask(id="s1", type="fetch", description="搜索", status="done",
                    result={"content": "搜索结果内容"}),
        ]
        result = agg.aggregate(subs)
        assert "搜索" in result

    def test_watchdog_watcher(self):
        from orchestrator import ResultWatcher
        w = ResultWatcher()
        w.start()
        assert w is not None
        w.stop()

    def test_has_llm_flag(self):
        from orchestrator import HAS_LLM
        # HAS_LLM 取决于 llm 模块是否可导入
        assert isinstance(HAS_LLM, bool)
