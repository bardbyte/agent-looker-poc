"""
MDM API Client for fetching table metadata.
"""

import httpx
from typing import Optional
from models import TableMetadata, ColumnMetadata, GapAnalysis, GapType


MDM_BASE_URL = "https://lumimdmapi-guse4.aexp.com/api/v1/ngbd/mdm-api"


class MDMClient:
    """Client for interacting with the MDM API."""

    def __init__(self, base_url: str = MDM_BASE_URL, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout

    async def fetch_table_schema(self, table_name: str) -> Optional[TableMetadata]:
        """
        Fetch table schema from MDM API.

        Args:
            table_name: Name of the table to fetch

        Returns:
            TableMetadata object or None if not found
        """
        url = f"{self.base_url}/datasets/schemas"
        params = {"tableName": table_name}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                return TableMetadata.from_api(table_name, data)
            except httpx.HTTPStatusError as e:
                print(f"HTTP error fetching {table_name}: {e}")
                return None
            except Exception as e:
                print(f"Error fetching {table_name}: {e}")
                return None

    def fetch_table_schema_sync(self, table_name: str) -> Optional[TableMetadata]:
        """
        Synchronous version for Streamlit.

        Args:
            table_name: Name of the table to fetch

        Returns:
            TableMetadata object or None if not found
        """
        url = f"{self.base_url}/datasets/schemas"
        params = {"tableName": table_name}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                return TableMetadata.from_api(table_name, data)
        except httpx.HTTPStatusError as e:
            print(f"HTTP error fetching {table_name}: {e}")
            return None
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return None


def analyze_gaps(table: TableMetadata) -> GapAnalysis:
    """
    Analyze a table for metadata gaps.

    Args:
        table: TableMetadata to analyze

    Returns:
        GapAnalysis with detected gaps
    """
    gaps: dict[str, list[GapType]] = {}
    missing_labels = 0
    missing_descriptions = 0
    missing_sensitivity = 0

    # Patterns that suggest sensitivity
    sensitive_patterns = [
        "card", "account", "customer", "cust", "ssn", "phone", "email",
        "address", "name", "dob", "birth", "income", "salary", "balance",
        "credit", "debit", "payment", "transaction", "txn"
    ]

    for col in table.columns:
        col_gaps: list[GapType] = []
        col_name_lower = col.attribute_name.lower()

        # Check for missing label
        if not col.business_name:
            col_gaps.append(GapType.MISSING_LABEL)
            missing_labels += 1

        # Check for missing description
        if not col.attribute_desc:
            col_gaps.append(GapType.MISSING_DESCRIPTION)
            missing_descriptions += 1

        # Check for potentially missing sensitivity classification
        if any(pattern in col_name_lower for pattern in sensitive_patterns):
            if not col.sensitivity_details and not col.is_sensitive:
                col_gaps.append(GapType.MISSING_SENSITIVITY)
                missing_sensitivity += 1

        if col_gaps:
            gaps[col.attribute_name] = col_gaps

    return GapAnalysis(
        table_name=table.table_name,
        total_columns=len(table.columns),
        columns_with_gaps=len(gaps),
        missing_labels=missing_labels,
        missing_descriptions=missing_descriptions,
        missing_sensitivity=missing_sensitivity,
        gaps=gaps,
    )


# Mock data for testing without API access
MOCK_TABLE_DATA = {
    "custins_customer_insights_cardmember": {
        "version": "1.12",
        "status": "ACTIVE",
        "dataset_id": "0b3f1fe2-8e40-479b-8f53-b4ba61dd807c",
        "schema": {
            "schema_id": "1f93e97f-6717-41bf-9cef-e93be5f3fbc1",
            "schema_attributes": [
                {
                    "attribute_name": "rpt_dt",
                    "attribute_position": 1,
                    "attribute_id": "e41c1e58-1f3c-47cb-ab71-bb5994102c66",
                    "business_name": "Report Date",
                    "attribute_desc": "Run date associated to the model execution month of data (e.g. 2023-12-01)",
                    "attribute_type": "DATE",
                    "attribute_format": "yyyy-MM-dd",
                    "is_sensitive": False,
                    "sensitivity_details": None,
                    "is_primary": False,
                    "is_partitioned": True,
                    "time_partition_type": "MONTH",
                },
                {
                    "attribute_name": "card_number",
                    "attribute_position": 2,
                    "attribute_id": "a34ac3d-f0fb-4003-b06c-cdaa8357734e",
                    "business_name": "Card Number",
                    "attribute_desc": "The unique number assigned - 11 Digit Card Number",
                    "attribute_type": "STRING",
                    "is_sensitive": True,
                    "sensitivity_details": "CM15",
                    "pii_role_id": "NGBD-SDE-CM15",
                    "is_primary": False,
                },
                {
                    "attribute_name": "cust_xref_id",
                    "attribute_position": 3,
                    "attribute_id": "d6a2d713-a585-4374-be09-68cb19a51d14",
                    "business_name": "Customer Reference Identifier",
                    "attribute_desc": "A unique number that is internally created by American Express to identify an individual customer",
                    "attribute_type": "INT64",
                    "is_sensitive": True,
                    "sensitivity_details": "NGBD-SDE-CM11",
                    "pii_role_id": "NGBD-SDE-CM11",
                    "is_primary": False,
                    "is_dedupe_key": True,
                },
                {
                    "attribute_name": "product_group",
                    "attribute_position": 4,
                    "attribute_id": "cf72f25c-334b-4d68-88b9-be6d257f3557",
                    "business_name": "Product Group",
                    "attribute_desc": "Product grouping (e.g. Consumer, Small Business, Corporate, etc)",
                    "attribute_type": "STRING",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "sub_product_group",
                    "attribute_position": 5,
                    "attribute_id": "0daec0a7-6b63-41da-97a1-example",
                    "business_name": None,  # GAP: Missing label
                    "attribute_desc": "Additional products under the product group",
                    "attribute_type": "STRING",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "business_org",
                    "attribute_position": 6,
                    "attribute_id": "example-uuid-business-org",
                    "business_name": None,  # GAP: Missing label
                    "attribute_desc": None,  # GAP: Missing description
                    "attribute_type": "STRING",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "txn_cnt",
                    "attribute_position": 7,
                    "attribute_id": "example-uuid-txn-cnt",
                    "business_name": None,  # GAP: Missing label
                    "attribute_desc": None,  # GAP: Missing description
                    "attribute_type": "INT64",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "total_spend_amt",
                    "attribute_position": 8,
                    "attribute_id": "example-uuid-spend",
                    "business_name": None,  # GAP: Missing label
                    "attribute_desc": "Total spending amount for the customer",
                    "attribute_type": "FLOAT64",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "avg_txn_amt",
                    "attribute_position": 9,
                    "attribute_id": "example-uuid-avg-txn",
                    "business_name": "Average Transaction Amount",
                    "attribute_desc": None,  # GAP: Missing description
                    "attribute_type": "FLOAT64",
                    "is_sensitive": False,
                },
                {
                    "attribute_name": "customer_tenure_months",
                    "attribute_position": 10,
                    "attribute_id": "example-uuid-tenure",
                    "business_name": None,  # GAP: Missing label
                    "attribute_desc": None,  # GAP: Missing description
                    "attribute_type": "INT64",
                    "is_sensitive": False,
                },
            ]
        }
    }
}


def get_mock_table(table_name: str) -> Optional[TableMetadata]:
    """Get mock table data for testing."""
    if table_name in MOCK_TABLE_DATA:
        return TableMetadata.from_api(table_name, MOCK_TABLE_DATA[table_name])
    return None
