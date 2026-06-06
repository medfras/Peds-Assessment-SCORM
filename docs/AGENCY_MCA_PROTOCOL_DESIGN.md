# Agency / MCA / Protocol / License-Level Architecture

**Last reviewed:** 2026-04-19  
**Status:** Current implementation — includes known gaps and planned fixes

---

## Changelog

| Date | Change |
|---|---|
| 2026-04-19 | Initial document — full architecture audit |
| 2026-04-19 | Gap 1 (debrief scoring cap) fixed; table updated |
| 2026-04-19 | Gap 2 (MCA not live-updated on member rows) fixed; table updated |
| 2026-04-19 | Gap 4 (`scenario_engine.list_agencies()`) removed; Gap 5 (`_MCA_STATE_DIR`) now auto-populated from `mca_config.json` |

---

## Glossary

| Term | Definition |
|---|---|
| **MCA** | Medical Control Authority — the regional body that governs EMS protocol scope and authorizes optional BLS expansions beyond the state base |
| **BLS expansion** | A skill or medication that is not in default EMT scope but can be authorized by an MCA (e.g., epinephrine draw-up IM, CPAP for BLS) |
| **Provider level** | The EMS license level of a student: MFR < EMT < AEMT < Paramedic |
| **Agency ceiling** | The maximum provider level a given agency's members may operate at (`provider_levels.primary` in agency config) |
| **Effective level** | `min(student_level, agency_ceiling)` — the level actually applied during a session |
| **Protocol** | A clinical guideline file under `app/protocols/` that defines scope, interventions, and scoring criteria for a condition |
| **Medication monograph** | A drug reference file under `MI/09_Medications/` used to inject dosing, six-rights, and administration steps into the AI prompt |
| **Open-join agency** | A generic agency with no join code; students select it during registration by agency ID (`is_open_join = true`) |
| **Private agency** | An agency requiring a join code; configured for a specific real-world department |
| **JSONB config** | The `Agency.config` database column — the live runtime source for all clinical configuration after initial seeding |
| **adapt_scenario_to_context()** | The function that applies agency/MCA/level context to a raw scenario before a session starts |

---

## 1. Overview

The app is multi-tenant by agency. Every user belongs to one or more agencies. An agency's configuration — its MCA affiliation, service type, equipment, provider level ceiling, and BLS expansion authorizations — drives what protocols and interventions are available during a scenario session.

### Resolution chain

```
Agency JSON file (seed_agency.json, generic_*.json)
    │
    │ startup: _seed_open_agencies() / _seed_agency_configs()
    ▼
Agency.config (JSONB in DB)  ← live source; updated via PUT /api/agencies/{id}/config
    │
    │ registration / join: _resolve_member_mca(), _resolve_member_provider_level()
    ▼
AgencyMember.mca + AgencyMember.provider_level  ← capped to agency ceiling at join time
    │
    │ session start
    ▼
SimSession.mca + SimSession.provider_level  ← frozen for session lifetime
    │
    │ scenario load: adapt_scenario_to_context()
    ▼
Protocol selected + BLS expansions resolved + out_of_scope_bls updated
    │
    │ AI pipeline: _build_system_prompt() / evaluate_and_generate_debrief()
    ▼
Effective level = _effective_level(student_level, agency_ceiling)
    │
    ▼
AI system prompt: scoped interventions, partner level, scoring rubric
```

### MCA substitution sub-chain

```
Session MCA  ──▶  try protocols/{session_mca}/{section}/{file}.json
                        │
                        │ not found
                        ▼
                  fall back to protocols/MI/{section}/{file}.json
```

---

## 2. Data Model

### Agency

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | String (PK) | No | UUID for private agencies; stable ID for open-join/seed agencies |
| `name` | String | No | Display name shown in UI |
| `agency_join_code` | String (unique) | **Yes** | NULL for open-join agencies; required for private agencies |
| `agency_file` | String | Yes | File stem used for config seeding. Unused at runtime after initial seed. |
| `is_active` | Boolean | No | Default `true`. Inactive agencies block login. |
| `is_open_join` | Boolean | No | Default `false`. `true` = joinable without a code. |
| `config` | JSONB | Yes | Full clinical config. NULL until seeded. Runtime reads exclusively from here. |
| `narrative_required` | Boolean | No | Default `false`. Agency-level narrative requirement flag. |
| `created_at` | DateTime | — | Auto |

### AgencyMember

| Column | Type | Notes |
|---|---|---|
| `user_id` | String (FK) | |
| `agency_id` | String (FK) | |
| `role` | String | `student` \| `instructor` \| `admin` |
| `provider_level` | String | Capped to agency ceiling at join time |
| `mca` | String | Always matches agency config MCA — never user-selected |
| `joined_at` | DateTime | |

Unique constraint: `(user_id, agency_id)` — one membership per user per agency; unlimited total memberships.

### SimSession

Stores `provider_level` and `mca` copied from `AgencyMember` at session start. These are **frozen** — changes to agency config or membership do not affect active sessions.

---

## 3. Agency Types

### Private agency
- Has an `agency_join_code`; `is_open_join = false`
- Created via superuser API or startup seed (`.env` `SEED_AGENCY_*` vars)
- Full clinical config — MCA, equipment, SOPs, training certs, BLS expansions
- Imposes a provider level ceiling (`provider_levels.primary`)

### Open-join generic agencies (5 built-in)
- `agency_join_code = NULL`; `is_open_join = true`
- No join code required — users select by agency ID during registration
- `provider_levels.primary = "Paramedic"` — no ceiling; student operates at self-reported license level
- `mca = "mi_base"` — base Michigan protocols, no BLS expansions
- Seeded automatically at every startup via `_seed_open_agencies()`

| ID | Display | Transport | Fire |
|---|---|---|---|
| `generic_ems_transport` | EMS — Transport | Yes | No |
| `generic_ems_nontransport` | EMS — Non-Transport | No | No |
| `generic_fire` | Fire — Non-EMS | No | Yes |
| `generic_fire_ems_transport` | Fire-EMS — Transport | Yes | Yes |
| `generic_fire_ems_nontransport` | Fire-EMS — Non-Transport | No | Yes |

---

## 4. MCA System

A Medical Control Authority (MCA) is the regional body that governs EMS protocol scope. In Michigan, the MDHHS publishes state base protocols (`MI/`). Each MCA can authorize optional BLS expansions on top of the base.

### mca_config.json structure

```json
{
  "mcas": [
    { "id": "mi_base",        "bls_expansions": [] },
    { "id": "mi_wmrmcc_kent", "bls_expansions": [
        "epi_drawup_im", "cpap_bls", "i_gel_bls",
        "ondansetron_emt", "glucometer_mfr"
    ]}
  ]
}
```

### MCA resolution — priority order

```
1. Agency.config["mca"]          ← authoritative; always wins
2. settings.default_mca          ← "mi_base"; fallback when agency config absent
```

`_resolve_member_mca()` ignores any user-requested MCA and always returns the agency's configured MCA. A user cannot self-select an MCA outside their agency.

### BLS expansion scope adaptation

`adapt_scenario_to_context()` runs at every session start:

```
For each scenario intervention with "required_expansion": "<key>":
    if key IN session MCA's bls_expansions:
        within_bls_scope = true   (no change)
    else:
        within_bls_scope = false
        expansion_not_selected = true
        entry added to protocol_config.out_of_scope_bls
```

Resolved expansions are written to `adapted["mca_expansions"]` for the AI prompt.

Generic agencies have `mca = "mi_base"` with **no expansions** — by design. A scenario requiring `cpap_bls` will be marked out-of-scope for all generic agency students. Expansions must be explicitly authorized at the MCA level.

→ *See §12 for the full scope decision matrix.*  
→ *See §9, Gap 2 for the known gap around live MCA updates.*

---

## 5. Provider Level System

### Level hierarchy

```
MFR (0)  <  EMT (1)  <  AEMT (2)  <  Paramedic (3)
```

### Ceiling enforcement

`_resolve_member_provider_level(requested_level, agency_config)`:
- Reads `agency_config["provider_levels"]["primary"]` as the ceiling
- Returns `min(requested, ceiling)` by rank index
- Applied at: registration, agency join, admin member update, startup migration (`_migrate_member_scope`)
- Default ceiling when field is absent: `"Paramedic"` (unrestricted — used by all generic agencies)

### Where the cap is applied across the AI pipeline

| Stage | Cap applied | Notes |
|---|---|---|
| Membership creation/update | **Yes** | `_resolve_member_provider_level()` |
| JWT token | No | Embeds membership level as-is |
| Session start | No | Copies from token |
| `_build_system_prompt()` | **Yes** | `_effective_level(level, agency_max_level)` |
| `evaluate_and_generate_debrief()` | **Yes** *(fixed 2026-04-19)* | Same call — applied before scoring rubric |

### Partner level

The EMS partner persona in the AI system prompt is explicitly constrained to the student's **effective** provider level:

> *"The partner operates at exactly {level_display} scope — the same level as the student. They cannot perform any skill or intervention the student cannot."*

### Test cases

| Student level | Agency ceiling | Effective level | Expected behavior |
|---|---|---|---|
| EMT | EMT | EMT | Normal BLS scope |
| Paramedic | EMT | EMT | Capped; scored and prompted as EMT |
| Paramedic | Paramedic | Paramedic | Full ALS scope |
| EMT | Paramedic (generic) | EMT | No ceiling applied; student operates at EMT |
| MFR | EMT | MFR | Capped at MFR (below agency ceiling) |

---

## 6. Protocol System

### Directory structure

```
app/protocols/
├── MI/                          ← Authoritative Michigan state protocols (runtime source)
│   ├── 01_General_Treatments/
│   ├── 02_Trauma_Environmental/
│   ├── 03_Adult_Treatment/
│   ├── 04_OB_Pediatrics/
│   ├── 05_Adult_Cardiac/
│   ├── 06_Pediatric_Cardiac/
│   ├── 07_Procedures/
│   ├── 08_Procedures/
│   ├── 09_Medications/          ← Medication monographs + procedure refs
│   └── 10_Special_Operations/
└── NASEMSO/                     ← Reserved; currently empty placeholder
```

MCA-specific override directories (e.g., `mi_wmrmcc_kent/`) are reserved for future use. Currently empty — all MCAs resolve to `MI/`.

### Protocol reference formats in scenarios

```json
// Simple string ref (recommended)
"protocol": "MI/04_OB_Pediatrics/04-5_respiratory_distress"

// Ref with scenario-level overrides (merged at load time)
"protocol": {
    "ref": "MI/04_OB_Pediatrics/04-5_respiratory_distress",
    "overrides": { "scope_notes": ["CPAP unavailable on this unit"] }
}
```

### MCA substitution

When session MCA differs from the scenario's protocol path prefix, `adapt_scenario_to_context()` attempts substitution:

```
scenario: "MI/04_OB_Pediatrics/04-5_respiratory_distress"
session MCA: "mi_wmrmcc_kent"

1. Try: protocols/mi_wmrmcc_kent/04_OB_Pediatrics/04-5_respiratory_distress.json
2. Not found → keep MI/ protocol (silent fallback)
```

### MCA → state directory mapping

`_resolve_protocols_dir(mca)` in `ai_client.py` builds `_MCA_STATE_DIR` at import time by reading `mca_config.json`:

```python
_MCA_STATE_DIR = _load_mca_state_map()  # {mca_id: base_protocols}
```

Each MCA entry in `mca_config.json` carries a `base_protocols` field (e.g. `"MI"`) — adding a new MCA to that file is sufficient to wire its protocol directory. No manual code change required (Gap 5 fixed).

### Medication monograph schemas (MI/09_Medications/)

Two schemas coexist — `_build_procedures_context()` detects via the `sections` key:

| Schema | Detected by | Fields | Rendered by |
|---|---|---|---|
| Medication reference | `type: "medication_monograph"` or no `sections` | `name`, `dosing` (array), `administration.setup`, `six_rights_for_this_drug` | Inline monograph renderer |
| Sections-based | `sections` array present | `condition`, `sections[].points` | `_build_protocol_sections()` |

---

## 7. Procedure / Drug Reference System

Scenario interventions reference protocol files for AI context injection:

```json
"popup_config": {
    "drug_ref":       "MI/09_Medications/9-12R_albuterol",
    "procedure_ref":  "MI/09_Medications/9-1_medication_administration"
}
```

`procedure_engine.load_procedure(ref)` resolves against `app/protocols/`, e.g.:  
`app/protocols/MI/09_Medications/9-12R_albuterol.json`

`_build_procedures_context()` loads all refs for a scenario and injects monographs and procedure summaries into the AI system prompt. Missing refs are silently skipped.

### Currently referenced paths (all valid as of 2026-04-19)

| Scenario | drug_ref | procedure_ref |
|---|---|---|
| peds_anaphylaxis_01 | `MI/09_Medications/9-23R_epinephrine` | `MI/09_Medications/9-1_medication_administration` |
| peds_anaphylaxis_01 | `MI/09_Medications/9-12R_albuterol` | `MI/09_Medications/9-1_medication_administration` |
| peds_asthma_01 | `MI/09_Medications/9-12R_albuterol` | `MI/09_Medications/9-1_medication_administration` |
| peds_diabetic_emergency_01 | `MI/09_Medications/9-19S_oral_glucose` | — |

---

## 8. Seeding & Startup Flow

```
lifespan()
  ├── init_db()                  ← create_all + additive DDL migrations (IF NOT EXISTS)
  ├── _seed_superuser()          ← superuser account from .env (idempotent)
  ├── _seed_agency()             ← private seed agency from .env (optional; skipped if vars absent)
  ├── _seed_open_agencies()      ← all 5 generic agencies (always runs; idempotent)
  ├── _seed_agency_configs()     ← populate Agency.config from JSON for any NULL rows
  └── _migrate_member_scope()    ← correct stale mca/provider_level on all members
```

### Fresh install — no .env seed vars set

1. No private agency created (`_seed_agency` skips)
2. 5 generic open-join agencies created and configured
3. System immediately usable for self-study registration

### Agency config update — existing install

JSON file edits do **not** auto-apply to existing DB records:

```
PUT /api/agencies/{id}/config   ← superuser; replaces Agency.config + invalidates cache
```

`_seed_agency_configs()` only writes config for rows where `config IS NULL`.  
A server restart triggers `_migrate_member_scope()` which corrects any stale member MCA/level rows.

→ *See §9, Gap 2 for the live-update gap.*

---

## 9. Known Gaps & Planned Fixes

| # | Severity | Status | Summary |
|---|---|---|---|
| 1 | **Medium** | ✅ Fixed 2026-04-19 | Provider level cap missing from debrief scoring |
| 2 | Low | ✅ Fixed 2026-04-19 | MCA not live-updated on member rows after config change |
| 3 | Low | Open | `_OPEN_AGENCY_FILES` list is redundant (seeding manifest only) |
| 4 | Low | ✅ Fixed 2026-04-18 | `scenario_engine.list_agencies()` is dead code |
| 5 | Low | ✅ Fixed 2026-04-18 | `_MCA_STATE_DIR` must be manually extended for new MCAs |
| 6 | Low | Open | `agency_file` carried in JWT but unused at runtime |

---

### Gap 1 — Provider level cap missing from debrief scoring ✅ Fixed

**Was:** `evaluate_and_generate_debrief()` read `session.provider_level` directly without calling `_effective_level()`. A Paramedic student at an EMT-ceiling agency was scored as a Paramedic.

**Fix applied:** `_effective_level(level, agency_max_level)` now called at the top of `evaluate_and_generate_debrief()` before building the scoring rubric — mirrors `_build_system_prompt()` exactly.

---

### Gap 2 — MCA not live-updated on member rows after config change ✅ Fixed

**Was:** Between a `PUT /api/agencies/{id}/config` MCA change and the next server restart, all `AgencyMember.mca` rows remained stale. New logins used the old MCA until `_migrate_member_scope()` ran on restart.

**Fix applied:** `PUT /api/agencies/{agency_id}/config` now queries all `AgencyMember` rows for the agency after updating `Agency.config`, calls `_resolve_member_mca(None, config)`, and updates any row whose `mca` differs. The batch update is committed atomically with the config change. The response body includes `members_updated: N`.

**Remaining limitation:** Active JWTs are not invalidated — they carry the previous MCA until they expire (default 24 hours). Users must re-authenticate for immediate effect if MCA changes mid-session. This is accepted behavior; a token blocklist would be required to close it fully.

→ *Relates to §4 MCA resolution chain.*

---

### Gap 3 — `_OPEN_AGENCY_FILES` list is redundant

The hardcoded list in `main.py` is used only by `_seed_open_agencies()` as a manifest of which JSON files to process. It is **no longer used for access control** — registration and join endpoints check `agency.is_open_join` (DB column). The list should be retained as the seeding manifest only, with a comment clarifying its scope.

---

### Gap 4 — `scenario_engine.list_agencies()` is dead code ✅ Fixed

**Was:** `scenario_engine.py` contained `list_agencies()` which read agency data directly from JSON files. No endpoint ever called it — all agency listing is DB-backed via `GET /api/agencies/public` and `GET /api/agencies/open`.

**Fix applied:** Function removed from `scenario_engine.py`.

---

### Gap 5 — `_MCA_STATE_DIR` must be manually extended for new MCAs ✅ Fixed

**Was:** `_MCA_STATE_DIR` in `ai_client.py` was a hardcoded dict mapping MCA IDs to state protocol directories. Adding a new MCA to `mca_config.json` did not wire it automatically — a second manual edit to `ai_client.py` was also required.

**Fix applied:** Replaced with `_load_mca_state_map()` which reads `mca_config.json` at import time and builds the mapping from each MCA's `base_protocols` field. Adding a new MCA to `mca_config.json` now auto-registers it with no code changes.

→ *See §10 for updated "Adding a New MCA" instructions.*

---

### Gap 6 — `agency_file` carried in JWT but unused at runtime

`agency_file` is embedded in the JWT `ActiveContext` but never read for clinical lookups. All config comes from `Agency.config` via `load_agency()`. The field is useful for debugging and audit trails but adds noise to the token payload.

---

## 10. Adding a New MCA

1. Add entry to `app/mca_config.json` — include `base_protocols` so `_load_mca_state_map()` picks it up automatically:
   ```json
   {
     "id": "my_new_mca",
     "display": "My Region EMS Authority",
     "display_short": "MREA",
     "state": "MI",
     "base_protocols": "MI",
     "bls_expansions": ["cpap_bls"],
     "notes": "..."
   }
   ```
2. Optionally create `app/protocols/my_new_mca/` with any MCA-specific protocol overrides
3. Update private agency configs to reference the new MCA ID
4. Restart — `_migrate_member_scope()` corrects any affected member rows; `_MCA_STATE_DIR` rebuilds automatically from `mca_config.json`

---

## 11. Adding a New Agency

### Private agency (join-code required)

1. Create `app/agencies/{stem}.json` with full clinical config
2. Set `.env`: `SEED_AGENCY_NAME`, `SEED_AGENCY_JOIN_CODE`, `SEED_AGENCY_FILE={stem}`
3. Restart — `_seed_agency()` creates the DB row; `_seed_agency_configs()` populates config
4. Subsequent config changes: `PUT /api/agencies/{id}/config` (no restart needed)

### Open-join agency

1. Create `app/agencies/{stem}.json` with `"open_join": true` and `"provider_levels": {"primary": "Paramedic"}`
2. Add the file stem to `_OPEN_AGENCY_FILES` in `app/main.py`
3. Restart — `_seed_open_agencies()` creates the DB row with `is_open_join = true`

---

## 12. Scope Decision Matrix

The AI evaluates each student intervention against the student's **effective level** (capped by agency ceiling) and the session MCA's expansion set.

| Student level | Agency ceiling | Effective level | Expansion required | Expansion in MCA | AI outcome |
|---|---|---|---|---|---|
| EMT | EMT | EMT | None | — | In scope ✓ |
| EMT | EMT | EMT | `cpap_bls` | Yes | In scope ✓ |
| EMT | EMT | EMT | `cpap_bls` | No | Out of scope ✗ |
| EMT | Paramedic (generic) | EMT | `cpap_bls` | No (`mi_base`) | Out of scope ✗ |
| Paramedic | EMT | **EMT** (capped) | None | — | Scored/prompted as EMT ✓ |
| Paramedic | Paramedic | Paramedic | None | — | Full ALS scope ✓ |
| Paramedic | Paramedic (generic) | Paramedic | `cpap_bls` | No (`mi_base`) | In scope — expansion irrelevant at Paramedic level ✓ |
| MFR | EMT | MFR | None | — | MFR scope only ✓ |

**Key rule:** BLS expansion gates (`required_expansion`) apply only when effective level ≤ EMT. Paramedic and AEMT scope supersedes expansion requirements for most interventions — the AI is expected to reason about this from the protocol context.

---

## 13. Future Considerations

### Multi-state support

The current protocol directory structure (`MI/`, `NASEMSO/`) assumes Michigan as the primary jurisdiction. Supporting additional states would require:

- A `state` field on each MCA in `mca_config.json` (already present as `"state": "MI"`)
- State-specific protocol directories (e.g., `OH/`, `IN/`)
- Adding a `base_protocols` entry per MCA in `mca_config.json` (already the pattern — `_MCA_STATE_DIR` is auto-built from it)
- Scenario `protocol` refs would need to be state-agnostic or carry the state prefix explicitly

No structural changes to `Agency`, `AgencyMember`, or `SimSession` are required — the state context flows entirely through the MCA chain.

### International / non-US jurisdictions

The MCA model maps cleanly to non-US regional governance bodies (e.g., UK ambulance trusts, Canadian EMS regions). The `jurisdiction` field in agency config and protocol files is a free-text label and does not drive logic — it is display-only in the AI prompt. Adapting to a non-US system would primarily require:

- New protocol directories for that jurisdiction
- MCA entries with appropriate `bls_expansions` for that scope model
- Scenario files referencing the correct protocol paths

### Multiple private agencies per deployment

The current `.env` seed supports one private agency. Additional agencies must be created via the superuser API (`POST /api/agencies`) and configured via `PUT /api/agencies/{id}/config`. There is no batch-seed mechanism for multiple private agencies from files.
