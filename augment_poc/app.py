"""
Semantic Enrichment PoC - Streamlit Application

A Data Steward Assistant for:
1. Table metadata enrichment via LLM suggestions
2. Gap analysis and approval workflow
3. LookML generation from enriched metadata
4. SQL to LookML conversion
"""

import streamlit as st
import json
from datetime import datetime
from typing import Dict, Optional

from models import (
    TableMetadata, ColumnMetadata, EnrichmentSuggestion,
    EnrichedColumn, GapType, ApprovalStatus, GapAnalysis
)
from mdm_client import MDMClient, analyze_gaps, get_mock_table
from enrichment_agent import EnrichmentAgent, EnrichmentResult
from lookml_generator import generate_view, generate_derived_table_view
from sql_parser import parse_sql_to_lookml


# ============================================================================
# Page Config
# ============================================================================

st.set_page_config(
    page_title="Semantic Enrichment PoC",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================================
# Session State Initialization
# ============================================================================

def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "table_metadata": None,
        "gap_analysis": None,
        "suggestions": [],
        "enriched_columns": {},
        "generated_lookml": None,
        "sql_parse_result": None,
        "sql_lookml": None,
        "use_mock": True,  # Start with mock data
        "agent": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ============================================================================
# Sidebar
# ============================================================================

def render_sidebar():
    """Render the sidebar with settings and info."""
    with st.sidebar:
        st.title("🔮 Semantic Enrichment")
        st.caption("Data Steward Assistant PoC")

        st.divider()

        # Mode toggle
        st.subheader("⚙️ Settings")
        st.session_state.use_mock = st.toggle(
            "Use Mock Data",
            value=st.session_state.use_mock,
            help="Toggle between mock data and real MDM API"
        )

        if not st.session_state.use_mock:
            st.info("🌐 Will fetch from MDM API")
        else:
            st.info("🧪 Using mock data for demo")

        st.divider()

        # Quick stats
        if st.session_state.table_metadata:
            st.subheader("📊 Current Table")
            table = st.session_state.table_metadata
            st.metric("Table", table.table_name[:25] + "...")
            st.metric("Columns", len(table.columns))

            if st.session_state.gap_analysis:
                gaps = st.session_state.gap_analysis
                st.metric("Completion", f"{gaps.completion_rate:.0f}%")

        st.divider()

        # Export/Import
        st.subheader("💾 Session")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📥 Export", use_container_width=True):
                export_session()
        with col2:
            if st.button("📤 Import", use_container_width=True):
                st.info("Upload JSON in main area")

        st.divider()

        # Info
        st.caption("Built with SafeChain + Streamlit")
        st.caption(f"Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}")


def export_session():
    """Export current session state to JSON."""
    export_data = {
        "timestamp": datetime.now().isoformat(),
        "table_name": st.session_state.table_metadata.table_name if st.session_state.table_metadata else None,
        "enriched_columns": {
            name: {
                "enriched_label": ec.enriched_label,
                "enriched_description": ec.enriched_description,
                "enriched_sensitivity": ec.enriched_sensitivity,
            }
            for name, ec in st.session_state.enriched_columns.items()
        },
        "generated_lookml": st.session_state.generated_lookml,
    }
    st.session_state.export_json = json.dumps(export_data, indent=2)


# ============================================================================
# Tab 1: Table Enrichment
# ============================================================================

def render_table_enrichment_tab():
    """Render the table enrichment workflow."""
    st.header("📊 Table Enrichment")
    st.caption("Fetch metadata, analyze gaps, and enrich with LLM suggestions")

    # Step 1: Table Selection
    with st.container():
        st.subheader("1️⃣ Select Table")

        col1, col2 = st.columns([3, 1])
        with col1:
            table_name = st.text_input(
                "Table Name",
                value="custins_customer_insights_cardmember",
                placeholder="Enter table name...",
                help="Enter the full table name to fetch from MDM"
            )
        with col2:
            st.write("")  # Spacer
            st.write("")
            fetch_btn = st.button("🔍 Fetch Metadata", type="primary", use_container_width=True)

        if fetch_btn and table_name:
            with st.spinner("Fetching table metadata..."):
                if st.session_state.use_mock:
                    table = get_mock_table(table_name)
                else:
                    client = MDMClient()
                    table = client.fetch_table_schema_sync(table_name)

                if table:
                    st.session_state.table_metadata = table
                    st.session_state.gap_analysis = analyze_gaps(table)
                    st.session_state.suggestions = []
                    st.session_state.enriched_columns = {}
                    st.success(f"✅ Loaded {len(table.columns)} columns")
                else:
                    st.error("❌ Table not found")

    # Step 2: Gap Analysis
    if st.session_state.table_metadata and st.session_state.gap_analysis:
        st.divider()
        render_gap_analysis()

        # Step 3: LLM Suggestions
        st.divider()
        render_suggestions_section()

        # Step 4: Column Editor
        st.divider()
        render_column_editor()

        # Step 5: Generate LookML
        st.divider()
        render_generate_lookml()


def render_gap_analysis():
    """Render gap analysis results."""
    st.subheader("2️⃣ Gap Analysis")

    gaps = st.session_state.gap_analysis
    table = st.session_state.table_metadata

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Columns", gaps.total_columns)
    with col2:
        st.metric("Missing Labels", gaps.missing_labels,
                 delta=f"-{gaps.missing_labels}" if gaps.missing_labels else None,
                 delta_color="inverse")
    with col3:
        st.metric("Missing Descriptions", gaps.missing_descriptions,
                 delta=f"-{gaps.missing_descriptions}" if gaps.missing_descriptions else None,
                 delta_color="inverse")
    with col4:
        st.metric("Completion Rate", f"{gaps.completion_rate:.0f}%")

    # Progress bar
    st.progress(gaps.completion_rate / 100)

    # Columns with gaps
    if gaps.gaps:
        with st.expander(f"🔍 View {len(gaps.gaps)} columns with gaps", expanded=False):
            for col_name, col_gaps in gaps.gaps.items():
                gap_icons = []
                if GapType.MISSING_LABEL in col_gaps:
                    gap_icons.append("🏷️ Label")
                if GapType.MISSING_DESCRIPTION in col_gaps:
                    gap_icons.append("📝 Description")
                if GapType.MISSING_SENSITIVITY in col_gaps:
                    gap_icons.append("🔒 Sensitivity")

                st.write(f"• **{col_name}**: {', '.join(gap_icons)}")


def render_suggestions_section():
    """Render LLM suggestions section."""
    st.subheader("3️⃣ LLM Suggestions")

    if not st.session_state.suggestions:
        if st.button("💡 Generate Suggestions", type="primary"):
            with st.spinner("Generating suggestions with LLM..."):
                agent = EnrichmentAgent(use_mock=st.session_state.use_mock)
                agent.initialize_sync()

                result = agent.generate_suggestions_sync(
                    st.session_state.table_metadata,
                    st.session_state.gap_analysis
                )

                if result.error:
                    st.error(f"Error: {result.error}")
                else:
                    st.session_state.suggestions = result.suggestions
                    st.success(f"✅ Generated {len(result.suggestions)} suggestions")
                    st.rerun()
    else:
        # Show suggestions
        st.write(f"**{len(st.session_state.suggestions)} suggestions available**")

        # Bulk actions
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("✅ Accept All", use_container_width=True):
                accept_all_suggestions()
                st.rerun()
        with col2:
            if st.button("❌ Reject All", use_container_width=True):
                st.session_state.suggestions = []
                st.rerun()
        with col3:
            if st.button("🔄 Regenerate", use_container_width=True):
                st.session_state.suggestions = []
                st.rerun()

        # Individual suggestions
        for i, suggestion in enumerate(st.session_state.suggestions):
            with st.expander(f"💡 {suggestion.column_name} - {suggestion.gap_type.value}", expanded=False):
                col1, col2 = st.columns(2)

                with col1:
                    st.write("**Current:**")
                    col = next((c for c in st.session_state.table_metadata.columns
                               if c.attribute_name == suggestion.column_name), None)
                    if col:
                        st.write(f"Label: `{col.business_name or 'None'}`")
                        st.write(f"Description: `{col.attribute_desc or 'None'}`")

                with col2:
                    st.write("**Suggested:**")
                    if suggestion.suggested_label:
                        st.write(f"Label: `{suggestion.suggested_label}`")
                    if suggestion.suggested_description:
                        st.write(f"Description: `{suggestion.suggested_description}`")
                    if suggestion.suggested_sensitivity:
                        st.write(f"Sensitivity: `{suggestion.suggested_sensitivity}`")

                st.caption(f"Confidence: {suggestion.confidence:.0%} | {suggestion.reasoning}")

                # Actions
                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    if st.button("✅ Accept", key=f"accept_{i}"):
                        accept_suggestion(suggestion)
                        st.rerun()
                with action_col2:
                    if st.button("❌ Reject", key=f"reject_{i}"):
                        st.session_state.suggestions.remove(suggestion)
                        st.rerun()


def accept_suggestion(suggestion: EnrichmentSuggestion):
    """Accept a single suggestion."""
    col_name = suggestion.column_name
    col = next((c for c in st.session_state.table_metadata.columns
               if c.attribute_name == col_name), None)

    if col:
        if col_name not in st.session_state.enriched_columns:
            st.session_state.enriched_columns[col_name] = EnrichedColumn(original=col)

        enriched = st.session_state.enriched_columns[col_name]

        if suggestion.suggested_label:
            enriched.enriched_label = suggestion.suggested_label
        if suggestion.suggested_description:
            enriched.enriched_description = suggestion.suggested_description
        if suggestion.suggested_sensitivity:
            enriched.enriched_sensitivity = suggestion.suggested_sensitivity

    # Remove from suggestions
    if suggestion in st.session_state.suggestions:
        st.session_state.suggestions.remove(suggestion)


def accept_all_suggestions():
    """Accept all pending suggestions."""
    for suggestion in list(st.session_state.suggestions):
        accept_suggestion(suggestion)


def render_column_editor():
    """Render the column-by-column editor."""
    st.subheader("4️⃣ Column Editor")

    if not st.session_state.table_metadata:
        return

    # Filter options
    filter_col1, filter_col2 = st.columns([2, 2])
    with filter_col1:
        show_only_gaps = st.checkbox("Show only columns with gaps", value=True)
    with filter_col2:
        search = st.text_input("🔍 Search columns", placeholder="Filter by name...")

    # Column cards
    columns = st.session_state.table_metadata.columns
    if show_only_gaps:
        columns = [c for c in columns if c.attribute_name in st.session_state.gap_analysis.gaps]
    if search:
        columns = [c for c in columns if search.lower() in c.attribute_name.lower()]

    for col in columns:
        enriched = st.session_state.enriched_columns.get(col.attribute_name)
        has_enrichment = enriched is not None

        # Card header with status
        status_icon = "✅" if has_enrichment else "⚠️" if col.attribute_name in st.session_state.gap_analysis.gaps else "✓"

        with st.expander(f"{status_icon} {col.attribute_name} ({col.attribute_type})", expanded=False):
            edit_col1, edit_col2 = st.columns(2)

            with edit_col1:
                st.write("**Original Values:**")
                st.text(f"Label: {col.business_name or 'None'}")
                st.text(f"Description: {col.attribute_desc or 'None'}")
                st.text(f"Sensitivity: {col.sensitivity_details or 'None'}")

            with edit_col2:
                st.write("**Enriched Values:**")

                # Editable fields
                new_label = st.text_input(
                    "Label",
                    value=enriched.enriched_label if enriched else (col.business_name or ""),
                    key=f"label_{col.attribute_name}"
                )
                new_desc = st.text_area(
                    "Description",
                    value=enriched.enriched_description if enriched else (col.attribute_desc or ""),
                    key=f"desc_{col.attribute_name}",
                    height=80
                )
                new_sens = st.selectbox(
                    "Sensitivity",
                    options=["", "CM11", "CM15", "NGBD-SDE-CM11", "NGBD-SDE-CM15"],
                    index=0,
                    key=f"sens_{col.attribute_name}"
                )

                # Save changes
                if st.button("💾 Save", key=f"save_{col.attribute_name}"):
                    if col.attribute_name not in st.session_state.enriched_columns:
                        st.session_state.enriched_columns[col.attribute_name] = EnrichedColumn(original=col)

                    ec = st.session_state.enriched_columns[col.attribute_name]
                    ec.enriched_label = new_label if new_label != col.business_name else None
                    ec.enriched_description = new_desc if new_desc != col.attribute_desc else None
                    ec.enriched_sensitivity = new_sens if new_sens else None
                    st.success("Saved!")


def render_generate_lookml():
    """Render LookML generation section."""
    st.subheader("5️⃣ Generate LookML")

    if not st.session_state.table_metadata:
        st.info("Load a table first")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        include_measures = st.checkbox("Auto-generate measures", value=True)
    with col2:
        if st.button("🚀 Generate LookML", type="primary"):
            lookml = generate_view(
                st.session_state.table_metadata,
                st.session_state.enriched_columns,
                include_measures=include_measures
            )
            st.session_state.generated_lookml = lookml
            st.success("✅ LookML generated!")

    if st.session_state.generated_lookml:
        st.code(st.session_state.generated_lookml, language="ruby")

        st.download_button(
            "📥 Download .view.lkml",
            data=st.session_state.generated_lookml,
            file_name=f"{st.session_state.table_metadata.table_name}.view.lkml",
            mime="text/plain"
        )


# ============================================================================
# Tab 2: SQL to LookML
# ============================================================================

def render_sql_to_lookml_tab():
    """Render the SQL to LookML converter."""
    st.header("🔄 SQL → LookML Converter")
    st.caption("Paste a SQL query and convert it to a LookML derived table view")

    # SQL Input
    sql_input = st.text_area(
        "SQL Query",
        height=200,
        placeholder="""SELECT
    product_group,
    sub_product_group,
    COUNT(*) as customer_count,
    SUM(total_spend_amt) as total_spend,
    AVG(avg_txn_amt) as avg_transaction
FROM project.dataset.custins_customer_insights_cardmember
WHERE rpt_dt = '2024-01-01'
GROUP BY product_group, sub_product_group
ORDER BY total_spend DESC""",
        help="Paste your SQL query here. The parser will extract dimensions and measures."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        view_name = st.text_input("View Name", value="", placeholder="Auto-detect from SQL")
    with col2:
        st.write("")
        st.write("")
        if st.button("🔄 Parse & Convert", type="primary"):
            if sql_input.strip():
                result = parse_sql_to_lookml(sql_input, view_name or None)
                st.session_state.sql_parse_result = result

                lookml = generate_derived_table_view(
                    result.view_name,
                    result.derived_table_sql,
                    result.dimensions,
                    result.measures
                )
                st.session_state.sql_lookml = lookml
                st.success("✅ Parsed successfully!")
            else:
                st.warning("Please enter a SQL query")

    # Results
    if st.session_state.sql_parse_result:
        result = st.session_state.sql_parse_result

        st.divider()
        st.subheader("📊 Parse Results")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("View Name", result.view_name)
        with col2:
            st.metric("Dimensions", len(result.dimensions))
        with col3:
            st.metric("Measures", len(result.measures))

        # Show extracted fields
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            with st.expander("📐 Dimensions", expanded=True):
                for dim in result.dimensions:
                    st.write(f"• **{dim['name']}** ({dim['type']})")

        with exp_col2:
            with st.expander("📏 Measures", expanded=True):
                for meas in result.measures:
                    st.write(f"• **{meas['name']}** ({meas['type']})")

    # Generated LookML
    if st.session_state.sql_lookml:
        st.divider()
        st.subheader("📄 Generated LookML")

        st.code(st.session_state.sql_lookml, language="ruby")

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download .view.lkml",
                data=st.session_state.sql_lookml,
                file_name=f"{st.session_state.sql_parse_result.view_name}.view.lkml",
                mime="text/plain"
            )
        with col2:
            if st.button("📋 Copy to Clipboard"):
                st.code(st.session_state.sql_lookml)
                st.info("Code shown above - copy manually")


# ============================================================================
# Tab 3: Output & Export
# ============================================================================

def render_output_tab():
    """Render the output preview and export tab."""
    st.header("📁 Generated Output")

    # Sub-tabs for different outputs
    output_tab1, output_tab2, output_tab3 = st.tabs([
        "📊 Table LookML",
        "🔄 SQL LookML",
        "📦 Export All"
    ])

    with output_tab1:
        if st.session_state.generated_lookml:
            st.subheader(f"View: {st.session_state.table_metadata.table_name}")

            # Stats
            if st.session_state.gap_analysis:
                gaps = st.session_state.gap_analysis
                enriched_count = len(st.session_state.enriched_columns)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Original Gaps", gaps.columns_with_gaps)
                with col2:
                    st.metric("Enriched", enriched_count)
                with col3:
                    remaining = gaps.columns_with_gaps - enriched_count
                    st.metric("Remaining", max(0, remaining))

            st.code(st.session_state.generated_lookml, language="ruby")

            st.download_button(
                "📥 Download .view.lkml",
                data=st.session_state.generated_lookml,
                file_name=f"{st.session_state.table_metadata.table_name}.view.lkml",
                mime="text/plain"
            )
        else:
            st.info("No table LookML generated yet. Go to Table Enrichment tab.")

    with output_tab2:
        if st.session_state.sql_lookml:
            st.subheader(f"View: {st.session_state.sql_parse_result.view_name}")
            st.code(st.session_state.sql_lookml, language="ruby")

            st.download_button(
                "📥 Download .view.lkml",
                data=st.session_state.sql_lookml,
                file_name=f"{st.session_state.sql_parse_result.view_name}.view.lkml",
                mime="text/plain"
            )
        else:
            st.info("No SQL LookML generated yet. Go to SQL → LookML tab.")

    with output_tab3:
        st.subheader("📦 Export Session")

        # Session summary
        st.write("**Session Contents:**")
        items = []
        if st.session_state.table_metadata:
            items.append(f"• Table: {st.session_state.table_metadata.table_name}")
        if st.session_state.enriched_columns:
            items.append(f"• Enriched columns: {len(st.session_state.enriched_columns)}")
        if st.session_state.generated_lookml:
            items.append("• Table LookML: ✅")
        if st.session_state.sql_lookml:
            items.append("• SQL LookML: ✅")

        if items:
            for item in items:
                st.write(item)
        else:
            st.info("No data to export yet")

        st.divider()

        # Export options
        if st.button("📦 Generate Export Package"):
            export_session()
            if hasattr(st.session_state, 'export_json'):
                st.download_button(
                    "📥 Download session.json",
                    data=st.session_state.export_json,
                    file_name="enrichment_session.json",
                    mime="application/json"
                )

        # Git PR placeholder
        st.divider()
        st.subheader("🔗 Git Integration")
        st.info("📌 **Phase 2**: Create PR with generated LookML files")
        st.button("Create Pull Request", disabled=True)


# ============================================================================
# Main App
# ============================================================================

def main():
    """Main application entry point."""
    render_sidebar()

    # Main content tabs
    tab1, tab2, tab3 = st.tabs([
        "📊 Table Enrichment",
        "🔄 SQL → LookML",
        "📁 Generated Output"
    ])

    with tab1:
        render_table_enrichment_tab()

    with tab2:
        render_sql_to_lookml_tab()

    with tab3:
        render_output_tab()


if __name__ == "__main__":
    main()
