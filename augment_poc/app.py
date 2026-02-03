"""
Semantic Enrichment PoC - Streamlit Application

A Data Steward Assistant for:
1. Table metadata enrichment via LLM suggestions
2. Gap analysis and approval workflow
3. LookML generation from enriched metadata
4. SQL to LookML conversion
5. Git integration for PR creation
"""

import streamlit as st
import json
import os
from datetime import datetime
from typing import Dict, Optional, List

from models import (
    TableMetadata, ColumnMetadata, EnrichmentSuggestion,
    EnrichedColumn, GapType, ApprovalStatus, GapAnalysis
)
from mdm_client import MDMClient, analyze_gaps, get_mock_table
from enrichment_agent import EnrichmentAgent, EnrichmentResult
from lookml_generator import generate_view, generate_derived_table_view
from sql_parser import parse_sql_to_lookml
from git_integration import GitConfig, LookMLDeployer, MockGitDeployer, PRResult, get_deployer


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
        # Git integration
        "git_repo_url": os.getenv("LOOKER_GIT_REPO_URL", ""),
        "github_token": os.getenv("GITHUB_TOKEN", ""),
        "git_default_branch": os.getenv("LOOKER_GIT_DEFAULT_BRANCH", "main"),
        "git_views_path": os.getenv("LOOKER_GIT_VIEWS_PATH", "views"),
        "use_mock_git": True,  # Start with mock Git
        "pr_history": [],  # Track created PRs
        "last_pr_result": None,
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
        st.subheader("⚙️ Data Settings")
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

        # Git Settings
        st.subheader("🔗 Git Settings")
        st.session_state.use_mock_git = st.toggle(
            "Use Mock Git",
            value=st.session_state.use_mock_git,
            help="Toggle between mock Git and real GitHub integration"
        )

        if not st.session_state.use_mock_git:
            with st.expander("Configure Git", expanded=False):
                st.session_state.git_repo_url = st.text_input(
                    "Git Repo URL",
                    value=st.session_state.git_repo_url,
                    placeholder="https://github.com/org/looker-models.git",
                    type="default"
                )
                st.session_state.github_token = st.text_input(
                    "GitHub Token",
                    value=st.session_state.github_token,
                    type="password",
                    help="Personal access token with repo permissions"
                )
                st.session_state.git_default_branch = st.text_input(
                    "Default Branch",
                    value=st.session_state.git_default_branch,
                )
                st.session_state.git_views_path = st.text_input(
                    "Views Path",
                    value=st.session_state.git_views_path,
                    help="Path within repo for view files"
                )

            if st.session_state.git_repo_url and st.session_state.github_token:
                st.success("✅ Git configured")
            else:
                st.warning("⚠️ Configure Git above")
        else:
            st.info("🧪 Using mock Git for demo")

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

        # PR History
        if st.session_state.pr_history:
            st.divider()
            st.subheader("📋 PR History")
            for pr in st.session_state.pr_history[-3:]:  # Show last 3
                st.write(f"• [{pr['table']}]({pr['url']})")

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

        # Git PR Creation
        st.divider()
        render_git_integration()


# ============================================================================
# Git Integration
# ============================================================================

def get_enrichment_summary() -> Dict:
    """Build enrichment summary for PR description."""
    summary = {
        "total_columns": 0,
        "labels_added": 0,
        "descriptions_added": 0,
        "sensitivity_tags": 0,
    }

    if st.session_state.table_metadata:
        summary["total_columns"] = len(st.session_state.table_metadata.columns)

    for col_name, enriched in st.session_state.enriched_columns.items():
        if enriched.enriched_label:
            summary["labels_added"] += 1
        if enriched.enriched_description:
            summary["descriptions_added"] += 1
        if enriched.enriched_sensitivity:
            summary["sensitivity_tags"] += 1

    return summary


def render_git_integration():
    """Render Git integration section for PR creation."""
    st.subheader("🔗 Git Integration")

    # Check if we have content to deploy
    has_table_lookml = st.session_state.generated_lookml is not None
    has_sql_lookml = st.session_state.sql_lookml is not None

    if not has_table_lookml and not has_sql_lookml:
        st.info("Generate LookML first to enable Git integration")
        return

    # Show what can be deployed
    st.write("**Available for deployment:**")
    deploy_options = []

    if has_table_lookml:
        table_name = st.session_state.table_metadata.table_name
        deploy_options.append(("table", table_name, st.session_state.generated_lookml))
        st.write(f"✅ Table view: `{table_name}.view.lkml`")

    if has_sql_lookml:
        sql_view_name = st.session_state.sql_parse_result.view_name
        deploy_options.append(("sql", sql_view_name, st.session_state.sql_lookml))
        st.write(f"✅ SQL view: `{sql_view_name}.view.lkml`")

    st.divider()

    # Deployment form
    with st.form("git_deploy_form"):
        st.write("**Create Pull Request**")

        # Select what to deploy
        selected_views = st.multiselect(
            "Select views to deploy",
            options=[opt[1] for opt in deploy_options],
            default=[opt[1] for opt in deploy_options],
            help="Choose which generated views to include in the PR"
        )

        col1, col2 = st.columns(2)
        with col1:
            create_draft = st.checkbox("Create as draft PR", value=True)
        with col2:
            add_labels = st.checkbox("Add labels", value=True)

        # Custom PR title (optional)
        custom_title = st.text_input(
            "Custom PR title (optional)",
            placeholder="Leave empty for auto-generated title"
        )

        # Reviewers (optional)
        reviewers = st.text_input(
            "Reviewers (comma-separated GitHub usernames)",
            placeholder="user1, user2"
        )

        submitted = st.form_submit_button("🚀 Create Pull Request", type="primary")

        if submitted:
            if not selected_views:
                st.error("Please select at least one view to deploy")
            else:
                create_pull_request(
                    deploy_options,
                    selected_views,
                    create_draft,
                    add_labels,
                    custom_title,
                    reviewers
                )

    # Show last PR result
    if st.session_state.last_pr_result:
        st.divider()
        render_pr_result(st.session_state.last_pr_result)


def create_pull_request(
    deploy_options: list,
    selected_views: list,
    create_draft: bool,
    add_labels: bool,
    custom_title: str,
    reviewers: str
):
    """Create a Pull Request with the selected views."""
    with st.spinner("Creating Pull Request..."):
        # Get or create deployer
        if st.session_state.use_mock_git:
            deployer = MockGitDeployer()
        else:
            config = GitConfig(
                repo_url=st.session_state.git_repo_url,
                default_branch=st.session_state.git_default_branch,
                views_path=st.session_state.git_views_path,
                github_token=st.session_state.github_token,
            )
            deployer = LookMLDeployer(config)

        # Deploy each selected view
        results = []
        for opt_type, view_name, lookml_content in deploy_options:
            if view_name not in selected_views:
                continue

            summary = get_enrichment_summary() if opt_type == "table" else {
                "total_columns": len(st.session_state.sql_parse_result.dimensions) +
                                len(st.session_state.sql_parse_result.measures),
                "labels_added": 0,
                "descriptions_added": 0,
                "sensitivity_tags": 0,
            }

            labels = ["ai-enrichment", "lookml"] if add_labels else None
            reviewer_list = [r.strip() for r in reviewers.split(",") if r.strip()] if reviewers else None

            result = deployer.deploy_lookml(
                table_name=view_name,
                lookml_content=lookml_content,
                enrichment_summary=summary,
                create_pr=True,
                draft=create_draft,
                labels=labels,
            )
            results.append((view_name, result))

        # Store results
        if results:
            # Use first result as the main result
            view_name, result = results[0]
            st.session_state.last_pr_result = {
                "view_name": view_name,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }

            # Add to history
            if result.success and result.pr_url:
                st.session_state.pr_history.append({
                    "table": view_name,
                    "url": result.pr_url,
                    "timestamp": datetime.now().isoformat(),
                })

            st.rerun()


def render_pr_result(pr_data: Dict):
    """Render the result of PR creation."""
    result: PRResult = pr_data["result"]
    view_name = pr_data["view_name"]

    if result.success:
        st.success(f"✅ Pull Request created for `{view_name}`!")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Branch", result.branch_name or "N/A")
        with col2:
            st.metric("PR #", result.pr_number or "N/A")

        if result.pr_url:
            st.markdown(f"**🔗 [View Pull Request]({result.pr_url})**")

        if result.files_changed:
            with st.expander("Files changed", expanded=False):
                for f in result.files_changed:
                    st.code(f)

        # Show PR body preview
        if st.session_state.use_mock_git:
            with st.expander("📝 PR Preview (Mock)", expanded=False):
                st.markdown(f"""
## Summary

AI-powered metadata enrichment for `{view_name}`.

### Enrichment Statistics

| Metric | Count |
|--------|-------|
| Labels Added | {get_enrichment_summary().get('labels_added', 0)} |
| Descriptions Added | {get_enrichment_summary().get('descriptions_added', 0)} |
| Sensitivity Tags | {get_enrichment_summary().get('sensitivity_tags', 0)} |

### Review Checklist

- [ ] Labels are business-friendly and accurate
- [ ] Descriptions clearly explain column purpose
- [ ] Sensitivity classifications are correct

---
🤖 Generated by Semantic Enrichment Agent
                """)

    else:
        st.error(f"❌ Failed to create PR: {result.error}")


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
