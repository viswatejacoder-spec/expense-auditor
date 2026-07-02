# Implementation Plan for MCP Integration

## Goal Description
Enable true Model Context Protocol (MCP) integration for the expense auditor application so that the `MCPToolset` discovers and invokes external tools (e.g., an `echo` tool) from the ADK workflow.

## User Review Required
- Confirm that exposing the MCP endpoint at the root (`/`) is acceptable; alternative paths can be used.
- Approve the decision to add a lightweight test agent (`mcp_test_agent`) for manual prompt testing.

## Open Questions
- Do you need additional MCP tools beyond `echo` (e.g., file access) now, or will you add them later?
- Should the MCP server run on a separate process or as part of the same FastAPI app?

## Proposed Changes
---
### app/mcp_server.py
- Replace the custom `/mcp/invoke` endpoint with a standards‑compliant JSON‑RPC endpoint at `/`.
- Implement a minimal JSON‑RPC dispatcher that loads a tool registry.
- Register an `echo` tool that returns the provided `params` unchanged.
- Keep a simple health check at `/health`.

---
### app/agent.py
- Import `MCPToolset` (already done) and pass it to the orchestrator via the `toolsets` argument.
- Modify `audit_orchestrator` construction:
  ```python
  audit_orchestrator = LlmAgent(
      ...,
      tools=[AgentTool(agent=receipt_parser), AgentTool(agent=policy_checker)],
      toolsets=[mcp_toolset],
  )
  ```
- Add an optional test agent (`mcp_test_agent`) that only calls the `echo` tool – useful for manual verification.

---
### pyproject.toml
- Ensure `mcp` dependency is present (already) and add `fastapi[all]` for proper JSON‑RPC handling if needed (already present via FastAPI).

## Verification Plan
### Automated Tests
- Spin up the FastAPI server and send a JSON‑RPC request:
  ```json
  {"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"msg": "test"}}
  ```
- Assert the response matches `{"jsonrpc":"2.0","id":1,"result":{"msg":"test"}}`.
- Run the ADK app (`uv run adk web`) and issue a prompt `Echo hello` to the workflow; the orchestrator should discover the `echo` tool via `MCPToolset` and invoke it.

### Manual Verification
- User can call the endpoint via `curl` or the UI and observe the JSON‑RPC response.
- In the chat UI, type a prompt that triggers the `echo` tool (e.g., "Please echo the phrase ‘hello world’"). The final report should include the echoed message.

---
