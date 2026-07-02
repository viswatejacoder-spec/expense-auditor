# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import re
import sys
from typing import Any
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from google.adk.events import RequestInput
from google.adk.workflow import Workflow, Edge, START, DEFAULT_ROUTE, node
from google.adk import Context

from app.config import config

# Initialize MCP toolset to connect to local MCP server
mcp_toolset = McpToolset(connection_params=StreamableHTTPServerParams(url=f"http://localhost:{config.mcp_server_port}/mcp"))
mcp_toolset.name = "mcp"
mcp_toolset.description = "MCP toolset for expense auditor"


# ---------------------------------------------------------------------------
# 1. State Definition
# ---------------------------------------------------------------------------

class AuditState(BaseModel):
    raw_text: str = ""
    parsed_expense: dict = Field(default_factory=dict)
    policy_violations: list[str] = Field(default_factory=list)
    needs_approval: bool = False
    approved: bool = False
    rejection_reason: str = ""
    status: str = "pending"


# ---------------------------------------------------------------------------
# 2. Specialized Agents & Orchestrator
# ---------------------------------------------------------------------------

# Sub-agent A: Parsers receipt details from text/input
receipt_parser = LlmAgent(
    name="receipt_parser",
    description="Parses raw receipts or expense descriptions to extract vendor, amount, currency, category, and date.",
    instruction=(
        "You are a receipt extraction assistant. Extract details from the provided input.\n"
        "Output ONLY a valid JSON object with the following schema:\n"
        "{\n"
        '  "vendor": "string or unknown",\n'
        '  "amount": float or 0.0,\n'
        '  "currency": "string, e.g. USD, EUR",\n'
        '  "category": "string, e.g. Meals, Travel, Software, Office Supplies",\n'
        '  "date": "string or unknown"\n'
        "}\n"
        "Do not output markdown code fences, comments, or extra text. Just the JSON."
    ),
    model=Gemini(
        model=config.model,
    )
)

# Sub-agent B: Verifies company policy compliance
policy_checker = LlmAgent(
    name="policy_checker",
    description="Validates structured expense data against company spending guidelines.",
    instruction=(
        "You are an expense compliance checker. Review the parsed expense data against guidelines:\n"
        "- Meals must be <= $150.\n"
        "- Travel must be <= $500.\n"
        "- Software must be <= $200.\n"
        "- Office Supplies or other categories must be <= $100.\n"
        "Output ONLY a JSON list of violation strings, e.g.:\n"
        '["Meal expense of $175 exceeds the $150 limit"]\n'
        "If there are no violations, output empty list: []\n"
        "Do not include markdown formatting or explanations."
    ),
    model=Gemini(
        model=config.model,
    )
)

# Root Orchestrator coordinating sub-agents via AgentTools
audit_orchestrator = LlmAgent(
    name="audit_orchestrator",
    description="Main coordinating agent for the expense auditor workflow. Manages parsing and checking.",
    instruction=(
        "You are the Lead Expense Audit Orchestrator. Process the expense claim by calling your tools:\n"
        "1. First, call `receipt_parser` to extract structured details from the expense description.\n"
        "2. Next, call `policy_checker` with the parsed details to check for violations.\n"
        "3. Evaluate the results and output a single JSON response indicating if manual human approval is required:\n"
        "   - Claims with any policy violations OR amount >= $1000 require human review.\n"
        "Output ONLY a JSON object formatted exactly as follows:\n"
        "{\n"
        '  "needs_approval": bool,\n'
        '  "approved": bool,\n'
        '  "policy_violations": ["violation description", ...],\n'
        '  "rejection_reason": "string or empty",\n'
        '  "parsed_expense": { ... }\n'
        "}\n"
        "Do not wrap in code fences, write extra text, or explain your decision. Respond with raw JSON."
    ),
    model=Gemini(
        model=config.model,
    ),
    tools=[AgentTool(agent=receipt_parser), AgentTool(agent=policy_checker), mcp_toolset]
)


# ---------------------------------------------------------------------------
# 3. Workflow Nodes
# ---------------------------------------------------------------------------

@node
def security_checkpoint(ctx: Context, node_input: Any):
    """Workflow node checking for prompt injection, PII, and domain keywords."""
    input_text = str(node_input)
    
    # regex for PII (Credit cards and Email)
    cc_regex = r"\b(?:\d[ -]*?){13,16}\b"
    email_regex = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    
    scrubbed_text = input_text
    cc_matches = re.findall(cc_regex, scrubbed_text)
    email_matches = re.findall(email_regex, scrubbed_text)
    
    scrubbed_text = re.sub(cc_regex, "[REDACTED CREDIT CARD]", scrubbed_text)
    scrubbed_text = re.sub(email_regex, "[REDACTED EMAIL]", scrubbed_text)
    
    ctx.state["raw_text"] = scrubbed_text
    
    # Prompt injection check
    injection_keywords = ["ignore instructions", "system prompt", "bypass", "translate this to", "you are now"]
    detected_injection = any(kw in input_text.lower() for kw in injection_keywords)
            
    # Prohibited category keywords
    prohibited_keywords = ["bribe", "gambling", "casino", "weapon", "illicit"]
    detected_prohibited = any(kw in input_text.lower() for kw in prohibited_keywords)
            
    # Structured Audit Log
    audit_event = {
        "timestamp": datetime.datetime.now().isoformat(),
        "event_type": "security_scan",
        "pii_detected": {
            "credit_cards": len(cc_matches) > 0,
            "emails": len(email_matches) > 0
        },
        "prompt_injection_detected": detected_injection,
        "prohibited_content_detected": detected_prohibited,
        "severity": "INFO"
    }
    
    if detected_injection or detected_prohibited:
        audit_event["severity"] = "CRITICAL"
        print(f"AUDIT_LOG: {json.dumps(audit_event)}", file=sys.stderr)
        ctx.route = "security_violation"
        ctx.state["status"] = "flagged"
        ctx.state["rejection_reason"] = (
            "Security check failed: Prompt injection detected."
            if detected_injection else "Security check failed: Prohibited transaction terms."
        )
        return scrubbed_text
        
    if len(cc_matches) > 0 or len(email_matches) > 0:
        audit_event["severity"] = "WARNING"
        
    print(f"AUDIT_LOG: {json.dumps(audit_event)}", file=sys.stderr)
    ctx.route = "clean"
    print(f"[TRACE] security_checkpoint route set to: {ctx.route}", file=sys.stderr)
    return scrubbed_text


@node
def security_violation_handler(ctx: Context, node_input: Any):
    """Workflow node handling rejected claims from the security scanner."""
    return (
        f"========================================\n"
        f"      SECURITY SCAN CHECKS FAILED       \n"
        f"========================================\n"
        f"Your expense claim has been blocked.\n"
        f"Reason: {ctx.state['rejection_reason']}\n"
        f"========================================\n"
    )


@node
def decision_gate(ctx: Context, node_input: Any):
    """Workflow node analyzing orchestrator's recommendation and updating state."""
    try:
        text = str(node_input).strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        data = json.loads(text)
    except Exception as e:
        data = {
            "needs_approval": True,
            "approved": False,
            "policy_violations": [f"Failed to parse audit response: {e}"],
            "rejection_reason": "Invalid response format.",
            "parsed_expense": {}
        }
        
    ctx.state["needs_approval"] = data.get("needs_approval", True)
    ctx.state["approved"] = data.get("approved", False)
    ctx.state["policy_violations"] = data.get("policy_violations", [])
    ctx.state["parsed_expense"] = data.get("parsed_expense", {})
    ctx.state["rejection_reason"] = data.get("rejection_reason", "")
    
    if ctx.state["needs_approval"]:
        ctx.route = "needs_approval"
        print(f"[TRACE] decision_gate set route: {ctx.route}, needs_approval={ctx.state['needs_approval']}", file=sys.stderr)
        return "Expense requires human review due to policy checks."
    else:
        ctx.route = "auto_approved"
        print(f"[TRACE] decision_gate set route: {ctx.route}, auto approved", file=sys.stderr)
        ctx.state["status"] = "approved"
        return "Expense approved automatically."


@node
def human_approval_node(ctx: Context, node_input: Any):
    """Human-in-the-loop approval step requesting user decision."""
    interrupt_id = f"human_review:{ctx.node_path}"
    
    response = ctx.resume_inputs.get(interrupt_id)
    if response is not None:
        approved = response.get("approved", False)
        reason = response.get("reason", "")
        
        ctx.state["approved"] = approved
        if approved:
            ctx.state["status"] = "approved"
            ctx.state["rejection_reason"] = ""
        else:
            ctx.state["status"] = "denied"
            ctx.state["rejection_reason"] = reason or "Rejected by human reviewer."
        return f"Human review complete. Status: {ctx.state['status']}"
        
    expense = ctx.state["parsed_expense"]
    violations_str = ", ".join(ctx.state["policy_violations"]) if ctx.state["policy_violations"] else "None"
    
    message = (
        f"📋 EXPENSE AUDIT MANUAL APPROVAL REQUIRED\n"
        f"----------------------------------------\n"
        f"Vendor: {expense.get('vendor', 'Unknown')}\n"
        f"Amount: {expense.get('amount', 0.0)} {expense.get('currency', 'USD')}\n"
        f"Category: {expense.get('category', 'Unknown')}\n"
        f"Date: {expense.get('date', 'Unknown')}\n"
        f"Violations: {violations_str}\n\n"
        f"Please approve or reject this expense claim."
    )
    
    return RequestInput(
        interrupt_id=interrupt_id,
        message=message,
        response_schema={
            "type": "object",
            "properties": {
                "approved": {
                    "type": "boolean",
                    "description": "True to approve the expense, False to reject."
                },
                "reason": {
                    "type": "string",
                    "description": "Optional comment or reason for rejection."
                }
            },
            "required": ["approved"]
        }
    )


@node
def final_output(ctx: Context, node_input: Any):
    print("STATE TYPE:", type(ctx.state), file=sys.stderr)
    print("STATE:", ctx.state, file=sys.stderr)
    print(f"[TRACE] final_output invoked with status={ctx.state.get('status', 'unknown')}, approved={ctx.state.get('approved', False)}", file=sys.stderr)
    expense = ctx.state.get("parsed_expense", {})
    violations = ctx.state.get("policy_violations", [])
    status = ctx.state.get("status", "unknown")
    approved = ctx.state.get("approved", False)
    
    report = (
        f"========================================\n"
        f"         EXPENSE AUDIT REPORT           \n"
        f"========================================\n"
        f"Status: {status.upper()}\n"
        f"Approved: {approved}\n"
        f"Vendor: {expense.get('vendor', 'N/A')}\n"
        f"Amount: {expense.get('amount', 0.0)} {expense.get('currency', 'USD')}\n"
        f"Category: {expense.get('category', 'N/A')}\n"
        f"Date: {expense.get('date', 'N/A')}\n"
        f"----------------------------------------\n"
        f"Policy Violations found: {len(violations)}\n"
    )
    for v in violations:
        report += f"  - {v}\n"
        
    rejection_reason = ctx.state.get("rejection_reason")
    if not approved and rejection_reason:
        report += f"Rejection Reason: {rejection_reason}\n"
    report += f"========================================\n"
    return report


# ---------------------------------------------------------------------------
# 4. Workflow Graph Construction
# ---------------------------------------------------------------------------

workflow = Workflow(
    name="expense_auditor_workflow",
    state_schema=AuditState,
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=audit_orchestrator, route="clean"),
        Edge(from_node=security_checkpoint, to_node=security_violation_handler, route="security_violation"),
        Edge(from_node=audit_orchestrator, to_node=decision_gate),
        Edge(from_node=decision_gate, to_node=human_approval_node, route="needs_approval"),
        Edge(from_node=decision_gate, to_node=final_output, route="auto_approved"),
        Edge(from_node=human_approval_node, to_node=final_output)
    ]
)


# ---------------------------------------------------------------------------
# 5. App Initialization
# ---------------------------------------------------------------------------

app = App(
    root_agent=workflow,
    name="expense_auditor"
)

# Export root_agent for tests and external use
root_agent = workflow

#for API calls
import time
import random
from google.api_core.exceptions import ServiceUnavailable

def call_with_retry(fn, retries=5):
    for i in range(retries):
        try:
            return fn()
        except ServiceUnavailable:
            wait = (2 ** i) + random.uniform(0, 1)
            time.sleep(wait)
    raise Exception("Gemini overloaded after retries")

#for less concurrent workflow
import asyncio

semaphore = asyncio.Semaphore(2)  # max 2 concurrent workflows
