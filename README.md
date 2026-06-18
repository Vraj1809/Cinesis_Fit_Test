# Cinesis Good Fit Test

## Architecture & Implementation
This solution mimics a production-grade dispatch pipeline, heavily prioritizing data validation, modularity, and explicit handling of edge cases.

### Part A — Extraction (`extract.py`)
Profiles are extracted using `claude-3-5-sonnet-20240620` via the official Anthropic Python SDK. 
* **Deterministic Configuration:** Uses `temperature=0` alongside structured JSON extraction with strict validation for reliable programmatic ingestion.
* **Safety & Resilience:** The SDK natively handles retries (e.g., HTTP 529s). Extracted JSON undergoes a strict `_validate_profile` bounds check (verifying valid coordinate boundaries and positive weight limits) to prevent silent hallucinations from corrupting downstream routing.

### Part B — Ranking (`rank.py`)
The pipeline ingests the load board dynamically directly from the `.xlsx` file utilizing `openpyxl`.

**Filtering & Evaluation Workflow:**
1. **Completeness:** Loads with missing prices or destinations are explicitly excluded (effective rates are mathematically uncomputable).
2. **Equipment Match:** Restricted to the extracted equipment constraints.
3. **Weight Limits:** Assumes an unknown weight (`None`) is a critical safety liability and explicitly excludes them pending manual human dispatch confirmation. Loads over the extracted capacity are rejected.
4. **Effective Rate Floor:** `price ÷ (dh_to_origin + loaded_miles + dh_home) ≥ driver_minimum`.

**The Trap Load Rejected:**
A high-paying load (`L04` — Plano → Memphis) is rejected on two strict bounds: the equipment is a Van (driver operates Hotshots) and the weight (38,000 lb) crushes the driver's inferred 16,500 lb hotshot capacity limit.

**NOTE**
The driver never explicitly stated weight capacity.
A capacity of approximately 16,500 lb was inferred from the driver's stated
equipment type ("hotshot gooseneck") using common industry operating limits.
Loads exceeding this inferred capacity were treated as ineligible.
The Ranking Script is loading data from the "Loads" sheet and the transcript from "Sample Conversation" sheet from the Uploaded Excel Sheet
If one wishes to test the code on new data they can do so by replacing the content of above mentioned sheets

*Run `python rank.py` to view the evaluated board and final rankings.*
