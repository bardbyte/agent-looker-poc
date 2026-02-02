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
├── requirements.txt    # Dependencies
└── README.md           # This file
```

## Demo Flow

1. **Select table**: `custins_customer_insights_cardmember`
2. **See gaps**: Missing labels, descriptions identified
3. **Generate suggestions**: LLM suggests enrichments
4. **Review & approve**: Accept, edit, or reject per-column
5. **Generate LookML**: Create .view.lkml with enrichments
6. **Download**: Export the generated file

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
- Import → (Phase 2) load previous session

## Next Steps

| Phase | Work |
|-------|------|
| Phase 1 | Connect real MDM API ✅ |
| Phase 2 | Integrate SafeChain for real LLM suggestions |
| Phase 3 | Add Git PR creation, multi-table support |
