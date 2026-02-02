"""
SQL Parser - Parse SQL queries and extract dimensions/measures for LookML.
"""

import re
from typing import List, Dict, Tuple, Optional
from models import SQLParseResult


def clean_sql(sql: str) -> str:
    """Clean and normalize SQL query."""
    # Remove comments
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)

    # Normalize whitespace
    sql = ' '.join(sql.split())

    return sql.strip()


def extract_select_columns(sql: str) -> List[str]:
    """Extract column expressions from SELECT clause."""
    sql_upper = sql.upper()

    # Find SELECT ... FROM
    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return []

    select_clause = select_match.group(1)

    # Handle nested parentheses
    columns = []
    current = ""
    paren_depth = 0

    for char in select_clause:
        if char == '(':
            paren_depth += 1
            current += char
        elif char == ')':
            paren_depth -= 1
            current += char
        elif char == ',' and paren_depth == 0:
            columns.append(current.strip())
            current = ""
        else:
            current += char

    if current.strip():
        columns.append(current.strip())

    return columns


def parse_column_expression(expr: str) -> Dict[str, str]:
    """
    Parse a column expression to extract name, type, and any alias.

    Returns dict with: name, alias, expression, is_aggregate
    """
    expr = expr.strip()

    # Check for alias (AS or just space before final word)
    alias_match = re.search(r'\s+AS\s+(\w+)\s*$', expr, re.IGNORECASE)
    if alias_match:
        alias = alias_match.group(1)
        expression = expr[:alias_match.start()].strip()
    else:
        # Check for implicit alias (expression word at end)
        parts = expr.split()
        if len(parts) > 1 and re.match(r'^\w+$', parts[-1]):
            # Could be implicit alias
            alias = parts[-1]
            expression = ' '.join(parts[:-1])
        else:
            alias = None
            expression = expr

    # Determine if aggregate
    aggregate_patterns = [
        r'\bSUM\s*\(',
        r'\bCOUNT\s*\(',
        r'\bAVG\s*\(',
        r'\bMIN\s*\(',
        r'\bMAX\s*\(',
        r'\bCOUNT\s*\(\s*DISTINCT',
    ]
    is_aggregate = any(re.search(p, expr, re.IGNORECASE) for p in aggregate_patterns)

    # Extract base column name if simple reference
    simple_col = re.match(r'^(\w+)\.?(\w*)$', expression)
    if simple_col:
        name = simple_col.group(2) or simple_col.group(1)
    else:
        name = alias or expression[:30].replace(' ', '_')

    # Infer type from expression
    inferred_type = "string"
    if is_aggregate:
        inferred_type = "number"
    elif re.search(r'\bDATE\b|\bTIMESTAMP\b', expression, re.IGNORECASE):
        inferred_type = "date"
    elif re.search(r'\bCAST\s*\([^)]+\s+AS\s+INT', expression, re.IGNORECASE):
        inferred_type = "number"

    return {
        "name": (alias or name).lower().replace(' ', '_'),
        "alias": alias,
        "expression": expression,
        "is_aggregate": is_aggregate,
        "type": inferred_type,
    }


def extract_group_by_columns(sql: str) -> List[str]:
    """Extract columns from GROUP BY clause."""
    group_match = re.search(
        r'GROUP\s+BY\s+(.*?)(?:HAVING|ORDER|LIMIT|$)',
        sql,
        re.IGNORECASE | re.DOTALL
    )
    if not group_match:
        return []

    group_clause = group_match.group(1)

    # Split by comma, handling potential expressions
    columns = []
    current = ""
    paren_depth = 0

    for char in group_clause:
        if char == '(':
            paren_depth += 1
            current += char
        elif char == ')':
            paren_depth -= 1
            current += char
        elif char == ',' and paren_depth == 0:
            col = current.strip()
            if col:
                columns.append(col)
            current = ""
        else:
            current += char

    if current.strip():
        columns.append(current.strip())

    # Clean up column references (remove table aliases)
    cleaned = []
    for col in columns:
        # Handle numeric references (GROUP BY 1, 2, 3)
        if col.isdigit():
            cleaned.append(f"col_{col}")
        else:
            # Remove table alias prefix
            parts = col.split('.')
            cleaned.append(parts[-1].strip())

    return cleaned


def infer_view_name(sql: str) -> str:
    """Infer a view name from the SQL query."""
    # Try to extract from main table
    from_match = re.search(r'FROM\s+(\w+)\.?(\w*)\.?(\w*)', sql, re.IGNORECASE)
    if from_match:
        parts = [p for p in from_match.groups() if p]
        return parts[-1].lower() if parts else "derived_view"

    return "derived_view"


def parse_sql_to_lookml(sql: str, view_name: Optional[str] = None) -> SQLParseResult:
    """
    Parse a SQL query and extract components for LookML generation.

    Args:
        sql: SQL query string
        view_name: Optional view name (inferred if not provided)

    Returns:
        SQLParseResult with extracted dimensions and measures
    """
    cleaned_sql = clean_sql(sql)

    if not view_name:
        view_name = infer_view_name(cleaned_sql)

    # Extract columns
    select_columns = extract_select_columns(cleaned_sql)
    group_by_columns = extract_group_by_columns(cleaned_sql)

    dimensions = []
    measures = []

    for col_expr in select_columns:
        parsed = parse_column_expression(col_expr)

        if parsed["is_aggregate"]:
            # Determine measure type
            measure_type = "sum"
            expr_upper = parsed["expression"].upper()
            if "COUNT(" in expr_upper:
                measure_type = "count" if "COUNT(*)" in expr_upper else "count_distinct"
            elif "AVG(" in expr_upper:
                measure_type = "average"
            elif "MIN(" in expr_upper:
                measure_type = "min"
            elif "MAX(" in expr_upper:
                measure_type = "max"

            measures.append({
                "name": parsed["name"],
                "type": measure_type,
                "sql_field": parsed["name"],
                "label": parsed["name"].replace("_", " ").title(),
                "description": f"Auto-generated from: {parsed['expression'][:50]}",
            })
        else:
            dimensions.append({
                "name": parsed["name"],
                "type": parsed["type"],
                "label": parsed["name"].replace("_", " ").title(),
                "description": f"Dimension from SQL query",
            })

    # If no measures but we have group by, columns not in group by might be measures
    if not measures and group_by_columns:
        group_by_lower = [g.lower() for g in group_by_columns]
        new_dims = []
        for dim in dimensions:
            if dim["name"].lower() in group_by_lower:
                new_dims.append(dim)
            else:
                measures.append({
                    "name": dim["name"],
                    "type": "sum",
                    "sql_field": dim["name"],
                    "label": dim["name"].replace("_", " ").title(),
                    "description": "Inferred measure (not in GROUP BY)",
                })
        dimensions = new_dims

    return SQLParseResult(
        original_sql=sql,
        view_name=view_name,
        dimensions=dimensions,
        measures=measures,
        derived_table_sql=cleaned_sql,
    )


def format_sql_for_lookml(sql: str, indent: int = 6) -> str:
    """Format SQL for embedding in LookML derived_table."""
    lines = sql.strip().split('\n')
    ind = ' ' * indent
    return '\n'.join(f"{ind}{line}" for line in lines)


# Example usage and testing
if __name__ == "__main__":
    test_sql = """
    SELECT
        product_group,
        sub_product_group,
        COUNT(*) as customer_count,
        SUM(total_spend_amt) as total_spend,
        AVG(avg_txn_amt) as avg_transaction
    FROM project.dataset.custins_customer_insights_cardmember
    WHERE rpt_dt = '2024-01-01'
    GROUP BY product_group, sub_product_group
    ORDER BY total_spend DESC
    """

    result = parse_sql_to_lookml(test_sql)
    print(f"View name: {result.view_name}")
    print(f"Dimensions: {result.dimensions}")
    print(f"Measures: {result.measures}")
