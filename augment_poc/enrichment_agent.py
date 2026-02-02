"""
Enrichment Agent using SafeChain for LLM-powered metadata suggestions.
"""

import asyncio
import json
import re
from typing import List, Optional
from dataclasses import dataclass

from models import (
    ColumnMetadata, EnrichmentSuggestion, GapType, GapAnalysis, TableMetadata
)

# Try to import SafeChain - fall back to mock if not available
try:
    from safechain.tools.mcp import MCPToolLoader, MCPToolAgent
    from ee_config.config import Config
    from langchain_core.messages import HumanMessage, SystemMessage
    SAFECHAIN_AVAILABLE = True
except ImportError:
    SAFECHAIN_AVAILABLE = False
    print("SafeChain not available - using mock suggestions")


ENRICHMENT_SYSTEM_PROMPT = """You are a Data Steward Assistant specializing in metadata enrichment.

Your task is to analyze database column metadata and suggest improvements for:
1. Business-friendly labels (business_name)
2. Clear descriptions (attribute_desc)
3. Sensitivity classifications when patterns suggest PII

## Context
You're working with enterprise data tables. Column names often use abbreviations:
- "cust" = customer
- "xref" = cross-reference
- "txn" = transaction
- "amt" = amount
- "cnt" = count
- "dt" = date
- "id" = identifier
- "org" = organization
- "grp" = group

## Sensitivity Tiers
- CM15: Highly Sensitive PII (card numbers, SSN, account numbers)
- CM11: Internal Confidential (customer IDs, revenue amounts)
- null: Not sensitive (dates, product categories)

## Output Format
For each column that needs enrichment, respond with JSON:
```json
{
  "suggestions": [
    {
      "column_name": "column_name_here",
      "suggested_label": "Business Friendly Label",
      "suggested_description": "A clear description of what this column contains and how it's used.",
      "suggested_sensitivity": "CM11 or CM15 or null",
      "reasoning": "Why I made these suggestions",
      "confidence": 0.95
    }
  ]
}
```

Be concise but thorough. Focus on business value and clarity.
"""


@dataclass
class EnrichmentResult:
    """Result of enrichment analysis."""
    suggestions: List[EnrichmentSuggestion]
    raw_response: str = ""
    error: Optional[str] = None


class EnrichmentAgent:
    """
    Agent for generating metadata enrichment suggestions.

    Uses SafeChain for LLM access when available, falls back to mock.
    """

    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock or not SAFECHAIN_AVAILABLE
        self.agent = None
        self.initialized = False

    async def initialize(self):
        """Initialize the SafeChain agent."""
        if self.use_mock:
            self.initialized = True
            return

        try:
            config = Config.from_env()
            tools = await MCPToolLoader.load_tools(config)
            model_id = getattr(config, 'model_id', None) or "gemini-pro"
            self.agent = MCPToolAgent(model_id, tools)
            self.initialized = True
        except Exception as e:
            print(f"Failed to initialize SafeChain: {e}")
            self.use_mock = True
            self.initialized = True

    def initialize_sync(self):
        """Synchronous initialization for Streamlit."""
        if self.use_mock:
            self.initialized = True
            return

        try:
            asyncio.run(self.initialize())
        except Exception as e:
            print(f"Failed to initialize: {e}")
            self.use_mock = True
            self.initialized = True

    async def generate_suggestions(
        self,
        table: TableMetadata,
        gaps: GapAnalysis
    ) -> EnrichmentResult:
        """
        Generate enrichment suggestions for columns with gaps.

        Args:
            table: Table metadata
            gaps: Gap analysis results

        Returns:
            EnrichmentResult with suggestions
        """
        if not self.initialized:
            await self.initialize()

        if self.use_mock:
            return self._generate_mock_suggestions(table, gaps)

        # Build prompt with column context
        columns_with_gaps = [
            col for col in table.columns
            if col.attribute_name in gaps.gaps
        ]

        if not columns_with_gaps:
            return EnrichmentResult(suggestions=[])

        prompt = self._build_prompt(table, columns_with_gaps, gaps)

        try:
            messages = [
                SystemMessage(content=ENRICHMENT_SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ]
            result = await self.agent.ainvoke(messages)

            # Parse response
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            suggestions = self._parse_suggestions(content, gaps)

            return EnrichmentResult(
                suggestions=suggestions,
                raw_response=content
            )
        except Exception as e:
            return EnrichmentResult(
                suggestions=[],
                error=str(e)
            )

    def generate_suggestions_sync(
        self,
        table: TableMetadata,
        gaps: GapAnalysis
    ) -> EnrichmentResult:
        """Synchronous version for Streamlit."""
        if self.use_mock:
            return self._generate_mock_suggestions(table, gaps)

        try:
            return asyncio.run(self.generate_suggestions(table, gaps))
        except Exception as e:
            return EnrichmentResult(suggestions=[], error=str(e))

    def _build_prompt(
        self,
        table: TableMetadata,
        columns: List[ColumnMetadata],
        gaps: GapAnalysis
    ) -> str:
        """Build the prompt for the LLM."""
        lines = [
            f"## Table: {table.table_name}",
            f"Total columns: {len(table.columns)}",
            f"Columns needing enrichment: {len(columns)}",
            "",
            "## Columns to Enrich:",
            ""
        ]

        for col in columns:
            col_gaps = gaps.gaps.get(col.attribute_name, [])
            gap_types = [g.value for g in col_gaps]

            lines.append(f"### {col.attribute_name}")
            lines.append(f"- Type: {col.attribute_type}")
            lines.append(f"- Current label: {col.business_name or 'MISSING'}")
            lines.append(f"- Current description: {col.attribute_desc or 'MISSING'}")
            lines.append(f"- Current sensitivity: {col.sensitivity_details or 'Not classified'}")
            lines.append(f"- Gaps: {', '.join(gap_types)}")
            lines.append("")

        lines.append("Please provide suggestions for each column above.")

        return "\n".join(lines)

    def _parse_suggestions(
        self,
        response: str,
        gaps: GapAnalysis
    ) -> List[EnrichmentSuggestion]:
        """Parse LLM response into suggestions."""
        suggestions = []

        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                for item in data.get("suggestions", []):
                    col_name = item.get("column_name", "")
                    col_gaps = gaps.gaps.get(col_name, [])

                    for gap_type in col_gaps:
                        suggestion = EnrichmentSuggestion(
                            column_name=col_name,
                            gap_type=gap_type,
                            suggested_label=item.get("suggested_label"),
                            suggested_description=item.get("suggested_description"),
                            suggested_sensitivity=item.get("suggested_sensitivity"),
                            reasoning=item.get("reasoning", ""),
                            confidence=item.get("confidence", 0.8),
                        )
                        suggestions.append(suggestion)
            except json.JSONDecodeError:
                pass

        return suggestions

    def _generate_mock_suggestions(
        self,
        table: TableMetadata,
        gaps: GapAnalysis
    ) -> EnrichmentResult:
        """Generate mock suggestions for testing."""
        suggestions = []

        # Mock suggestion mappings
        label_suggestions = {
            "sub_product_group": "Sub Product Group",
            "business_org": "Business Organization",
            "txn_cnt": "Transaction Count",
            "total_spend_amt": "Total Spend Amount",
            "customer_tenure_months": "Customer Tenure (Months)",
            "avg_txn_amt": "Average Transaction Amount",
        }

        description_suggestions = {
            "sub_product_group": "Subdivision of the product group indicating specific product variants (e.g., Delta Gold, Delta Platinum, Cobrand offerings)",
            "business_org": "The business organization or division associated with the customer's account",
            "txn_cnt": "Total number of transactions made by the customer during the reporting period",
            "total_spend_amt": "Aggregate spending amount across all transactions for the customer in USD",
            "customer_tenure_months": "Number of months the customer has been active with American Express",
            "avg_txn_amt": "Average transaction amount calculated as total spend divided by transaction count",
        }

        sensitivity_suggestions = {
            "txn_cnt": None,
            "total_spend_amt": "CM11",
            "customer_tenure_months": None,
        }

        for col_name, col_gaps in gaps.gaps.items():
            for gap_type in col_gaps:
                suggestion = EnrichmentSuggestion(
                    column_name=col_name,
                    gap_type=gap_type,
                    reasoning="Generated based on column naming patterns and common enterprise data conventions",
                    confidence=0.85,
                )

                if gap_type == GapType.MISSING_LABEL:
                    suggestion.suggested_label = label_suggestions.get(
                        col_name,
                        col_name.replace("_", " ").title()
                    )

                if gap_type == GapType.MISSING_DESCRIPTION:
                    suggestion.suggested_description = description_suggestions.get(
                        col_name,
                        f"Description for {col_name.replace('_', ' ')}"
                    )

                if gap_type == GapType.MISSING_SENSITIVITY:
                    suggestion.suggested_sensitivity = sensitivity_suggestions.get(col_name)

                suggestions.append(suggestion)

        return EnrichmentResult(suggestions=suggestions)
