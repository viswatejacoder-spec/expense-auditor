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

"""Unit tests for the expense auditor workflow.

These tests validate the structural integrity of the workflow graph,
App registration, agent configuration, and node definitions against the
Google ADK 2.2 API.  They do NOT execute the workflow (which requires an
InvocationContext-backed Context and a Runner) but they cover everything
that can be verified at import/construction time.
"""

import pytest

from google.adk.workflow import Workflow, Edge, START, node
from google.adk.workflow._function_node import FunctionNode
from google.adk.apps import App
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.events import RequestInput

from app.agent import (
    workflow,
    app,
    root_agent,
    AuditState,
    security_checkpoint,
    security_violation_handler,
    decision_gate,
    human_approval_node,
    final_output,
    audit_orchestrator,
    receipt_parser,
    policy_checker,
)


# ---------------------------------------------------------------------------
# 1. Import smoke tests
# ---------------------------------------------------------------------------

class TestImports:
    """Verify that the critical module-level objects import successfully."""

    def test_app_imports(self):
        assert app is not None

    def test_workflow_imports(self):
        assert workflow is not None

    def test_root_agent_imports(self):
        assert root_agent is not None


# ---------------------------------------------------------------------------
# 2. Name / identity assertions
# ---------------------------------------------------------------------------

class TestNames:
    """Verify the canonical names expected by ADK playground and deployment."""

    def test_workflow_name(self):
        assert workflow.name == "expense_auditor_workflow"

    def test_app_name(self):
        assert app.name == "expense_auditor"

    def test_root_agent_is_workflow(self):
        assert root_agent is workflow

    def test_root_agent_name_matches_workflow(self):
        assert root_agent.name == workflow.name


# ---------------------------------------------------------------------------
# 3. Type assertions
# ---------------------------------------------------------------------------

class TestTypes:
    """Ensure objects are the expected ADK 2.2 types."""

    def test_workflow_is_workflow_instance(self):
        assert isinstance(workflow, Workflow)

    def test_app_is_app_instance(self):
        assert isinstance(app, App)

    def test_app_root_agent_is_workflow(self):
        assert app.root_agent is workflow

    def test_audit_orchestrator_is_llm_agent(self):
        assert isinstance(audit_orchestrator, LlmAgent)

    def test_receipt_parser_is_llm_agent(self):
        assert isinstance(receipt_parser, LlmAgent)

    def test_policy_checker_is_llm_agent(self):
        assert isinstance(policy_checker, LlmAgent)


# ---------------------------------------------------------------------------
# 4. State schema
# ---------------------------------------------------------------------------

class TestStateSchema:
    """Validate the AuditState pydantic model used as workflow state."""

    def test_state_schema_is_audit_state(self):
        assert workflow.state_schema is AuditState

    def test_audit_state_has_required_fields(self):
        expected_fields = {
            "raw_text",
            "parsed_expense",
            "policy_violations",
            "needs_approval",
            "approved",
            "rejection_reason",
            "status",
        }
        assert expected_fields == set(AuditState.model_fields.keys())

    def test_audit_state_defaults(self):
        state = AuditState()
        assert state.raw_text == ""
        assert state.parsed_expense == {}
        assert state.policy_violations == []
        assert state.needs_approval is False
        assert state.approved is False
        assert state.rejection_reason == ""
        assert state.status == "pending"


# ---------------------------------------------------------------------------
# 5. Workflow graph structure
# ---------------------------------------------------------------------------

class TestWorkflowGraph:
    """Validate the graph topology: nodes, edges, and routes."""

    def test_edge_count(self):
        assert len(workflow.edges) == 7

    def test_graph_node_count(self):
        assert len(workflow.graph.nodes) == 7  # START + 6 defined nodes

    def test_graph_node_names(self):
        expected_names = {
            "__START__",
            "security_checkpoint",
            "audit_orchestrator",
            "security_violation_handler",
            "decision_gate",
            "human_approval_node",
            "final_output",
        }
        actual_names = {n.name for n in workflow.graph.nodes}
        assert expected_names == actual_names

    def test_start_edge(self):
        """START -> security_checkpoint (no route condition)."""
        edge = workflow.edges[0]
        assert edge.from_node.name == "__START__"
        assert edge.to_node.name == "security_checkpoint"
        assert edge.route is None

    def test_security_clean_route(self):
        """security_checkpoint --(clean)--> audit_orchestrator."""
        edge = workflow.edges[1]
        assert edge.from_node.name == "security_checkpoint"
        assert edge.to_node.name == "audit_orchestrator"
        assert edge.route == "clean"

    def test_security_violation_route(self):
        """security_checkpoint --(security_violation)--> security_violation_handler."""
        edge = workflow.edges[2]
        assert edge.from_node.name == "security_checkpoint"
        assert edge.to_node.name == "security_violation_handler"
        assert edge.route == "security_violation"

    def test_orchestrator_to_decision_gate(self):
        """audit_orchestrator --> decision_gate (unconditional)."""
        edge = workflow.edges[3]
        assert edge.from_node.name == "audit_orchestrator"
        assert edge.to_node.name == "decision_gate"
        assert edge.route is None

    def test_decision_needs_approval_route(self):
        """decision_gate --(needs_approval)--> human_approval_node."""
        edge = workflow.edges[4]
        assert edge.from_node.name == "decision_gate"
        assert edge.to_node.name == "human_approval_node"
        assert edge.route == "needs_approval"

    def test_decision_auto_approved_route(self):
        """decision_gate --(auto_approved)--> final_output."""
        edge = workflow.edges[5]
        assert edge.from_node.name == "decision_gate"
        assert edge.to_node.name == "final_output"
        assert edge.route == "auto_approved"

    def test_human_approval_to_final_output(self):
        """human_approval_node --> final_output (unconditional)."""
        edge = workflow.edges[6]
        assert edge.from_node.name == "human_approval_node"
        assert edge.to_node.name == "final_output"
        assert edge.route is None


# ---------------------------------------------------------------------------
# 6. Node type assertions
# ---------------------------------------------------------------------------

class TestNodeTypes:
    """Ensure @node-decorated functions become FunctionNode instances."""

    def test_security_checkpoint_is_function_node(self):
        assert isinstance(security_checkpoint, FunctionNode)

    def test_security_violation_handler_is_function_node(self):
        assert isinstance(security_violation_handler, FunctionNode)

    def test_decision_gate_is_function_node(self):
        assert isinstance(decision_gate, FunctionNode)

    def test_human_approval_node_is_function_node(self):
        assert isinstance(human_approval_node, FunctionNode)

    def test_final_output_is_function_node(self):
        assert isinstance(final_output, FunctionNode)

    def test_audit_orchestrator_is_not_function_node(self):
        """The orchestrator is an LlmAgent, not a @node function."""
        assert not isinstance(audit_orchestrator, FunctionNode)


# ---------------------------------------------------------------------------
# 7. Sub-agent configuration
# ---------------------------------------------------------------------------

class TestSubAgentConfig:
    """Validate sub-agent naming and tool wiring."""

    def test_receipt_parser_name(self):
        assert receipt_parser.name == "receipt_parser"

    def test_policy_checker_name(self):
        assert policy_checker.name == "policy_checker"

    def test_audit_orchestrator_name(self):
        assert audit_orchestrator.name == "audit_orchestrator"

    def test_orchestrator_has_tools(self):
        assert audit_orchestrator.tools is not None
        assert len(audit_orchestrator.tools) >= 2  # AgentTool(receipt_parser), AgentTool(policy_checker), mcp_toolset

    def test_orchestrator_has_agent_tools(self):
        agent_tools = [t for t in audit_orchestrator.tools if isinstance(t, AgentTool)]
        assert len(agent_tools) == 2

    def test_orchestrator_agent_tool_agents(self):
        agent_tools = [t for t in audit_orchestrator.tools if isinstance(t, AgentTool)]
        agent_names = {t.agent.name for t in agent_tools}
        assert "receipt_parser" in agent_names
        assert "policy_checker" in agent_names


# ---------------------------------------------------------------------------
# 8. Workflow model fields (ADK 2.2 compatibility)
# ---------------------------------------------------------------------------

class TestWorkflowModelFields:
    """Validate that the Workflow pydantic model has the expected fields."""

    def test_workflow_has_name_field(self):
        assert "name" in Workflow.model_fields

    def test_workflow_has_edges_field(self):
        assert "edges" in Workflow.model_fields

    def test_workflow_has_state_schema_field(self):
        assert "state_schema" in Workflow.model_fields

    def test_workflow_has_graph_field(self):
        assert "graph" in Workflow.model_fields


# ---------------------------------------------------------------------------
# 9. App model fields (ADK 2.2 compatibility)
# ---------------------------------------------------------------------------

class TestAppModelFields:
    """Validate the App pydantic model structure."""

    def test_app_has_name_field(self):
        assert "name" in App.model_fields

    def test_app_has_root_agent_field(self):
        assert "root_agent" in App.model_fields

    def test_app_root_agent_type(self):
        assert app.root_agent is workflow
