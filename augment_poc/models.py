"""
Data models for the Semantic Enrichment PoC.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class GapType(str, Enum):
    """Types of metadata gaps."""
    MISSING_LABEL = "missing_label"
    MISSING_DESCRIPTION = "missing_description"
    MISSING_SENSITIVITY = "missing_sensitivity"
    UNCLEAR_DESCRIPTION = "unclear_description"


class ApprovalStatus(str, Enum):
    """Status of a suggestion."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


@dataclass
class ColumnMetadata:
    """Represents a column from MDM API."""
    attribute_name: str
    attribute_position: int
    attribute_id: str
    attribute_type: str

    # Business metadata (key for enrichment)
    business_name: Optional[str] = None
    attribute_desc: Optional[str] = None
    aka_synonyms: Optional[str] = None

    # Sensitivity
    is_sensitive: bool = False
    sensitivity_details: Optional[str] = None
    pii_role_id: Optional[str] = None

    # Key flags
    is_primary: bool = False
    is_dedupe_key: bool = False
    is_partitioned: bool = False
    partition_position: Optional[int] = None
    time_partition_type: Optional[str] = None

    # Technical
    attribute_format: Optional[str] = None
    attribute_length: Optional[int] = None
    is_derived: bool = False
    derived_logic: Optional[str] = None

    @classmethod
    def from_api(cls, data: dict) -> "ColumnMetadata":
        """Create from MDM API response."""
        return cls(
            attribute_name=data.get("attribute_name", ""),
            attribute_position=data.get("attribute_position", 0),
            attribute_id=data.get("attribute_id", ""),
            attribute_type=data.get("attribute_type", "STRING"),
            business_name=data.get("business_name"),
            attribute_desc=data.get("attribute_desc"),
            aka_synonyms=data.get("aka_synonyms"),
            is_sensitive=data.get("is_sensitive", False),
            sensitivity_details=data.get("sensitivity_details"),
            pii_role_id=data.get("pii_role_id"),
            is_primary=data.get("is_primary", False),
            is_dedupe_key=data.get("is_dedupe_key", False),
            is_partitioned=data.get("is_partitioned", False),
            partition_position=data.get("partition_position"),
            time_partition_type=data.get("time_partition_type"),
            attribute_format=data.get("attribute_format"),
            attribute_length=data.get("attribute_length"),
            is_derived=data.get("is_derived", False),
            derived_logic=data.get("derived_logic"),
        )


@dataclass
class EnrichmentSuggestion:
    """LLM-generated suggestion for a column."""
    column_name: str
    gap_type: GapType

    # Suggestions
    suggested_label: Optional[str] = None
    suggested_description: Optional[str] = None
    suggested_sensitivity: Optional[str] = None

    # Reasoning
    reasoning: str = ""
    confidence: float = 0.0

    # Approval workflow
    status: ApprovalStatus = ApprovalStatus.PENDING
    edited_label: Optional[str] = None
    edited_description: Optional[str] = None
    edited_sensitivity: Optional[str] = None


@dataclass
class TableMetadata:
    """Represents a table from MDM API."""
    table_name: str
    dataset_id: str
    schema_id: str
    version: str
    status: str
    columns: List[ColumnMetadata] = field(default_factory=list)

    @classmethod
    def from_api(cls, table_name: str, data: dict) -> "TableMetadata":
        """Create from MDM API response."""
        schema = data.get("schema", {})
        attributes = schema.get("schema_attributes", [])

        columns = [ColumnMetadata.from_api(attr) for attr in attributes]
        columns.sort(key=lambda c: c.attribute_position)

        return cls(
            table_name=table_name,
            dataset_id=data.get("dataset_id", ""),
            schema_id=schema.get("schema_id", ""),
            version=data.get("version", ""),
            status=data.get("status", ""),
            columns=columns,
        )


@dataclass
class GapAnalysis:
    """Results of gap analysis for a table."""
    table_name: str
    total_columns: int
    columns_with_gaps: int

    # Gap counts
    missing_labels: int = 0
    missing_descriptions: int = 0
    missing_sensitivity: int = 0

    # Detailed gaps
    gaps: Dict[str, List[GapType]] = field(default_factory=dict)

    @property
    def completion_rate(self) -> float:
        """Percentage of columns fully documented."""
        if self.total_columns == 0:
            return 100.0
        return ((self.total_columns - self.columns_with_gaps) / self.total_columns) * 100


@dataclass
class EnrichedColumn:
    """Column with enrichment applied."""
    original: ColumnMetadata
    enriched_label: Optional[str] = None
    enriched_description: Optional[str] = None
    enriched_sensitivity: Optional[str] = None

    @property
    def final_label(self) -> str:
        """Get the final label (enriched or original)."""
        return self.enriched_label or self.original.business_name or ""

    @property
    def final_description(self) -> str:
        """Get the final description (enriched or original)."""
        return self.enriched_description or self.original.attribute_desc or ""

    @property
    def final_sensitivity(self) -> Optional[str]:
        """Get the final sensitivity (enriched or original)."""
        return self.enriched_sensitivity or self.original.sensitivity_details


@dataclass
class SQLParseResult:
    """Result of parsing a SQL query."""
    original_sql: str
    view_name: str
    dimensions: List[Dict[str, str]] = field(default_factory=list)
    measures: List[Dict[str, str]] = field(default_factory=list)
    derived_table_sql: str = ""
