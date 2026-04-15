# ClawSwarm Examples

Run examples from the project root:

```bash
# Quick start: submit tasks and poll results
python examples/01_quickstart.py

# Parallel tasks: batch submit + aggregate
python examples/02_parallel.py

# MCP Server demo: call ClawSwarm via MCP protocol
python examples/04_mcp_demo.py
```

## Requirements

```bash
pip install aiohttp
# MCP demo also requires: fastapi uvicorn websockets
```
