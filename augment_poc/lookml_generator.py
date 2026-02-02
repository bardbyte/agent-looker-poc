"""
LookML Generator - Creates valid .view.lkml files from enriched metadata.
"""

from typing import List, Optional, Dict
from models import ColumnMetadata, EnrichedColumn, TableMetadata


def map_type_to_lookml(mdm_type: str) -> str:
    """Map MDM attribute types to LookML types."""
    type_map = {
        "STRING": "string",
        "INT64": "number",
        "INTEGER": "number",
        "FLOAT64": "number",
        "FLOAT": "number",
        "NUMERIC": "number",
        "DECIMAL": "number",
        "DATE": "date",
        "DATETIME": "date_time",
        "TIMESTAMP": "date_time",
        "TIME": "string",
        "BOOLEAN": "yesno",
        "BOOL": "yesno",
        "BYTES": "string",
        "GEOGRAPHY": "string",
        "JSON": "string",
    }
    return type_map.get(mdm_type.upper(), "string")


def generate_dimension(
    col: ColumnMetadata,
    enriched: Optional[EnrichedColumn] = None,
    indent: int = 2
) -> str:
    """
    Generate a LookML dimension block.

    Args:
        col: Column metadata
        enriched: Optional enriched column data
        indent: Indentation spaces

    Returns:
        LookML dimension block as string
    """
    ind = " " * indent
    lines = []

    # Get final values (enriched or original)
    label = (enriched.final_label if enriched else col.business_name) or ""
    description = (enriched.final_description if enriched else col.attribute_desc) or ""
    sensitivity = (enriched.final_sensitivity if enriched else col.sensitivity_details)

    lines.append(f"{ind}dimension: {col.attribute_name} {{")

    # Type
    lookml_type = map_type_to_lookml(col.attribute_type)
    lines.append(f"{ind}  type: {lookml_type}")

    # SQL reference
    lines.append(f"{ind}  sql: ${{TABLE}}.{col.attribute_name} ;;")

    # Label
    if label:
        lines.append(f'{ind}  label: "{label}"')

    # Description
    if description:
        # Escape quotes in description
        desc_escaped = description.replace('"', '\\"')
        lines.append(f'{ind}  description: "{desc_escaped}"')

    # Primary key
    if col.is_primary or col.is_dedupe_key:
        lines.append(f"{ind}  primary_key: yes")

    # Tags (sensitivity)
    tags = []
    if sensitivity:
        tags.append(f"sensitivity:{sensitivity}")
    if col.is_sensitive:
        tags.append("pii")
    if col.is_partitioned:
        tags.append("partition")

    if tags:
        tags_str = ", ".join(f'"{t}"' for t in tags)
        lines.append(f"{ind}  tags: [{tags_str}]")

    # Hidden for sensitive fields
    if col.is_sensitive:
        lines.append(f"{ind}  hidden: yes")

    lines.append(f"{ind}}}")

    return "\n".join(lines)


def generate_date_dimension(
    col: ColumnMetadata,
    enriched: Optional[EnrichedColumn] = None,
    indent: int = 2
) -> str:
    """
    Generate a LookML dimension_group for date fields.

    Args:
        col: Column metadata (must be DATE or DATETIME type)
        enriched: Optional enriched column data
        indent: Indentation spaces

    Returns:
        LookML dimension_group block as string
    """
    ind = " " * indent
    lines = []

    label = (enriched.final_label if enriched else col.business_name) or ""
    description = (enriched.final_description if enriched else col.attribute_desc) or ""

    # Remove common date suffixes for group name
    group_name = col.attribute_name
    for suffix in ["_dt", "_date", "_datetime", "_ts", "_timestamp"]:
        if group_name.endswith(suffix):
            group_name = group_name[:-len(suffix)]
            break

    lines.append(f"{ind}dimension_group: {group_name} {{")
    lines.append(f"{ind}  type: time")
    lines.append(f"{ind}  timeframes: [raw, date, week, month, quarter, year]")

    # Datatype
    if col.attribute_type.upper() in ["DATETIME", "TIMESTAMP"]:
        lines.append(f"{ind}  datatype: datetime")
    else:
        lines.append(f"{ind}  datatype: date")

    lines.append(f"{ind}  sql: ${{TABLE}}.{col.attribute_name} ;;")

    if label:
        lines.append(f'{ind}  label: "{label}"')

    if description:
        desc_escaped = description.replace('"', '\\"')
        lines.append(f'{ind}  description: "{desc_escaped}"')

    # Partition tag
    if col.is_partitioned:
        lines.append(f'{ind}  tags: ["partition"]')

    lines.append(f"{ind}}}")

    return "\n".join(lines)


def generate_measure(
    name: str,
    measure_type: str,
    sql_field: str,
    label: Optional[str] = None,
    description: Optional[str] = None,
    indent: int = 2
) -> str:
    """
    Generate a LookML measure block.

    Args:
        name: Measure name
        measure_type: LookML measure type (count, sum, average, etc.)
        sql_field: SQL field reference
        label: Optional label
        description: Optional description
        indent: Indentation spaces

    Returns:
        LookML measure block as string
    """
    ind = " " * indent
    lines = []

    lines.append(f"{ind}measure: {name} {{")
    lines.append(f"{ind}  type: {measure_type}")

    if measure_type != "count":
        lines.append(f"{ind}  sql: ${{TABLE}}.{sql_field} ;;")

    if label:
        lines.append(f'{ind}  label: "{label}"')

    if description:
        desc_escaped = description.replace('"', '\\"')
        lines.append(f'{ind}  description: "{desc_escaped}"')

    lines.append(f"{ind}}}")

    return "\n".join(lines)


def generate_view(
    table: TableMetadata,
    enriched_columns: Optional[Dict[str, EnrichedColumn]] = None,
    include_measures: bool = True
) -> str:
    """
    Generate a complete LookML view file.

    Args:
        table: Table metadata
        enriched_columns: Optional dict of column_name -> EnrichedColumn
        include_measures: Whether to auto-generate measures for numeric fields

    Returns:
        Complete LookML view as string
    """
    enriched_columns = enriched_columns or {}
    lines = []

    # View header
    view_name = table.table_name.lower()
    lines.append(f"view: {view_name} {{")
    lines.append(f'  sql_table_name: `project.dataset.{table.table_name}` ;;')
    lines.append("")

    # Dimensions
    lines.append("  # ============ DIMENSIONS ============")
    lines.append("")

    date_types = {"DATE", "DATETIME", "TIMESTAMP"}
    numeric_types = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "DECIMAL"}

    for col in table.columns:
        enriched = enriched_columns.get(col.attribute_name)

        if col.attribute_type.upper() in date_types:
            lines.append(generate_date_dimension(col, enriched))
        else:
            lines.append(generate_dimension(col, enriched))
        lines.append("")

    # Measures
    if include_measures:
        lines.append("  # ============ MEASURES ============")
        lines.append("")

        # Always add count
        lines.append(generate_measure(
            name="count",
            measure_type="count",
            sql_field="",
            label="Row Count",
            description="Total number of records"
        ))
        lines.append("")

        # Add sum/average for numeric columns
        for col in table.columns:
            if col.attribute_type.upper() in numeric_types:
                enriched = enriched_columns.get(col.attribute_name)
                label = (enriched.final_label if enriched else col.business_name) or col.attribute_name.replace("_", " ").title()

                # Check if it looks like a countable field
                if any(suffix in col.attribute_name.lower() for suffix in ["_cnt", "_count", "_qty", "_num"]):
                    lines.append(generate_measure(
                        name=f"total_{col.attribute_name}",
                        measure_type="sum",
                        sql_field=col.attribute_name,
                        label=f"Total {label}",
                        description=f"Sum of {label}"
                    ))
                    lines.append("")

                # Check if it looks like an amount field
                elif any(suffix in col.attribute_name.lower() for suffix in ["_amt", "_amount", "_spend", "_revenue", "_cost"]):
                    lines.append(generate_measure(
                        name=f"total_{col.attribute_name}",
                        measure_type="sum",
                        sql_field=col.attribute_name,
                        label=f"Total {label}",
                        description=f"Sum of {label}"
                    ))
                    lines.append("")
                    lines.append(generate_measure(
                        name=f"avg_{col.attribute_name}",
                        measure_type="average",
                        sql_field=col.attribute_name,
                        label=f"Average {label}",
                        description=f"Average of {label}"
                    ))
                    lines.append("")

    lines.append("}")

    return "\n".join(lines)


def generate_derived_table_view(
    view_name: str,
    sql: str,
    dimensions: List[Dict[str, str]],
    measures: List[Dict[str, str]]
) -> str:
    """
    Generate a LookML view with a derived table from SQL.

    Args:
        view_name: Name for the view
        sql: SQL query for derived table
        dimensions: List of dimension dicts with name, type, label
        measures: List of measure dicts with name, type, sql_field, label

    Returns:
        Complete LookML view as string
    """
    lines = []

    lines.append(f"view: {view_name} {{")
    lines.append("  derived_table: {")
    lines.append("    sql:")

    # Indent SQL properly
    for sql_line in sql.strip().split("\n"):
        lines.append(f"      {sql_line}")

    lines.append("    ;;")
    lines.append("  }")
    lines.append("")

    # Dimensions
    if dimensions:
        lines.append("  # ============ DIMENSIONS ============")
        lines.append("")

        for dim in dimensions:
            lines.append(f"  dimension: {dim['name']} {{")
            lines.append(f"    type: {dim.get('type', 'string')}")
            lines.append(f"    sql: ${{TABLE}}.{dim['name']} ;;")
            if dim.get('label'):
                lines.append(f'    label: "{dim["label"]}"')
            if dim.get('description'):
                lines.append(f'    description: "{dim["description"]}"')
            lines.append("  }")
            lines.append("")

    # Measures
    if measures:
        lines.append("  # ============ MEASURES ============")
        lines.append("")

        for meas in measures:
            lines.append(f"  measure: {meas['name']} {{")
            lines.append(f"    type: {meas.get('type', 'sum')}")
            if meas.get('type') != 'count':
                lines.append(f"    sql: ${{TABLE}}.{meas.get('sql_field', meas['name'])} ;;")
            if meas.get('label'):
                lines.append(f'    label: "{meas["label"]}"')
            if meas.get('description'):
                lines.append(f'    description: "{meas["description"]}"')
            lines.append("  }")
            lines.append("")

    lines.append("}")

    return "\n".join(lines)
