import os
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict

# Load configuration
from app.config import config

app = FastAPI(title="Expense Auditor MCP Server")

class InvokeRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}

@app.post("/mcp/invoke")
async def invoke(request: InvokeRequest):
    """Placeholder MCP endpoint.
    In a full implementation this would dispatch to a McpToolset on the client side.
    For now we support a simple 'echo' tool that returns the provided params.
    """
    if request.tool == "echo":
        return {"result": request.params}
    raise HTTPException(status_code=400, detail=f"Unknown tool: {request.tool}")

# Optional root endpoint
@app.get("/")
async def root():
    return {"status": "mcp server running"}
