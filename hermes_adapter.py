# hermes_adapter.py - Hermes ACP Protocol Adapter for ClawSwarm
#
# Launches Hermes in ACP (Agent Communication Protocol) mode as a subprocess.
# Communicates via stdin/stdout using JSON-RPC 2.0.
#
# Protocol flow:
#   1. Start: `hermes acp`
#   2. Wait for `//ready` on stdout
#   3. Send: initialize (JSON-RPC)
#   4. Send: authenticate (JSON-RPC)
#   5. For each task: session/new or session/prompt (JSON-RPC)
#   6. Read response: result or stream of content blocks
#
# Ref: https://github.com/nousresearch/hermes

import asyncio
import json
import os
import sys
import time
import subprocess
import threading
from typing import Any, Dict, List, Optional, AsyncIterator

from agent_adapter import AgentAdapter, register_adapter


@register_adapter("hermes")
class HermesAdapter(AgentAdapter):
    """Adapter for Hermes Agent via ACP (stdin/stdout JSON-RPC 2.0)."""

    ADAPTER_TYPE = "hermes"

    # -- Config keys --
    CFG_HERMES_BIN = "hermes_bin"           # path to hermes binary
    CFG_MODEL = "model"                     # model name
    CFG_SYSTEM_PROMPT = "system_prompt"     # optional system prompt
    CFG_MAX_TOKENS = "max_tokens"           # max output tokens
    CFG_TIMEOUT = "timeout"                 # per-task timeout (seconds)
    CFG_EXTRA_ARGS = "extra_args"           # additional CLI args

    def __init__(self, agent_id: str, config: dict = None):
        super().__init__(agent_id, config)
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._next_id = 1
        self._initialized = False
        self._session_id: Optional[str] = None
        self._ready_event = threading.Event()
        self._stderr_lines: List[str] = []

    # -- Lifecycle --

    def start(self) -> bool:
        hermes_bin = self.config.get(self.CFG_HERMES_BIN, "hermes")
        if not self._find_hermes(hermes_bin):
            return False

        cmd = [hermes_bin, "acp"]
        extra = self.config.get(self.CFG_EXTRA_ARGS, [])
        if isinstance(extra, list):
            cmd.extend(extra)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,        # line-buffered
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return False
        except Exception as e:
            self._stderr_lines.append(f"Launch failed: {e}")
            return False

        # Start background reader thread
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

        # Wait for //ready (up to 30s)
        if not self._ready_event.wait(timeout=30):
            self.stop()
            return False

        # Run initialize + authenticate
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._handshake())
            self._initialized = True
        finally:
            loop.close()

        self._running = True
        self._started_at = time.time()
        return True

    def stop(self) -> None:
        self._running = False
        if self._process:
            try:
                self._process.stdin.write('{"jsonrpc":"2.0","method":"shutdown","id":' + str(self._next_id) + '}\n')
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except Exception:
                pass
            try:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        self._initialized = False
        self._session_id = None

    # -- Task execution --

    async def execute(self, task: dict) -> dict:
        if not self._running or not self._initialized:
            return self._make_result(
                task.get("id", "unknown"), "failed",
                error="Hermes adapter not running"
            )

        task_id = task.get("id", "unknown")
        prompt = task.get("prompt", task.get("description", ""))
        timeout = self.config.get(self.CFG_TIMEOUT, task.get("timeout_seconds", 300))

        if not prompt:
            return self._make_result(task_id, "failed", error="No prompt provided")

        try:
            result = await asyncio.wait_for(
                self._send_task(task_id, prompt),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            return self._make_result(
                task_id, "timeout",
                error=f"Hermes task timed out after {timeout}s"
            )
        except Exception as e:
            return self._make_result(
                task_id, "failed",
                error=f"Hermes execution error: {type(e).__name__}: {e}"
            )

    # -- Health check --

    def health_check(self) -> dict:
        proc_alive = self._process is not None and self._process.poll() is None
        uptime = time.time() - self._started_at if self._started_at else 0
        return {
            "healthy": proc_alive and self._initialized,
            "agent_id": self.agent_id,
            "adapter_type": self.ADAPTER_TYPE,
            "uptime": uptime,
            "tasks_completed": self._task_count,
            "errors": self._error_count,
            "session_id": self._session_id,
            "initialized": self._initialized,
            "details": {
                "hermes_bin": self.config.get(self.CFG_HERMES_BIN, "hermes"),
                "model": self.config.get(self.CFG_MODEL, "default"),
                "stderr_tail": self._stderr_lines[-5:],
            },
        }

    # -- Capabilities --

    @property
    def capabilities(self) -> List[str]:
        caps = self.config.get("capabilities", [])
        if not caps:
            caps = ["general", "research", "code", "write", "analyze"]
        return caps

    # -- Internal: Hermes binary discovery --

    def _find_hermes(self, hermes_bin: str) -> bool:
        """Check if hermes binary is available."""
        from shutil import which
        if os.path.isabs(hermes_bin):
            return os.path.isfile(hermes_bin)
        found = which(hermes_bin)
        if found:
            self.config[self.CFG_HERMES_BIN] = found
            return True
        self._stderr_lines.append(f"hermes binary not found: {hermes_bin}")
        return False

    # -- Internal: Reader loop (background thread) --

    def _reader_loop(self):
        """Read stdout line by line, dispatch JSON-RPC responses."""
        if not self._process or not self._process.stdout:
            return
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue

            # //ready signal
            if line == "//ready":
                self._ready_event.set()
                continue

            # Try JSON parse
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._stderr_lines.append(f"Non-JSON stdout: {line[:200]}")
                continue

            # Handle as JSON-RPC response or notification
            self._handle_message(msg)

    def _handle_message(self, msg: dict):
        """Dispatch incoming JSON-RPC message."""
        req_id = msg.get("id")
        method = msg.get("method")
        result = msg.get("result")
        error = msg.get("error")

        # Store session ID if present
        if isinstance(result, dict) and "sessionId" in result:
            self._session_id = result["sessionId"]

        # Resolve pending future if we have a matching request ID
        if req_id is not None:
            future = self._pending_requests.get(str(req_id))
            if future and not future.done():
                if error:
                    future.set_exception(Exception(json.dumps(error)))
                else:
                    future.set_result(result)
                self._pending_requests.pop(str(req_id), None)

    # -- Internal: Send JSON-RPC request --

    def _send_jsonrpc(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request and wait for response (blocking)."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Hermes process not running")

        request_id = self._next_id
        self._next_id += 1

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
        }
        if params:
            message["params"] = params

        # Create future for response
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        self._pending_requests[str(request_id)] = future

        # Write to stdin
        with self._write_lock:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()

        # Wait for response
        try:
            result = loop.run_until_complete(
                asyncio.wait_for(future, timeout=30)
            )
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(str(request_id), None)
            raise TimeoutError(f"JSON-RPC request timed out: {method}")
        finally:
            loop.close()

    # -- Internal: ACP handshake --

    async def _handshake(self):
        """Initialize + authenticate with Hermes ACP."""
        # Initialize
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "ClawSwarm",
                "version": "0.10.0",
            },
        }
        self._send_jsonrpc("initialize", init_params)

        # Notify initialized
        self._send_notification("notifications/initialized")

        # Authenticate (optional - some Hermes builds may not require it)
        token = self.config.get("auth_token")
        if token:
            self._send_jsonrpc("authenticate", {"token": token})

    def _send_notification(self, method: str, params: dict = None):
        """Send a JSON-RPC notification (no id, no response expected)."""
        if not self._process or not self._process.stdin:
            return
        message = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        with self._write_lock:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()

    # -- Internal: Execute task via ACP --

    async def _send_task(self, task_id: str, prompt: str) -> dict:
        """Send a task to Hermes via session/prompt."""
        # Reuse session if available, otherwise create new
        if not self._session_id:
            # Create a new session
            session_params = {
                "model": self.config.get(self.CFG_MODEL, ""),
            }
            sys_prompt = self.config.get(self.CFG_SYSTEM_PROMPT)
            if sys_prompt:
                session_params["systemPrompt"] = sys_prompt

            self._send_jsonrpc("session/new", session_params)

        if not self._session_id:
            return self._make_result(task_id, "failed",
                                     error="Failed to create Hermes session")

        # Send the actual prompt
        prompt_params = {
            "sessionId": self._session_id,
            "content": prompt,
        }
        max_tokens = self.config.get(self.CFG_MAX_TOKENS)
        if max_tokens:
            prompt_params["maxTokens"] = max_tokens

        result = self._send_jsonrpc("session/prompt", prompt_params)

        # Extract text from Hermes response
        output_text = self._extract_output(result)

        return self._make_result(
            task_id, "done",
            output=output_text,
            extra={"hermes_session": self._session_id}
        )

    # -- Internal: Extract output from Hermes response --

    @staticmethod
    def _extract_output(result) -> str:
        """Extract text output from Hermes ACP response."""
        if not result:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            # Hermes returns content blocks array
            content = result.get("content", [])
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "result":
                            text = block.get("text", "")
                            if text:
                                parts.append(text)
                return "\n".join(parts)
            return json.dumps(result, ensure_ascii=False)
        return str(result)


# -- CLI test --

if __name__ == "__main__":
    print("HermesAdapter - ACP Protocol Adapter")
    print("=" * 50)

    adapter = HermesAdapter("test-hermes", config={
        "hermes_bin": "hermes",
        "model": "default",
    })

    print(f"Capabilities: {adapter.capabilities}")

    # Check if hermes is available
    from shutil import which
    if not which("hermes"):
        print("[SKIP] hermes binary not found, skipping live test")
        sys.exit(0)

    print("[START] Launching Hermes ACP...")
    ok = adapter.start()
    print(f"  Started: {ok}")

    if ok:
        health = adapter.health_check()
        print(f"  Health: {json.dumps(health, indent=2)}")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(adapter.execute({
                "id": "test-001",
                "prompt": "Say hello in one sentence.",
            }))
            print(f"  Result: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
        finally:
            loop.close()

        adapter.stop()
        print("[STOP] Hermes stopped")
