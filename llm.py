"""
ClawSwarm - LLM 抽象层

支持多种 LLM Provider：
- OpenAI (GPT-4o, GPT-4o-mini)
- Anthropic (Claude 3.5 Sonnet, Haiku)
- Gemini (gemini-2.0-flash, gemini-pro)
- Azure OpenAI
- Ollama (本地模型)
- OpenAI-Compatible (智谱/DeepSeek/硅基流动等)

核心类:
    LLMClient    — 统一接口
    OpenAIProvider / AnthropicProvider / GeminiProvider / OllamaProvider
    Message      — 对话消息
    ChatResponse — 响应结果
"""

import os, json, time, asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Literal, Union
from abc import ABC, abstractmethod
from datetime import datetime

# ── 消息模型 ──────────────────────────────────────────────────────────────

@dataclass
class Message:
    """对话消息"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None          # tool caller name
    tool_call_id: Optional[str] = None    # for tool results
    tool_calls: Optional[List[dict]] = None  # for assistant tool calls

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.name: d["name"] = self.name
        if self.tool_call_id: d["tool_call_id"] = self.tool_call_id
        if self.tool_calls: d["tool_calls"] = self.tool_calls
        return d


@dataclass
class ChatResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)   # prompt_tokens, completion_tokens, total
    finish_reason: str = "stop"
    raw: Optional[dict] = None          # 原始响应
    tool_calls: Optional[List[dict]] = None
    error: Optional[str] = None


# ── Provider 抽象 ──────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """LLM Provider 基类"""

    name: str = "base"

    def __init__(self, model: str, api_key: str = None,
                 base_url: str = None, timeout: float = 60.0, **kwargs):
        self.model = model
        self.api_key = api_key or os.environ.get(f"{self.name.upper()}_API_KEY")
        self.base_url = base_url
        self.timeout = timeout
        self.extra = kwargs

    @abstractmethod
    async def chat(self, messages: List[Message],
                   temperature: float = 0.5,
                   max_tokens: int = 4096,
                   tools: List[dict] = None,
                   **kwargs) -> ChatResponse:
        """发送对话请求"""
        raise NotImplementedError

    @abstractmethod
    def chat_sync(self, messages: List[Message],
                  temperature: float = 0.5,
                  max_tokens: int = 4096,
                  tools: List[dict] = None,
                  **kwargs) -> ChatResponse:
        """同步版本"""
        raise NotImplementedError

    def _usage_from_response(self, response: dict) -> Dict[str, int]:
        """从响应中提取 usage"""
        usage = response.get("usage", {})
        return {
            "prompt_tokens":     usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total":            usage.get("total_tokens", 0),
        }


# ── OpenAI Provider ─────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """OpenAI GPT 系列"""

    name = "openai"

    async def chat(self, messages: List[Message],
                   temperature: float = 0.5,
                   max_tokens: int = 4096,
                   tools: List[dict] = None,
                   **kwargs) -> ChatResponse:
        import aiohttp

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model":    self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        body.update(kwargs)

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body, headers=headers) as r:
                    data = await r.json()
                    if r.status != 200:
                        return ChatResponse(
                            content="", model=self.model,
                            error=f"HTTP {r.status}: {data.get('error', {}).get('message', data)}",
                        )

                    choice = data["choices"][0]
                    msg = choice["message"]
                    return ChatResponse(
                        content=msg.get("content", ""),
                        model=data.get("model", self.model),
                        usage=self._usage_from_response(data),
                        finish_reason=choice.get("finish_reason", "stop"),
                        tool_calls=msg.get("tool_calls"),
                        raw=data,
                    )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))

    def chat_sync(self, messages: List[Message],
                  temperature: float = 0.5,
                  max_tokens: int = 4096,
                  tools: List[dict] = None,
                  **kwargs) -> ChatResponse:
        import requests

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model":    self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        body.update(kwargs)

        try:
            r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            data = r.json()
            if r.status_code != 200:
                return ChatResponse(
                    content="", model=self.model,
                    error=f"HTTP {r.status_code}: {data.get('error', {}).get('message', data)}",
                )

            choice = data["choices"][0]
            msg = choice["message"]
            return ChatResponse(
                content=msg.get("content", ""),
                model=data.get("model", self.model),
                usage=self._usage_from_response(data),
                finish_reason=choice.get("finish_reason", "stop"),
                tool_calls=msg.get("tool_calls"),
                raw=data,
            )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))


# ── Anthropic Provider ──────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    """Anthropic Claude 系列"""

    name = "anthropic"

    def __init__(self, model: str, api_key: str = None,
                 base_url: str = None, timeout: float = 60.0, **kwargs):
        super().__init__(model, api_key, base_url, timeout, **kwargs)
        self.base_url = base_url or "https://api.anthropic.com"

    async def chat(self, messages: List[Message],
                   temperature: float = 0.5,
                   max_tokens: int = 4096,
                   tools: List[dict] = None,
                   **kwargs) -> ChatResponse:
        import aiohttp

        url = f"{self.base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true",
        }

        # 将 messages 转换为 Anthropic 格式
        system_msg = ""
        anthropic_msgs = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            elif m.role == "user":
                anthropic_msgs.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                anthropic_msgs.append({"role": "assistant", "content": m.content})

        body = {
            "model":    self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            body["system"] = system_msg
        if tools:
            body["tools"] = tools

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body, headers=headers) as r:
                    data = await r.json()
                    if r.status != 200:
                        return ChatResponse(
                            content="", model=self.model,
                            error=f"HTTP {r.status}: {data.get('error', {}).get('message', data)}",
                        )
                    return ChatResponse(
                        content=data.get("content", [{}])[0].get("text", ""),
                        model=self.model,
                        usage={
                            "prompt_tokens":     data.get("usage", {}).get("input_tokens", 0),
                            "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                            "total":            data.get("usage", {}).get("input_tokens", 0) +
                                               data.get("usage", {}).get("output_tokens", 0),
                        },
                        finish_reason=data.get("stop_reason", "stop"),
                        raw=data,
                    )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))

    def chat_sync(self, messages: List[Message],
                  temperature: float = 0.5,
                  max_tokens: int = 4096,
                  tools: List[dict] = None,
                  **kwargs) -> ChatResponse:
        import requests

        url = f"{self.base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        system_msg = ""
        anthropic_msgs = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            elif m.role == "user":
                anthropic_msgs.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                anthropic_msgs.append({"role": "assistant", "content": m.content})

        body = {
            "model":    self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            body["system"] = system_msg
        if tools:
            body["tools"] = tools

        try:
            r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            data = r.json()
            if r.status_code != 200:
                return ChatResponse(
                    content="", model=self.model,
                    error=f"HTTP {r.status_code}: {data.get('error', {}).get('message', data)}",
                )
            return ChatResponse(
                content=data.get("content", [{}])[0].get("text", ""),
                model=self.model,
                usage={
                    "prompt_tokens":     data.get("usage", {}).get("input_tokens", 0),
                    "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                    "total":            data.get("usage", {}).get("input_tokens", 0) +
                                       data.get("usage", {}).get("output_tokens", 0),
                },
                finish_reason=data.get("stop_reason", "stop"),
                raw=data,
            )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))


# ── Ollama Provider (本地模型) ─────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    """Ollama 本地 LLM"""

    name = "ollama"

    def __init__(self, model: str, api_key: str = None,
                 base_url: str = None, timeout: float = 120.0, **kwargs):
        super().__init__(model, api_key, base_url, timeout, **kwargs)
        self.base_url = base_url or "http://localhost:11434"

    async def chat(self, messages: List[Message],
                   temperature: float = 0.5,
                   max_tokens: int = 4096,
                   tools: List[dict] = None,
                   **kwargs) -> ChatResponse:
        return self.chat_sync(messages, temperature, max_tokens, tools, **kwargs)

    def chat_sync(self, messages: List[Message],
                  temperature: float = 0.5,
                  max_tokens: int = 4096,
                  tools: List[dict] = None,
                  **kwargs) -> ChatResponse:
        import requests

        url = f"{self.base_url}/api/chat"
        ollama_msgs = [{"role": m.role, "content": m.content} for m in messages]
        body = {
            "model":    self.model,
            "messages": ollama_msgs,
            "stream":   False,
            "options":  {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            body["tools"] = tools

        try:
            r = requests.post(url, json=body, timeout=self.timeout)
            data = r.json()
            msg = data.get("message", {})
            return ChatResponse(
                content=msg.get("content", ""),
                model=self.model,
                usage={"total": data.get("eval_count", 0)},
                raw=data,
            )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))


# ── Gemini Provider ─────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    """Google Gemini"""

    name = "gemini"

    def __init__(self, model: str, api_key: str = None,
                 base_url: str = None, timeout: float = 60.0, **kwargs):
        super().__init__(model, api_key, base_url, timeout, **kwargs)
        self.base_url = base_url or "https://generativelanguage.googleapis.com"

    async def chat(self, messages: List[Message],
                   temperature: float = 0.5,
                   max_tokens: int = 4096,
                   tools: List[dict] = None,
                   **kwargs) -> ChatResponse:
        return self.chat_sync(messages, temperature, max_tokens, tools, **kwargs)

    def chat_sync(self, messages: List[Message],
                  temperature: float = 0.5,
                  max_tokens: int = 4096,
                  tools: List[dict] = None,
                  **kwargs) -> ChatResponse:
        import requests

        api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent?key={api_key}"

        # 构建 contents
        contents = []
        for m in messages:
            if m.role == "system":
                # Gemini 用 systemInstruction
                continue
            contents.append({"role": "model" if m.role == "assistant" else "user",
                             "parts": [{"text": m.content}]})

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if tools:
            body["tools"] = tools

        try:
            r = requests.post(url, json=body, timeout=self.timeout)
            data = r.json()
            if r.status_code != 200:
                return ChatResponse(
                    content="", model=self.model,
                    error=f"HTTP {r.status_code}: {data}",
                )
            text = ""
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    text += part.get("text", "")
            return ChatResponse(
                content=text,
                model=self.model,
                usage={"total": data.get("usageMetadata", {}).get("totalTokenCount", 0)},
                raw=data,
            )
        except Exception as e:
            return ChatResponse(content="", model=self.model, error=str(e))


# ── 统一客户端 ──────────────────────────────────────────────────────────────

# Provider 注册表
_PROVIDERS = {
    "openai":    OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini":    GeminiProvider,
    "ollama":    OllamaProvider,
}

# 默认 base_url
_DEFAULT_BASE_URLS = {
    "openai":    "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini":    "https://generativelanguage.googleapis.com",
    "ollama":    "http://localhost:11434",
}


def create_llm_client(
    provider: str,
    model: str,
    api_key: str = None,
    base_url: str = None,
    **kwargs,
) -> LLMProvider:
    """
    工厂函数：创建 LLM 客户端

    用法:
        client = create_llm_client("openai", "gpt-4o", api_key="sk-...")
        resp = client.chat_sync([Message("user", "Hello!")])
        print(resp.content)
    """
    cls = _PROVIDERS.get(provider.lower())
    if not cls:
        raise ValueError(
            f"Unknown provider: {provider}. Available: {list(_PROVIDERS.keys())}"
        )

    # 从环境变量获取 API key
    if not api_key:
        env_key = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(env_key)

    # 从配置获取 base_url
    if not base_url:
        base_url = os.environ.get(f"{provider.upper()}_BASE_URL")

    return cls(
        model=model,
        api_key=api_key,
        base_url=base_url or _DEFAULT_BASE_URLS.get(provider.lower()),
        **kwargs,
    )


def chat(
    messages: List[Message],
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 0.5,
    max_tokens: int = 4096,
    api_key: str = None,
    base_url: str = None,
    tools: List[dict] = None,
    **kwargs,
) -> ChatResponse:
    """快捷函数：单次对话请求"""
    client = create_llm_client(provider, model, api_key, base_url)
    return client.chat_sync(messages, temperature, max_tokens, tools, **kwargs)


# ── 预置工具定义 ───────────────────────────────────────────────────────────

TOOL_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}

TOOL_WEB_FETCH = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetch content from a URL",
        "parameters": {
            "type": "object",
            "properties": {
                "url":    {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return", "default": 10000},
            },
            "required": ["url"],
        },
    },
}

TOOL_CODE_EXECUTE = {
    "type": "function",
    "function": {
        "name": "code_execute",
        "description": "Execute Python code and return output",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "language": {"type": "string", "description": "Language (python/js/bash)", "default": "python"},
            },
            "required": ["code"],
        },
    },
}

TOOL_FILE_READ = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": "Read a file from the filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
    },
}

TOOL_FILE_WRITE = {
    "type": "function",
    "function": {
        "name": "file_write",
        "description": "Write content to a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
}

TOOL_MAP = {
    "web_search":    TOOL_WEB_SEARCH,
    "web_fetch":     TOOL_WEB_FETCH,
    "code_execute":  TOOL_CODE_EXECUTE,
    "file_read":     TOOL_FILE_READ,
    "file_write":    TOOL_FILE_WRITE,
}


# ── CLI 入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="ClawSwarm LLM Client")
    parser.add_argument("--provider", "-p", default="openai",
                        choices=list(_PROVIDERS.keys()))
    parser.add_argument("--model", "-m", default="gpt-4o-mini")
    parser.add_argument("--system", "-s", default="You are a helpful assistant.")
    parser.add_argument("--temperature", "-t", type=float, default=0.5)
    parser.add_argument("prompt", nargs="?", default="Say hello in 10 words.")

    args = parser.parse_args(sys.argv[1:])

    messages = [Message("system", args.system), Message("user", args.prompt)]
    resp = chat(
        messages,
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
    )

    if resp.error:
        print(f"❌ Error: {resp.error}")
    else:
        print(f"✅ {resp.model} ({resp.usage})")
        print(resp.content)
