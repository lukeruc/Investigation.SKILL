"""Pydantic 校验模型与枚举常量。"""

from __future__ import annotations

from typing import Literal, Annotated

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low"]
ExplorationStatus = Literal[
    "unexplored",
    "exploring",
    "explored",
    "partial",
    "skipped",
    "exhausted",
]
VerificationStatus = Literal["unverified", "verified", "contradicted", "retracted"]
Direction = Literal["directed", "undirected"]
SourceReliability = Literal["A", "B", "C", "D", "E", "X"]
InfoCredibility = Literal["1", "2", "3", "4", "5", "6"]

# ---------------------------------------------------------------------------
# Source chain
# ---------------------------------------------------------------------------


class SourceChainEntry(BaseModel):
    """节点或边的来源链条目。"""

    source_name: str
    source_type: str = "web_search"
    source_reliability: SourceReliability = "X"
    info_credibility: InfoCredibility = "6"
    discovery_time: str | None = None
    discovery_agent: str | None = None
    discovery_context: str | None = None
    raw_data: str = "{}"


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


class SessionCreateInput(BaseModel):
    workspace_path: str
    name: str
    goal: str = ""
    depth_limit: int = Field(default=3, ge=1)


class SessionOpenInput(BaseModel):
    case_path: str


# ---------------------------------------------------------------------------
# Node tools
# ---------------------------------------------------------------------------


class NodeCreateInput(BaseModel):
    type: str
    name: str
    body: str = ""
    confidence: Confidence = "medium"
    source_chain_entry: SourceChainEntry | None = None


class NodeGetInput(BaseModel):
    node_id: str


class NodeUpdateInput(BaseModel):
    node_id: str
    body: str | None = None
    confidence: Confidence | None = None
    exploration_status: ExplorationStatus | None = None
    anomaly_flags: list[str] | None = None


class NodeSearchInput(BaseModel):
    type: str | None = None
    name_pattern: str | None = None
    limit: int = Field(default=50, gt=0)


class NodeListGapsInput(BaseModel):
    type: str | None = None


# ---------------------------------------------------------------------------
# Edge tools
# ---------------------------------------------------------------------------


class EdgeCreateInput(BaseModel):
    source_id: str
    target_id: str
    type: str
    direction: Direction = "directed"
    body: str = ""
    intensity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    confidence: Confidence = "medium"
    source_chain_entry: SourceChainEntry | None = None


class EdgesFromNodeInput(BaseModel):
    node_id: str
    edge_type: str | None = None
    direction: Direction | None = None


# ---------------------------------------------------------------------------
# Graph tools
# ---------------------------------------------------------------------------


class GraphSnapshotInput(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Edge advanced tools
# ---------------------------------------------------------------------------


class EdgeGetInput(BaseModel):
    edge_id: str


class EdgeUpdateInput(BaseModel):
    edge_id: str
    body: str | None = None
    confidence: Confidence | None = None
    verification_status: VerificationStatus | None = None
    intensity: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    anomaly_flags: list[str] | None = None
    contradicted_by: list[str] | None = None


# ---------------------------------------------------------------------------
# Graph path tools
# ---------------------------------------------------------------------------


class GraphPathInput(BaseModel):
    source_node_id: str
    target_node_id: str
    max_depth: int = Field(default=5, ge=1)


class GraphNeighborsInput(BaseModel):
    node_id: str
    depth: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Identity / merge tools
# ---------------------------------------------------------------------------


class IdentityEdgeCreateInput(BaseModel):
    node_a_id: str
    node_b_id: str
    match_basis: str = "name_match"


class IdentityEdgeUpdateInput(BaseModel):
    identity_edge_id: str
    evidence_entry: dict | None = None
    intensity: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    verification_status: VerificationStatus | None = None


class NodeMergeInput(BaseModel):
    node_ids: list[str] = Field(min_length=2)
    reason: str = ""


class NodeUnmergeInput(BaseModel):
    node_id: str
    merge_event_index: int | None = None


# ---------------------------------------------------------------------------
# Report tools
# ---------------------------------------------------------------------------


class ReportSummaryInput(BaseModel):
    node_id: str
