# Semantic Enrichment PoC

A Data Steward Assistant for enriching metadata and generating LookML from enterprise data catalogs.

## Features

| Feature | Description |
|---------|-------------|
| **Table Lookup** | Fetch metadata from MDM API |
| **Gap Analysis** | Identify missing labels, descriptions, sensitivity |
| **LLM Suggestions** | Generate enrichment suggestions via SafeChain |
| **Approval Workflow** | Accept, edit, or reject suggestions per-column |
| **LookML Generation** | Create valid .view.lkml from enriched metadata |
| **SQL → LookML** | Convert SQL queries to LookML derived tables |
| **Git Integration** | Create PRs with generated LookML directly |
| **Export** | Download generated LookML files |

## Quick Start

```bash
# Navigate to the poc directory
cd augment_poc

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

## Architecture

```
augment_poc/
├── app.py              # Main Streamlit application
├── models.py           # Pydantic data models
├── mdm_client.py       # MDM API client + mock data
├── enrichment_agent.py # SafeChain LLM agent
├── lookml_generator.py # LookML generation
├── sql_parser.py       # SQL to LookML parsing
├── git_integration.py  # Git operations & PR creation
├── requirements.txt    # Dependencies
└── README.md           # This file
```

## Demo Flow

1. **Select table**: `custins_customer_insights_cardmember`
2. **See gaps**: Missing labels, descriptions identified
3. **Generate suggestions**: LLM suggests enrichments
4. **Review & approve**: Accept, edit, or reject per-column
5. **Generate LookML**: Create .view.lkml with enrichments
6. **Create PR**: Push to Git and create Pull Request
7. **Download**: Export the generated file

## Tabs

### Tab 1: Table Enrichment
- Fetch from MDM API (or use mock data)
- Gap analysis with metrics
- LLM-powered suggestions
- Per-column editing
- Bulk accept/reject

### Tab 2: SQL → LookML
- Paste SQL query
- Auto-detect dimensions (GROUP BY columns)
- Auto-detect measures (SUM, COUNT, AVG)
- Generate derived table LookML

### Tab 3: Generated Output
- Preview all generated LookML
- Download .view.lkml files
- Export session as JSON
- **Create Pull Requests** to Looker Git repo

## Git Integration

### Configuration

Set environment variables or configure in sidebar:

```bash
export LOOKER_GIT_REPO_URL="https://github.com/org/looker-models.git"
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
export LOOKER_GIT_DEFAULT_BRANCH="main"
export LOOKER_GIT_VIEWS_PATH="views"
```

### PR Creation Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Generate    │───▶│ Clone Repo  │───▶│ Create      │───▶│ Create PR   │
│ LookML      │    │ & Branch    │    │ Commit      │    │ on GitHub   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### PR Features
- Auto-generated branch names: `enrichment/{table}/{timestamp}`
- Rich PR descriptions with enrichment statistics
- Adds labels: `ai-enrichment`, `lookml`
- Support for draft PRs
- Request reviewers automatically

### Mock vs Real Git

Toggle "Use Mock Git" in sidebar:
- **Mock Mode**: Simulates PR creation (for demos)
- **Real Mode**: Creates actual PRs on GitHub

## Mock vs Real Mode

Toggle "Use Mock Data" in sidebar:
- **Mock Mode**: Uses sample data, no API calls
- **Real Mode**: Fetches from MDM API, uses SafeChain for LLM

## Connecting to Real MDM API

The MDM API endpoint requires no authentication:
```
GET https://lumimdmapi-guse4.aexp.com/api/v1/ngbd/mdm-api/datasets/schemas?tableName={table}
```

Toggle off "Use Mock Data" to fetch from real API.

## Connecting to SafeChain LLM

1. Install SafeChain dependencies (uncomment in requirements.txt)
2. Configure `.env` with model credentials
3. Toggle off "Use Mock Data"

## Session Persistence

- All state lives in Streamlit session_state
- Export → saves to JSON file
- PR history tracked in session

## Development Phases

| Phase | Status | Work |
|-------|--------|------|
| Phase 1 | ✅ | MDM API integration, Gap analysis, LLM suggestions |
| Phase 2 | ✅ | Git integration, PR creation |
| Phase 3 | 🔜 | Looker SDK validation, multi-table batch processing |

## Environment Variables

```bash
# MDM API (no auth required)
# No configuration needed

# SafeChain LLM
MODEL_ID=gemini-pro

# Git Integration
LOOKER_GIT_REPO_URL=https://github.com/org/looker-models.git
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
LOOKER_GIT_DEFAULT_BRANCH=main
LOOKER_GIT_VIEWS_PATH=views
```
