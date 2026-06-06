# Multi-Tenant Protocol Architecture
## Design Document — EMS Simulator

**Status:** Phase 2A/2B Pilot-Complete — Phase 2C Scale Work Deferred. Phase 3 Target: Ohio.
**Last Updated:** 2026-05-03
**Authors:** Jonathan Frastaci

---

## Table of Contents

1. [Overview](#1-overview)
2. [Core Concepts](#2-core-concepts)
3. [Database Schema](#3-database-schema)
4. [Protocol Compiler](#4-protocol-compiler)
5. [Agency SOP Ingestion](#5-agency-sop-ingestion)
6. [Scenario Engine Changes](#6-scenario-engine-changes)
7. [NASEMSO National Base](#7-nasemso-national-base)
8. [State Base Authoring Pipeline](#8-state-base-authoring-pipeline)
9. [Versioning and Change Management](#9-versioning-and-change-management)
10. [Admin Dashboard](#10-admin-dashboard)
11. [Session Immutability](#11-session-immutability)
12. [Testing and Validation Strategy](#12-testing-and-validation-strategy)
13. [Phased Rollout](#13-phased-rollout)
14. [Open Questions](#14-open-questions)

---

## 1. Overview

This document describes the architecture for transitioning the EMS Simulator from a single-jurisdiction, statically-maintained protocol system into a scalable, multi-tenant LMS platform supporting multiple states, MCAs (Medical Control Authorities), and agencies.

### Problem Statement

The current system hardcodes Michigan protocols as static JSON files. Every protocol update, every new agency, and every jurisdiction addition requires direct developer intervention. This does not scale.

### Goals

- Allow agency admins to configure their jurisdiction-specific protocol settings without developer involvement
- Support multiple states, each with a base protocol set, regional MCA overrides, and agency-level customizations
- Ensure clinical accuracy and legal defensibility of all protocol configurations
- Maintain historical grading integrity — a student's past session must always be gradable against the exact protocol set active at the time
- Decouple the developer from being the sole author and maintainer of all protocol content

### Strategic Sequencing Note

This document describes the full target architecture. **Phase 1 is complete as pilot-ready protocol profile infrastructure. Phase 2A/2B are complete for pilot use.** The system can create agency protocol profiles, compile immutable snapshots, assign members to agency-approved profiles, audit/notify changes, safely materialize profile snapshots, ingest/review agency SOP rules, build session-pinned protocol excerpts, inject those excerpts into chat/debrief prompts, and apply deterministic scoring overlays for active SOP scope restrictions, contraindications, and explicit not-carried rules. Phase 2C scale work is deferred until volume demands it. Phase 3 multi-state expansion begins with Ohio (OH).

**Phase 1A shipped (2026-05-02):**
- `app/protocol_engine.py` created as single protocol gatekeeper (`get_resolved_protocol`, `get_all_protocols_for_mca`, `create_protocol_snapshot`)
- `ProtocolSnapshot` model and additive DB migration with partial unique index on `(agency_id, mca_id, content_hash)` (partial index handles nullable `agency_id` correctly)
- `SimSession` gains `protocol_snapshot_id`, `protocol_hash`, and `legacy_protocol` columns; existing rows migrated to `legacy_protocol = True`
- `scenario_engine.py` routes protocol loading through `get_resolved_protocol()`; legacy path-style refs preserved internally
- Medical Control filesystem scan replaced with `get_all_protocols_for_mca()`; broad, blinded, budget-capped, no scenario-tag filtering
- Snapshot capture wired to scenario, random call, and random quick drill session starts
- Regression tests: `test_protocol_engine.py` (resolver + hash); 311 tests passing across protocol, checklist, scoring, gold standard, evidence packet, and gamification suites

The immediate priority is now:
1. ~~Lay the two foundational pieces that prevent future rewrites~~ ✓ Done
2. ~~Add the minimum backend support for agency protocol profiles~~ ✓ Done
3. ~~Build the minimal MCA / Protocols admin UI when pilot onboarding needs self-service~~ ✓ Done
4. ~~Finalize Phase 2 prerequisites and implement local SOP/custom protocol pilot flow~~ ✓ Done
5. Get real EMS providers and training officers using the product
6. Start Phase 3 Ohio protocol-base planning and SME pipeline
7. Only after volume demands it, complete Phase 2C fan-out/PDF scale work

**NASEMSO SME blocker resolved (2026-04-17):** Jonathan Frastaci will serve as the Clinical SME reviewer for Michigan and NASEMSO base protocol content. Phase 1A can be scheduled without waiting for an external SME. See updated Section 7.4.

**Protocol scope decision recorded (2026-04-22):** A formal scope decision record has been added to `docs/AI_ARCHITECTURE.md` Section 5. Current status: single-jurisdiction (PFD/Michigan), deferred multi-agency resolver. Scenario authoring must comply with the author constraints documented there. The decision is review-gated — it will be revisited when a real second-agency protocol differentiation need arises, not before.

The Phase 3 Ohio rollout is now the next planned expansion path. Phase 2C scale features remain demand-gated rather than blocking Ohio planning.

### Pre-Phase 1A Contract Decisions (Required Before Build)

These six decisions are recorded below and must remain true before Phase 1A implementation begins. They are not open questions — they are resolved constraints. If any is challenged before build starts, update this record and the relevant canonical docs before proceeding.

**Decision 1 — Phase 1A scope has NOT been reopened**
Phase 1A remains foundation-only. The protocol scope decision recorded in `AI_ARCHITECTURE.md §5` (single-jurisdiction, deferred multi-agency resolver) has not been reopened. Phase 1A lays the ProtocolResolver abstraction and snapshot persistence so that scope can be extended later without rewrites. Nothing in Phase 1A changes how scenarios are scored, which protocols are active, or how the debrief evaluates scope. If a stakeholder review reopens multi-agency scope before Phase 1A begins, update this record and `AI_ARCHITECTURE.md §5` together — do not proceed on ambiguous authority.

**Decision 2 — adapt_scenario_to_context() is not a stub**
`adapt_scenario_to_context()` in `scenario_engine.py` already resolves agency transport type, ALS timing/unit, MCA substitution, and BLS expansion flags. The gap is not "nothing is resolved" — it is "agency context is resolved without a compiled protocol stack, snapshots, or generalized intervention scope analysis." Phase 1A changes the file-loading primitive underneath it (replacing `_load_protocol_file` with `protocol_engine.get_resolved_protocol`). Phase 2 adds the compiled stack and scope analysis on top. These are additive changes, not replacements. Do not describe this function as a stub in code comments or architecture notes.

**Decision 3 — Medical Control blindness is non-negotiable**
`AI_ARCHITECTURE.md §3.3` defines Medical Control as receiving zero scenario context. The ProtocolResolver must NOT feed scenario `clinical_context` tags to the Medical Control prompt. If a physician can see the scenario's condition tags, they can infer the diagnosis before the student verbalizes it — this breaks the simulation. Scenario-specific hidden truth (condition, expected interventions, diagnosis) must never reach the med control prompt. This constraint applies to every phase.

**Phase 1A behavior (preserve current):** `_build_med_control_protocol_summary` currently produces a broad, budget-capped MCA-level summary with no scenario-tag filtering. Phase 1A replaces the filesystem scan with `get_all_protocols_for_mca()` but preserves this behavior exactly — broad, blinded, and budget-capped. Do not add complaint-based filtering in Phase 1A. A future phase may resolve from the student's stated complaint/request, but only after the blindness invariant is verified to hold under that approach.

**Decision 4 — Protocol JSON tagging contract before authoritative tree-shaking**
The initial Phase 2 pilot uses a static mapping layer in `app/protocol_concept_index.py` and mirrors that mapping into the currently indexed protocol JSON files as `clinical_context.concepts` with `tag_source: "initial_static_mapping"` and `sme_review_status: "pending"`. This gives admins/developers inspectable tags without claiming that the full protocol corpus has been permanently migrated. Phase 1 snapshots still store the full unfiltered compiled context. SME review on 2026-05-03 approved the clinical concept/action-ID contract with revisions, and the required OB/GYN, behavioral, infectious disease, and ALS action-ID gaps were added. Static mapping remains acceptable for the Phase 2B pilot, but inline protocol JSON tags are the preferred long-term strategy to reduce drift.

**Decision 5 — Scope analysis requires canonical intervention action IDs**
The current runtime uses `[[INTERVENTION: label]]` tags and `intervention_applied` events with display labels. Evidence packet scope analysis requires stable canonical action IDs (e.g., `naloxone_administer`, `epinephrine_im_administer`, `transcutaneous_pacing`, `intravenous_access_establish`) so ProtocolResolver can match what the student actually did against what is in scope. The action ID vocabulary is defined alongside the clinical concept taxonomy (§2.5, Open Question #1) and received SME approval with revisions on 2026-05-03. Phase 2B may now implement deterministic scope analysis against those IDs, but Phase 1A does not perform scope analysis.

**Decision 6 — Intervention scope classifications (replaces ambiguous `below_scope`)**
The term `below_scope` is ambiguous (it could mean "allowed by a lower level," "beneath provider capability," or "not advanced enough for this case") and must not appear in scoring, debrief output, or API responses. Use these canonical classifications instead:

| Classification | Meaning |
|---|---|
| `in_scope` | Allowed and appropriate for this provider level |
| `out_of_scope` | Above the provider's licensure level |
| `requires_medical_control` | Allowed only with prior medical control authorization; not a standing order |
| `not_carried` | In scope but unavailable per agency equipment configuration |
| `not_indicated` | In scope but not appropriate for this clinical presentation |
| `contraindicated` | Clinically incorrect for this presentation regardless of scope |
| `available_but_not_expected` | In scope and available; not required by this scenario's rubric |

`_intervention_in_scope()` must return one of these classifications. It must not return a boolean or `below_scope`.

---

### Non-Goals (This Document)

- Real-time protocol collaboration or co-editing
- Public-facing protocol authoring by non-verified users
- Patient care record (PCR) integration
- Agency-authored custom scenarios (deferred — HIPAA/PHI compliance review required first)
- State EMS office API integrations (future consideration)
- Multi-user / crew-level simultaneous training (future consideration)
- Offline / disconnected scenario playback (future consideration)

---

## 2. Core Concepts

### 2.1 The Cascade Hierarchy

Protocol authority flows from most general to most specific. More specific levels restrict but do not expand the level above.

```
NASEMSO National Model Guidelines (fallback only)
    └── State Base Protocols  (e.g., Michigan MDHHS)
            └── Regional / MCA Overrides  (e.g., WMRMCC Kent County)
                    └── Agency Overrides  (e.g., Plainfield Fire Department)
```

**Cascade rules:**
- A lower level can **restrict** scope relative to the level above (e.g., MCA restricts a drug to paramedic-only that the state allows at AEMT)
- A lower level **cannot expand** scope beyond what the state base allows (e.g., an agency cannot authorize a drug not in the state formulary)
- Scope floors are enforced at the state base level and are not overridable by any downstream level

### 2.2 Two Types of Overrides

**Type 1 — Structured Selections (`mca_selections_required`)**
The Michigan base protocol JSON files already contain `mca_selections_required` arrays. Each entry has an `id`, `label`, `description`, and `selected: null`. These represent binary on/off decisions that MCAs and agencies make. In the new architecture, `selected` is no longer stored in the JSON file — it is stored in the database.

**Type 2 — Patch Operations (RFC 6902-style)**
For structured modifications to arrays and values within protocol objects (e.g., adding a drug to `out_of_scope`, removing a drug from `key_drugs`), overrides are stored as explicit patch operations:

```json
[
  { "op": "add", "path": "out_of_scope_bls", "value": "CPAP" },
  { "op": "remove", "path": "key_drugs", "value": "Amiodarone" }
]
```

Using patch operations (rather than full array replacement) ensures that upstream additions to base arrays are automatically inherited by downstream levels. An agency that adds "CPAP" to `out_of_scope` will automatically inherit any new items NASEMSO or the state adds to that array later — their patch is re-applied to the updated base.

**Why not full array replacement?**
Full array replacement ("arrays overwrite") silently suppresses upstream updates. If Michigan adds a new contraindication to a medication array, any agency that previously replaced that array will never see the update. In a clinical training context, silent suppression of contraindication updates is a patient safety risk.

**Patch validation:** All patch operations are validated against `allowed_levels` scope floors at write time (when the admin saves, not only at compile time). A patch attempting to add an intervention at a licensure level below its state-floor is rejected immediately with a clear error — not silently accepted and filtered later.

### 2.3 Scope Floors

The state base JSON defines `allowed_levels` for each intervention, drug, and procedure. These represent the minimum and maximum licensure levels at which the intervention is authorized statewide. The admin dashboard respects these floors — checkboxes are **disabled** (not hidden) for levels outside the state-authorized range.

```
Example:
  State: Surgical Cricothyrotomy → allowed_levels: ["Paramedic"]
  MCA Dashboard: MFR / EMT / AEMT checkboxes are LOCKED (disabled)
  Agency Dashboard: Same — cannot be enabled below Paramedic
```

### 2.3.1 Agency Protocol Profiles vs. Official MCAs

The agency admin UI should use **Protocol Profiles** as the primary concept. A protocol profile is the agency's training configuration for a base protocol set and, when applicable, a regional MCA. It may represent:

- a generic profile using NASEMSO National Model Guidelines
- a state-base profile such as Michigan base
- an agency-local profile named after a regional MCA, such as "Kent County"
- an agency-specific training profile with local SOP additions

Do **not** treat every agency-created profile as an official regional MCA. Official MCA records are shared jurisdictional authorities and require separate governance. Agency-created profiles are agency-local unless promoted or certified by a superadmin/MCA admin workflow in a later phase.

**Runtime rule:** Generic/open users may choose NASEMSO or a state base profile. Agency users inherit an agency-approved protocol profile, or choose only from profiles the agency has created/approved. A joined agency member must not self-select an MCA/profile that bypasses the agency's configured protocol authority.

### 2.4 Role-Based Access Control (RBAC)

A system with clinical liability cannot allow a single user to submit and certify their own protocol changes. Agency-level permissions are segregated by role.

| Role | Responsibilities |
|---|---|
| **Provider** | End-user student. Runs simulations, views own history and progress. Read-only access to own data. |
| **Training Officer** | Reviews and certifies SOPs submitted by Admins. Can view all member analytics and session debriefs. Cannot modify agency settings or manage users. **Cannot certify SOPs they submitted.** |
| **Agency Admin** | Manages agency settings, invites/removes members, assigns roles. Can submit SOPs for review. **Cannot certify their own SOP submissions.** |
| **MCA Admin** | Future role for official regional MCA authority. Separate from agency-level protocol profiles. Managed and credentialed outside the standard agency onboarding flow — see [Open Question #12](#14-open-questions). |

**Separation of duties enforcement:**
- An SOP rule enters `pending_review` state after AI extraction and Admin submission
- The rule only becomes `active` (`approved_at` is set) when a **Training Officer** who is **not** the original submitter approves it
- `approved_by` is a non-nullable column and must reference a different user than the submitter — enforced at the database level, not just the UI

**Small agency edge case — resolved for Phase 2:** Self-approval is not allowed. If a small agency has only one administrator/training officer, agency-local SOP rules can be drafted but cannot become active until a second named agency user approves them or an internal platform clinical reviewer approves them through paid onboarding/support. The system may show a "needs external reviewer" state, but it must not offer a one-person override for clinically authoritative SOP activation.

**Official MCA Admin boundary — resolved for Phase 2:** Agency Protocol Profiles are agency-local training configurations. They do not create or modify official regional MCA authority. Rules that claim `scope_expansion`, alter provider-level standing orders, or represent shared regional MCA policy require an internal/superadmin-held "MCA reviewer" approval path until a credentialed MCA Admin portal exists. Phase 2 may build the data hooks and review state, but broad self-service MCA Admin credentialing remains deferred.

### 2.5 Controlled Vocabulary for Scenario Tags

Scenarios declare their clinical dependencies using a controlled vocabulary of tags. These tags are used by the Protocol Compiler's relevance filter (tree-shaker) to identify which sections of the resolved protocol — and which agency SOPs — to inject into the LLM prompt.

```json
"clinical_context": {
  "concepts": ["pediatric_respiratory_distress", "reactive_airway"],
  "medications": ["albuterol_svn", "epinephrine_im"],
  "procedures": ["nebulization", "bvm_ventilation"]
}
```

The tag taxonomy must be defined and maintained centrally. Tags in scenarios, protocol JSON nodes, and SOP rules must be identical strings from the controlled vocabulary — a tag mismatch silently returns no protocol context, which is worse than a wrong answer because there is no error to diagnose.

**Canonical tag list location:** `docs/clinical_concept_taxonomy.md` — must be created and finalized before any Phase 2 scenario migration or SOP tagging.

---

## 3. Database Schema

### 3.1 Core Tables

**`agencies`**
```
id                          UUID PRIMARY KEY
name                        TEXT NOT NULL
default_protocol_profile_id UUID  (FK → agency_protocol_profiles.id, nullable)
state_code                  TEXT  (e.g., "MI")
active_protocol_snapshot_id UUID  (FK → protocol_snapshots.id, nullable)
created_at                  TIMESTAMP
updated_at                  TIMESTAMP
```

**`mcas`**
```
id                          TEXT PRIMARY KEY  (e.g., "mi_wmrmcc_kent")
state_code                  TEXT
display_name                TEXT
base_protocol_version       TEXT  (matches state JSON "version" field)
created_at                  TIMESTAMP
```

**`agency_protocol_profiles`**
Agency-local training protocol profiles. These are the admin-facing "MCA / Protocols" objects, but they are not automatically official regional MCA records.
```
id                  UUID PRIMARY KEY
agency_id           UUID  (FK → agencies.id, nullable for generic/open profiles)
display_name        TEXT  (e.g., "Kent County", "Michigan Base", "NASEMSO")
profile_type        TEXT  (generic_base | state_base | agency_local | official_mca)
base_protocol_set   TEXT  (e.g., "NASEMSO", "MI")
official_mca_id     TEXT  (FK → mcas.id, nullable — set only when tied to official MCA authority)
is_default          BOOLEAN NOT NULL DEFAULT FALSE
is_active           BOOLEAN NOT NULL DEFAULT TRUE
created_by          UUID  (FK → users.id, nullable for system profiles)
created_at          TIMESTAMP
updated_at          TIMESTAMP
```

**Profile selection rule:** Agency users inherit the agency default profile unless an agency admin assigns another active profile to the member. Open/generic users may choose from system profiles (`agency_id = NULL`) such as NASEMSO or a state base. Agency members may only use profiles approved for their agency; students do not self-select profiles that bypass agency authority.

**Default propagation rule:** `AgencyMember.protocol_profile_assignment_source` records whether the member is following the agency default (`default`) or pinned by an admin (`manual`). When the agency default profile changes, default-inherited members move to the new default. Manual assignments remain pinned until an admin returns the member to "Agency default" or selects another profile.

**Profile deactivation rule:** The active agency default profile cannot be deactivated. A profile with manually assigned members also cannot be deactivated until those members are reassigned or returned to "Agency default." This prevents future sessions from resolving to an inactive profile.

**Base protocol set change rule:** Changing a profile's `base_protocol_set` clears its structured selections before recompilation. Selections belong to a specific base protocol catalog; carrying them across catalogs risks stale no-op configuration. The audit event records how many selections were cleared.

**`agency_members` protocol fields**
```
protocol_profile_id                  UUID  (FK → agency_protocol_profiles.id, nullable)
protocol_profile_assignment_source   TEXT  ("default" | "manual")
```

**`agency_protocol_selections`**
Stores binary on/off decisions from `mca_selections_required` arrays.
```
id                      UUID PRIMARY KEY
agency_id               UUID  (FK → agencies.id)
protocol_profile_id     UUID  (FK → agency_protocol_profiles.id)
mca_id                  TEXT  (FK → mcas.id)
protocol_id             TEXT  (e.g., "mi_base_medication_ref_ketamine")
selection_id            TEXT  (e.g., "ketamine_pain_management_iv")
is_selected             BOOLEAN
base_protocol_version   TEXT  (version of state JSON when selection was made)
created_at              TIMESTAMP
updated_by              UUID  (FK → users.id)
```

**`agency_protocol_patches`**
Stores RFC 6902-style patch operations for array/value overrides.
```
id              UUID PRIMARY KEY
agency_id       UUID  (FK → agencies.id)
protocol_profile_id UUID  (FK → agency_protocol_profiles.id)
protocol_id     TEXT
patch_ops       JSONB  (array of {op, path, value} objects)
created_at      TIMESTAMP
updated_by      UUID  (FK → users.id)
```

**`agency_sops`**
Stores agency-local SOP/custom protocol rules for the agency MCA workflow. Draft/review rows are non-authoritative; Phase 2B-approved rows move to `active` and are eligible for session-pinned protocol excerpts.
```
id                       UUID PRIMARY KEY
agency_id                UUID  (FK → agencies.id)
protocol_profile_id      UUID  (FK → agency_protocol_profiles.id)
version_id               TEXT
rule_type                TEXT  (local_sop | scope_restriction | contraindication | scope_expansion | equipment_policy | not_carried | training_note | protocol_clarification)
status                   TEXT  (draft | pending_review | pending_external_review | reviewed_non_authoritative | active | rejected | superseded)
extracted_rule           TEXT
source_quote             TEXT
source_label             TEXT
page_number              INTEGER
clinical_concept_tags    JSONB  (array of CLINICAL_CONCEPTS ids)
intervention_action_ids  JSONB  (array of INTERVENTION_ACTIONS ids)
patch_operations         JSONB  (nullable RFC 6902-style operations)
sme_review_status        TEXT  (pending | approved | changes_requested)
submitted_by             UUID  (FK → users.id)
submitted_at             TIMESTAMP
approved_by              UUID  (FK → users.id)
approved_at              TIMESTAMP
rejected_by              UUID  (FK → users.id)
rejected_at              TIMESTAMP
superseded_at            TIMESTAMP
metadata_json            JSONB
created_at               TIMESTAMP
updated_at               TIMESTAMP
```

**Authority rule:** `agency_sops` rows may be created, submitted, reviewed, audited, and associated with protocol profiles while non-authoritative. Only rows promoted to `active` after second-person review may affect session-pinned excerpts, prompts, debrief context, or deterministic scope analysis. Draft, pending, rejected, superseded, and `reviewed_non_authoritative` rows remain excluded from authoritative runtime use.

### 3.2 Protocol Snapshots

Immutable compiled protocol records. Never updated — new compile = new row.

**`protocol_snapshots`**
```
id              UUID PRIMARY KEY
agency_id       UUID  (FK → agencies.id, nullable — null = national/state base snapshot)
mca_id          TEXT  (e.g., "mi_wmrmcc_kent" — required for idempotency lookup)
compiled_json   JSONB  (fully resolved, flattened protocol object)
content_hash    TEXT   (SHA-256 of sorted compiled_json)
created_at      TIMESTAMP
superseded_at   TIMESTAMP  (nullable — set when a newer snapshot is compiled)
```

**Unique constraint:** `(agency_id, mca_id, content_hash)` must be unique. The idempotency check in `create_protocol_snapshot()` depends on this constraint — use `INSERT ... ON CONFLICT (agency_id, mca_id, content_hash) DO NOTHING` or equivalent.

**Key behaviors:**
- Rows are never deleted or mutated after creation
- `superseded_at` is set on the old snapshot when a new one is compiled
- The `agencies.active_protocol_snapshot_id` pointer is updated atomically by the background worker after compilation completes
- The "last known good" snapshot remains active until the new one is ready — zero downtime

### 3.3 Sessions

**`sessions`** (relevant columns)
```
id                          UUID PRIMARY KEY
user_id                     UUID
agency_id                   UUID
scenario_id                 TEXT
protocol_snapshot_id        UUID   (FK → protocol_snapshots.id)
protocol_hash               TEXT   (SHA-256 — copied from snapshot at session start)
active_sop_ids              JSONB  (array of agency_sops.id active at session start)
effective_protocol_excerpt  JSONB  (nullable filtered excerpt; authoritative only when `authoritative: true` and pinned at session start)
debrief_markdown            TEXT   (nullable — populated on first debrief generation; immutable thereafter)
started_at                  TIMESTAMP
```

**Debrief immutability:** The first time a debrief is generated for a session, the resulting markdown is stored in `debrief_markdown` as the immutable original. `session.feedback` may still hold the latest regenerated instructor debrief after explicit re-debrief workflows; `debrief_markdown` preserves the first generated version for audit and comparison.

**Storage note:** A full debrief is approximately 2–4KB. At 100K sessions this is 200–400MB in the sessions table — manageable, but worth monitoring as a table size concern at scale.

**Tamper verification:** At any future point, `session.protocol_hash` can be compared to `protocol_snapshots.content_hash` via the `protocol_snapshot_id` FK. A mismatch indicates post-session data tampering.

**Legacy session migration:** Existing sessions created before this architecture is deployed will not have `protocol_snapshot_id` or `protocol_hash`. These sessions should be flagged with a `legacy_protocol: true` marker and treated as un-verifiable for tamper evidence purposes. Debriefs for legacy sessions that haven't been generated yet should trigger a one-time generation and storage. See [Open Question #13](#14-open-questions).

### 3.4 Agency SOPs

Append-only ledger of agency-specific SOP rules.

**`agency_sops`**
```
id                      UUID PRIMARY KEY
agency_id               UUID  (FK → agencies.id)
protocol_profile_id     UUID  (FK → agency_protocol_profiles.id)
version_id              UUID   (groups rules from a single upload/approval event)
rule_type               TEXT   (local_sop | scope_restriction | contraindication | scope_expansion | equipment_policy | not_carried | training_note | protocol_clarification)
status                  TEXT   (draft | pending_review | pending_external_review | reviewed_non_authoritative | active | rejected | superseded)
extracted_rule          TEXT   (max 500 characters)
clinical_concept_tags   JSONB  (ids from canonical taxonomy — required for future relevance filtering)
intervention_action_ids JSONB  (ids from canonical action vocabulary)
patch_operations        JSONB  (nullable RFC 6902-style operations)
source_quote            TEXT   (verbatim text from source document)
source_page             INTEGER
source_document         TEXT   (filename or reference)
submitted_by            UUID   (FK → users.id — Agency Admin who submitted)
approved_by             UUID   (FK → users.id — Training Officer/Admin reviewer who certified; NOT NULL after Phase 2A review approval)
approved_at             TIMESTAMP
superseded_at           TIMESTAMP  (nullable)
```

**Key constraint:** `approved_by` must reference a different user than `submitted_by` — enforced at the API layer, backed by `ck_agency_sops_no_self_approval`, and audited in `agency_audit_logs`.

### 3.5 Audit Logs

**`agency_audit_logs`**
```
id              UUID PRIMARY KEY
agency_id       UUID
user_id         UUID
action          TEXT   (e.g., "protocol_selection_changed", "sop_submitted", "sop_approved", "sop_superseded")
previous_state  JSONB  (nullable)
new_state       JSONB
timestamp       TIMESTAMP
ip_address      TEXT
```

Audit logs are append-only. No update or delete operations are permitted on this table.

### 3.6 Protocol Change Notifications

**`protocol_change_notifications`**
```
id                  UUID PRIMARY KEY
user_id             UUID  (FK → users.id)
agency_id           UUID
snapshot_id         UUID  (FK → protocol_snapshots.id — the new snapshot)
summary_markdown    TEXT  (auto-generated change summary)
seen_at             TIMESTAMP  (nullable — null until user acknowledges)
created_at          TIMESTAMP
```

---

## 4. Protocol Compiler

### 4.1 Compile-on-Write Strategy

The protocol is NOT resolved at runtime (compile-on-read). It is compiled ahead of time whenever a change is saved (compile-on-write) and stored as a materialized snapshot.

**Triggers that enqueue a compile job:**
- Agency admin saves Protocol Profile selection changes
- Agency admin approves new/revised SOPs
- Future MCA admin saves official regional override changes
- A new state base JSON version is published (fan-out — one job per affected agency)

**Benefits:**
- Scenario engine does zero merge work at runtime — O(1) snapshot lookup by `agency_id`
- Stale reads are bounded to the worker processing window (seconds to minutes), not indefinite
- State base updates propagate automatically through re-applying the patch chain

### 4.2 Compilation Process

```
1. Load state base JSON files for the agency's state_code
2. Apply official MCA-level patch operations (future shared authority only)
3. Apply official MCA-level selections (future shared authority only)
4. Apply Protocol Profile patch operations
5. Apply Protocol Profile selections
6. Validate scope floors — any selection or patch violating allowed_levels is rejected and logged
7. Serialize to JSONB
8. Compute SHA-256 content hash over sorted keys
9. Insert new row into protocol_snapshots
10. Atomically update agencies.active_protocol_snapshot_id
11. Enqueue protocol_change_notification jobs for all active agency users
```

**Merge rules:**
- Dict/object keys: downstream value overwrites upstream
- Arrays: use RFC 6902 patch operations (add/remove); never full replacement
- Scope floors: enforced at step 6; violations are rejected with error, not silently accepted

### 4.3 Fan-Out and Queue Management

A state base update affecting 500 agencies must not trigger 500 simultaneous compile jobs. Each compile job is individually queued as a lightweight message:

```
compile_agency_protocol_task:
  agency_id: UUID
  trigger: "state_base_update"
  triggered_by: "mi_base_v2025-04-01"
```

Worker pool processes jobs at controlled concurrency (e.g., 10 simultaneous). Total propagation time for a state update across 500 agencies: minutes, not seconds. Acceptable for a training context.

**Phase 2 sequencing decision:** A background fan-out queue is not required for Phase 2 pilot SOP/profile work. Synchronous compile-on-write remains acceptable for single-agency profile edits, manual SOP edits, and admin preview validation as long as compile status/errors are surfaced and the last known good snapshot remains active on failure.

Queue implementation is required before either of these scale triggers:

- state-base updates are propagated across multiple agencies
- profile/SOP volume makes synchronous compile latency unacceptable for agency admins

When a queue is needed, use a simple DB-backed job queue first. Redis/Celery, SQS/Lambda, or another broker should be introduced only if measured workload requires it.

**Phase split:**
- **Phase 2A:** Synchronous compile-on-write for pilot SOP/profile edits; no fan-out worker.
- **Phase 2B:** DB-backed compile queue before state-base update propagation or high-volume agency rollout.
- **Phase 2C:** External broker only after DB-backed queue limits are demonstrated.

### 4.4 Consistency Window Behavior

During the window between admin saving changes and worker completing compilation:

- New sessions: use the current `active_protocol_snapshot_id` (last known good)
- In-progress sessions: unaffected — they already captured their snapshot at `start_session`
- After worker completes: `active_protocol_snapshot_id` updates atomically; new sessions use new snapshot

No blocking, no errors, no race conditions.

### 4.5 Change Summary Generation

When a new snapshot supersedes the previous one, the compiler generates a human-readable change summary for the provider notification modal. This is computed from the JSON diff between old and new `compiled_json`.

**Phase 2 policy:** Change summaries are template-based only. LLM-generated protocol change summaries are explicitly out of scope for Phase 2 because provider-facing change notices are safety-relevant, audit-relevant, and generated during compile/write workflows. LLM summaries may be reconsidered later only as draft assistance for internal reviewers, never as the stored authoritative notification without deterministic review.

**Challenge:** Converting a raw JSON diff (e.g., `albuterol_svn.dosing[0].dose: "2.5mg" → "3mg"`) into readable clinical language is non-trivial. Phase 2 uses predefined templates for known change types and a conservative fallback for unknown diffs.

1. **Dose change:** "Dose guidance for {item} changed from {old} to {new}."
2. **Scope change:** "{item} availability changed for {provider_level}: {old_status} → {new_status}."
3. **Protocol added/removed:** "{protocol_title} was added/removed from this profile."
4. **SOP rule added/removed:** "Local SOP rule added/removed: {rule_summary}."
5. **Fallback:** "Protocols have been updated. Review the profile with your Training Officer before starting new assigned training."

The template library requires ongoing maintenance as new change types emerge — this is recurring operational work, not a one-time build. Unknown diffs must degrade conservatively rather than silently omitting a notification.

### 4.6 Observability and Monitoring

The compile worker must be treated as a clinical-accuracy-critical process. Silent failures mean agencies train on stale or incorrect protocols with no warning.

**Required instrumentation:**
- Alert on compile job failure (any job that errors must page, not just log)
- Alert on queue depth exceeding a threshold (indicates worker backlog or outage)
- Alert on `active_protocol_snapshot_id` not updating within expected window after a job is enqueued
- Dashboard showing per-agency snapshot age and base version currency
- Audit report: agencies whose `base_protocol_version` is more than N versions behind current — surfaced to the internal admin, not just logged

This monitoring is a Phase 1 requirement, not a Phase 2 nice-to-have. A compile failure that goes undetected means providers train on wrong protocols.

---

## 5. Agency SOP Ingestion

### 5.1 Input Methods

**Tier 1 (All plans) — Rich-Text Paste:**
Admin pastes text directly into a large textarea in the Admin Dashboard. Text is sent to the LLM extraction pipeline. This is the primary input method.

**Tier 2 (Pro/Enterprise only) — PDF Upload:**
Admin uploads a PDF. The backend converts pages to images and uses a multimodal vision LLM to extract text. This handles scanned and multi-column documents that standard PDF parsers (pdfplumber, PyPDF2) cannot reliably read.

**Rejection behavior:** If PDF parsing confidence falls below threshold, the system fails loudly: "We could not reliably read this document. Please paste the relevant text manually." Silent failures are not acceptable.

### 5.2 AI Extraction Pipeline

The LLM is not asked to summarize — it is asked to return structured JSON conforming to a strict extraction schema:

```json
[
  {
    "extracted_rule": "EMTs must contact Medical Control before administering a 3rd dose of Nitroglycerin.",
    "source_quote": "Contact Medical Control prior to administering third dose of NTG for chest pain.",
    "page_number": 4,
    "rule_type": "notification_requirement",
    "suggested_tags": ["chest_pain_acs", "nitroglycerin"]
  }
]
```

**`rule_type` options (controlled vocabulary):**
- `scope_restriction` — restricts an intervention to a higher provider level
- `contraindication` — marks an otherwise in-scope intervention as clinically inappropriate for the tagged presentation; scored in `protocols_treatment`, not `scope_adherence`
- `not_carried` — marks an otherwise in-scope intervention as unavailable/not carried by that agency or unit configuration; scored in `protocols_treatment`, not `scope_adherence`
- `scope_expansion` — claims to expand scope (flagged for mandatory SME review; cannot override state floor)
- `dosage_deviation` — local dose differs from state base
- `notification_requirement` — requires contact with medical control or specific notification
- `equipment_requirement` — agency-specific equipment or formulary note
- `transport_protocol` — destination or transport-specific rule
- `documentation_requirement` — additional documentation beyond standard

`suggested_tags` are provided by the LLM as suggestions only — the Training Officer confirms or corrects them during the certification step.

### 5.3 Human Review Workflow

The SOP ingestion pipeline enforces a multi-step, multi-role process:

**Step 1 — Draft creation:** Phase 2A starts with manual rich-text rule entry. Later AI/PDF extraction can populate the same fields. New rules enter `draft` state.

**Step 2 — Admin Review:** Agency Admin reviews extracted rules for basic accuracy using the split-panel UI. Left panel: `extracted_rule` (editable). Right panel: `source_quote` + `page_number` (read-only verbatim). Admin corrects obvious errors and submits for clinical certification.

**Step 3 — Training Officer Certification:** A Training Officer (who is not the submitting Admin) reviews each rule in the same split-panel UI. During certification, the Training Officer:
- Confirms or corrects the `extracted_rule` text
- Confirms or overrides the `suggested_tags` with the canonical taxonomy
- Approves or rejects each rule individually

**Step 4 — Batch Certification:** After individual rule review, the Training Officer checks: "I have reviewed these SOPs against the source document and certify they are clinically accurate for my agency." Timestamp and user ID are recorded. This is the `approved_at` / `approved_by` write. In Phase 2A this moves the row to `reviewed_non_authoritative`; it does not activate runtime use.

Rules with `rule_type: scope_expansion` are additionally flagged for internal/MCA review before becoming active — they cannot be approved by the agency alone.

**Small-agency approval rule:** If the submitting user is the only available admin/training officer, the rule remains `pending_external_review`. The agency can use the base profile without the local SOP rule, or route the rule through Enterprise/onboarding support for internal clinical review. The system must not provide a self-approval override for clinically authoritative SOP activation.

### 5.4 Hard Limits

Enforced at the API route level, not just the UI:

| Constraint | Limit | Rationale |
|---|---|---|
| Max PDF file size | 5 MB | Prevents abuse; PDFs >5MB are unlikely to be agency addendums |
| Max pages processed | 15 pages | >15 pages is a state manual, not an agency SOP |
| Max extracted rule character length | 500 characters | Accommodates conditional EMS directives |
| Max active SOP rules per agency | 20 rules | Prevents prompt token bloat |
| PDF extraction API calls | 5/month (Pro), 20 in first 30 days (onboarding burst) | Cost control for vision LLM calls |
| Manual paste extractions | Unlimited | No significant compute cost |

**Vision LLM cost note:** Multimodal extraction of a 15-page PDF costs approximately $0.15–$0.25 per run (GPT-4o / Claude Sonnet pricing). At 5 calls/month: ~$1.00/agency/month in raw compute. Must be absorbed by Pro/Enterprise tier pricing, not the Free tier.

### 5.4.1 Sales Tier Contract

Phase 2 feature boundaries are:

| Tier | Protocol Capability | Limits |
|---|---|---|
| Open / Free | Generic NASEMSO or built-in state base profiles only. No agency-local SOP ingestion. | Intended for individual learners and demos. |
| Pro Agency | Agency Protocol Profiles, state base selection, structured MCA selections, manual rich-text SOP ingestion, template change notifications. | Limited profile count and active SOP rule count per hard limits above. PDF extraction is available with monthly cap. |
| Enterprise / Onboarding | Everything in Pro plus assisted SOP onboarding, internal clinical reviewer workflow for one-person agencies, higher PDF extraction caps, custom BAA/security review where required. | Required before agency-custom content is sold into departments that require legal/security review. |

State-specific base protocol access can be offered in Pro or Enterprise depending on state authoring/review cost. Agency-local SOP ingestion must not be offered in the Open / Free tier.

### 5.5 SOP Versioning

SOPs use an append-only ledger model. When an agency re-uploads and re-approves SOPs:

1. New `agency_sops` rows are inserted with a new `version_id`
2. Previous rows have `superseded_at` set and `status` updated to `superseded`
3. Previous rows are never deleted
4. Active SOPs = rows where `status = 'active'`

**Session capture:** At `start_session`, the backend records `active_sop_ids`. Historical sessions always debrief against the SOPs that were active at session start — not the current set.

### 5.6 Patch Validation Policy

Phase 2 patch/SOP writes use fail-loud validation at write time and again at compile time.

**Write-time validation requirements:**
- RFC 6902 patch paths must exist in the selected base protocol/schema unless the operation is an explicit `add` to an allowed extension path.
- Patch operations must be schema-validated before storage; invalid paths return `422` and are not persisted.
- Scope-expansion patches cannot activate on agency approval alone; they enter an internal/MCA-review-required state.
- Patches must reference canonical protocol IDs, clinical concept IDs, and intervention action IDs. Display labels are not accepted as authoritative references.
- A failed patch must surface a human-readable diagnostic to the admin and write an audit event.

**Compile-time validation requirements:**
- Re-run all write-time validations against the current base protocol version.
- If a previously valid patch no longer applies after a state-base update, keep the last known good snapshot active, mark compile status `failed`, notify admins, and do not silently drop the patch.
- Unknown or no-op patches are errors, not warnings.

### 5.7 HIPAA / BAA Posture

Phase 2 assumes protocol/SOP content is not PHI. The product should still treat named-user training data as sensitive operational education data.

**Before Enterprise agency onboarding or any agency-custom content workflow is broadly sold:**
- Publish a no-PHI content policy for SOP uploads, notes, custom scenarios, and free-text fields.
- Add UI/API attestation that uploaded SOPs and pasted local rules do not contain patient identifiers.
- Keep agency-custom scenario authoring deferred until a separate PHI/BAA review is complete.
- If an agency requires a BAA because named-user training data is handled under their compliance posture, route them to Enterprise/onboarding rather than self-serve Pro.
- Do not market the platform as a clinical documentation, patient-care record, or PHI storage system.

---

## 6. Scenario Engine Changes

### 6.0 The ProtocolResolver — Foundational Abstraction

**This is the most important architectural decision in the entire document and the one thing that must be built before any user acquisition work begins.**

Every part of the application that currently loads protocol JSON files directly must be replaced with a single call to `get_resolved_protocol(agency_id, protocol_id)`. No other component in the system ever touches JSON files directly.

**Why this matters:** The resolver is the only seam between "Option B now" and "V2 later." If the rest of the application calls the resolver with a consistent interface, swapping the implementation from "read JSON from disk" to "query materialized snapshot" requires zero changes to `scenario_engine.py`, `ai_client.py`, or the scoring engine.

**The interface contract — frozen from day one:**
- Input: `agency_id` (nullable until agencies exist), `protocol_id` (string identifier — NOT a file path)
- Output: a dict conforming to `pfd_protocol_v1` or `pfd_medication_reference_v1` schema

**Critical distinction — protocol_id vs. file path:** The resolver's public interface uses a protocol ID (e.g., `"mi_base_medication_ref_ketamine"`), not a file path. The file path is an internal implementation detail of the Option B resolver. If the interface is built around paths, evolving to database lookups in V2 requires changing the contract — breaking the isolation.

**Phase 1A compatibility rule — legacy path refs in existing scenarios:** Current scenario JSON files reference protocols using path-style strings (e.g., `"MI/04_OB_Pediatrics/..."`). Phase 1A must not break existing scenario loading. Choose one of these approaches and record the decision before writing code:

- **(A) Internal path-acceptance (recommended for Phase 1A):** `get_resolved_protocol()` accepts both a `protocol_id` string (canonical) and a legacy path-style string. Internally, if the input contains `/` or ends in `.json`, it is treated as a path and resolved directly. The public contract remains `protocol_id`-first; path-style inputs are a tolerated legacy form. Document them as deprecated in the function docstring.
- **(B) Scenario migration first:** Migrate all existing scenario protocol refs to canonical IDs before Phase 1A ships. Requires a one-time script and re-validation of all affected scenarios. Cleaner long-term; more upfront work.

Option A allows Step 3 (scenario engine update) to proceed without touching scenario JSON. Option B eliminates the legacy path in one pass. Either is acceptable; the risk is choosing neither and silently breaking scenario loading when `_load_protocol_file` is removed.

**Phase 1A implementation (foundation / static-protocol):** At session start, compile all protocol JSON files for the agency's MCA into a single unified context dict, serialize deterministically, and compute the content hash. Then check whether a `protocol_snapshots` row already exists for `(agency_id, mca_id, content_hash)`. If one exists, reuse it — do not insert a new row. Only insert when the compiled content has actually changed. The session stores a FK to the matched or newly inserted row.

**Idempotency is required.** Inserting a new full 500KB–1MB snapshot per session would cause unbounded storage growth and make `superseded_at` meaningless. The hash-before-insert check is the enforcement mechanism.

**V2 implementation (later):** Instead of compiling at session start from disk, read the pre-compiled snapshot that the compile-on-write worker already persisted. The caller sees no difference.

**Important:** File I/O in the resolver must be handled correctly for async web servers. Standard `open()` calls block the event loop. Use `asyncio.get_event_loop().run_in_executor()` or an async file library. This is not optional in a production async context.

**Compiled context shape — the keying decision:**
The compiled context is a dict of all protocols for an MCA, keyed by protocol ID. The protocol ID used as the key must match the `"id"` field already present in each JSON file (e.g., `"mi_base_medication_ref_ketamine"`) — not a path-derived dot-notation string. The tree-shaker in V2 looks up protocols by these IDs. If Option B keys them differently, the tree-shaker must be rewritten when V2 arrives, defeating the abstraction.

```
compiled_context = {
  "mca_id": "mi_wmrmcc_kent",
  "protocols": {
    "mi_base_medication_ref_ketamine": { ...full protocol dict... },
    "mi_base_medication_ref_albuterol": { ...full protocol dict... },
    ...
  }
}
```

**Snapshot size:** Michigan alone has 150+ protocol JSON files. The compiled context for a full state may be 500KB–1MB as a JSONB blob. This is acceptable for Phase 1A but should be monitored. The V2 tree-shaker addresses prompt injection — it does not reduce the snapshot storage size.

### 6.1 Protocol Resolution at Runtime

**Phase 1A behavior (no agency table changes):** `agencies.active_protocol_snapshot_id` does not exist yet in Phase 1A — the agencies table is not modified. Instead, session start calls `create_protocol_snapshot(db, agency_id, mca_id)` directly, which compiles, hashes, and returns a reused or newly inserted `ProtocolSnapshot`. The session stores the returned snapshot's `id` and `content_hash`. The code below describes **V2 / Phase 1B+ behavior** (compile-on-write worker + active pointer), not Phase 1A.

**V2 / Phase 1B+ behavior (after compile-on-write worker exists):**

The scenario engine performs no cascade merging. At session start:

```python
snapshot = db.query(ProtocolSnapshot)
    .filter_by(id=agency.active_protocol_snapshot_id)
    .one()

session.protocol_snapshot_id = snapshot.id
session.protocol_hash = snapshot.content_hash
session.active_sop_ids = get_active_sop_ids(agency_id)
```

The compiled protocol blob is retrieved in a single query. The scenario engine works only with the resolved snapshot.

### 6.2 Relevance Filtering — Two-Pass Tree-Shaker

The full compiled protocol and all agency SOPs cannot be injected into the LLM prompt. The tree-shaker performs two passes:

**Pass 1 — Protocol filter:**
Match scenario `clinical_context` tags against protocol JSON nodes in the materialized snapshot. Extract only matching sections.

**Pass 2 — SOP filter:**
Match scenario `clinical_context` tags against `clinical_concept_tags` on each active SOP. Extract only matching rules.

**Output:** A filtered protocol subset + a filtered SOP subset — both ready for prompt injection.

The tree-shaker is only as reliable as the tag taxonomy. A tag mismatch silently returns no content — worse than a wrong answer because there is no error to surface. The canonical tag list must be the single source of truth for all tagging across scenarios, protocol JSON nodes, and SOP rules.

**Phase 2 prerequisite status — initial protocol tags exist and are approved for the Phase 2B pilot.** The currently indexed protocol subset carries `clinical_context.concepts` mirrored from the static mapping layer. Coverage is intentionally limited to scenario-relevant MI/NASEMSO protocols. SME review approved the pilot contract with revisions addressed on 2026-05-03. Full-corpus protocol tagging and inline-tag migration remain future work as scenario coverage expands.

### 6.3 Scoring Engine — Scope vs. Clinical Errors

`_intervention_in_scope()` must be refactored to return a structured result, not a boolean:

```python
{
  "allowed": False,
  "reason": "mca_restriction",  # scope_floor | mca_restriction | agency_sop | clinical_contraindication
  "required_level": "Paramedic",
  "source": "mi_wmrmcc_kent_selection_id_12"
}
```

**Scope classification taxonomy:**

Use the canonical classifications defined in the Pre-Phase 1A Contract Decisions (Decision 6). The structured result from `_intervention_in_scope()` maps to these classifications as follows:

| Classification | `reason` value | Example | Debrief Language |
|---|---|---|---|
| `out_of_scope` | `scope_floor` | EMT attempts surgical airway (state min = Paramedic) | "Outside your licensure level statewide" |
| `out_of_scope` | `mca_restriction` | EMT gives albuterol in MCA that restricted to AEMT+ | "Clinically appropriate; restricted by your MCA" |
| `requires_medical_control` | `standing_order_limit` | EMT gives 3rd NTG dose without authorization | "Requires medical control authorization per protocol" |
| `out_of_scope` | `agency_sop` | Action violates an active agency SOP rule | "Correct per state protocol; violates your agency SOP" |
| `contraindicated` | `clinical_contraindication` | Adenosine for wide-complex tachycardia | "Clinically incorrect — contraindicated for this presentation" |
| `not_carried` | `equipment_config` | Ventilator not on unit per agency config | "Not available on your unit per your agency configuration" |
| `not_indicated` | `clinical_presentation` | CPAP for normoxic patient | "In scope but not indicated for this presentation" |
| `available_but_not_expected` | `not_in_rubric` | In scope, correct, but no rubric item expected it | Not deducted; may be noted as proactive care |

**`below_scope` must not be used.** It is ambiguous and has been retired. See Decision 6 above.

These distinctions matter for debrief quality and student learning. A policy error is not a clinical error and must not be graded identically.

**Action ID prerequisite:** Scope classification requires canonical intervention action IDs matched against resolver output — not display labels from `[[INTERVENTION: label]]` tags. This layer is unbuilt until the action ID vocabulary is finalized (Decision 5, Open Question #1). Phase 1A does not implement scope classification in the evidence packet.

### 6.4 SOP Prompt Injection

SOPs are appended to the prompt as a clearly demarcated separate block — never merged into the structured protocol output. Prompt structure:

```
## STATE & MCA PROTOCOL
[Tree-shaker Pass 1 output — filtered protocol subset]

---

## AGENCY-SPECIFIC STANDARD OPERATING PROCEDURES
**IMPORTANT:** The following rules reflect local agency SOPs for this clinical context.
They govern operational flow but CANNOT expand the student's licensed scope of practice.
Evaluate SOP compliance separately from clinical correctness.

- [Approved, tagged, relevant SOP rule 1]
- [Approved, tagged, relevant SOP rule 2]
```

Scope expansion claims in SOP text are structural guardrails enforced by the compiler — the prompt note is a hint to the model, not the enforcement mechanism. Do not rely on the LLM to correctly interpret "cannot expand scope" under adversarial prompt conditions.

### 6.5 Scenario Jurisdictional Portability

Scenarios authored against specific state protocols are not universally portable. The scenario JSON schema gains a `jurisdiction` field:

- `"jurisdiction": "national"` — authored against NASEMSO model; runs correctly for any agency
- `"jurisdiction": "mi_base"` — authored against Michigan-specific protocols; may not score correctly for non-Michigan agencies

**Engine behavior:** When a student at an agency running on `nasemso_model_guidelines` launches a scenario tagged `"jurisdiction": "mi_base"`, the UI displays:
> "This scenario was authored for Michigan-specific protocols. It will be graded against the NASEMSO National Model, and some expected actions may differ from your training."

**Content strategy:** All new scenarios should default to `"jurisdiction": "national"`. Michigan-specific scenarios should be reviewed and re-tagged as `national` where possible during Phase 2.

---

## 7. NASEMSO National Base

### 7.1 Naming and Purpose

The national fallback protocol set is named `nasemso_model_guidelines` — never "NREMT protocols" or "national EMS standards."

- **NREMT** is a certification examination body — not a protocol publisher
- **NASEMSO** (National Association of State EMS Officials) publishes the National Model EMS Clinical Guidelines — a voluntary reference document
- No agency holds a license or operates under NASEMSO guidelines directly
- This base provides a functionally reasonable training baseline but is explicitly provisional for any specific jurisdiction

### 7.2 UI Disclaimer Requirements

If an agency's resolved protocol chain terminates at `nasemso_model_guidelines`, a persistent, non-dismissible banner appears on all training-facing screens:

> ⚠️ **Provisional Protocol Active:** This scenario is being graded against NASEMSO National Model Guidelines. These may not reflect your jurisdiction's scope of practice, formulary, or local protocols. Contact your MCA for jurisdiction-specific configuration.

This banner cannot be hidden by the agency admin. It persists until the agency is linked to a state base protocol.

### 7.3 Phase 1 CTA

The banner includes an action button. In Phase 1 (self-serve onboarding tool does not yet exist), the button reads **"Request Protocol Customization"** — not "Upload Protocols."

Clicking opens a modal that submits an inquiry to the support/sales queue:
- Agency name and ID
- State/region
- Contact name and email

This creates a high-intent lead for the paid onboarding tier without implying self-serve functionality that doesn't exist in Phase 1.

### 7.4 Authoring and Maintenance

The NASEMSO base is a **first-party content asset maintained by the internal product team** — not user-generated. Its authoring follows the same three-role process as any state base:

1. Data Engineer runs AI-assisted draft generation
2. Clinical SME (paramedic, EMS educator, or EMS physician) reviews all clinical content against the NASEMSO source document
3. System Admin publishes the reviewed base

**Phase 1A SME blocker resolved (2026-04-17):** Jonathan Frastaci will serve as the Clinical SME reviewer for Michigan and NASEMSO base content. Phase 1A engineering and NASEMSO authoring can proceed in parallel immediately.

---

## 8. State Base Authoring Pipeline

### 8.1 The Bottleneck

Adding a new state requires authoring 100–200+ structured JSON files conforming to `pfd_protocol_v1` and `pfd_medication_reference_v1` schemas. This cannot be delegated to agency admins. It requires clinical accuracy and schema knowledge. This is a **business and sequencing problem**, not purely an engineering problem. The bottleneck does not block national launch — the NASEMSO base provides a functional fallback.

### 8.2 Content Roles

All state base authoring (including the NASEMSO base) requires three distinct roles:

| Role | Responsibility |
|---|---|
| **Data Engineer** | Runs AI-assisted draft generation; ensures schema compliance |
| **Clinical SME** | Paramedic, EMS educator, or EMS physician; verifies all doses, contraindications, pediatric cutoffs, and scope levels against source PDFs |
| **System Admin** | Publishes audited state base to production; sets `version` field and publishes release notes |

The developer cannot serve as the Clinical SME for states or content they have no clinical basis to verify. Schema conformance (guaranteed by structured output) is not the same as clinical accuracy. These are separate verification steps.

**Michigan / NASEMSO exception (2026-04-17):** Jonathan Frastaci will serve as Clinical SME reviewer for Michigan base and NASEMSO content. For Phase 3 states outside Michigan, a separate contracted clinical reviewer (paramedic, EMS educator, or EMS physician familiar with that state's protocols) is required.

### 8.3 AI-Assisted Draft Generation (Internal Tool)

An internal CLI tool (not user-facing) accelerates state authoring:

**Input:** State EMS protocol PDF
**Process:** Vision LLM with structured output constrained to `pfd_protocol_v1` / `pfd_medication_reference_v1` schema fields (using pydantic or instructor for schema enforcement)
**Output:** Draft JSON files, one per protocol section

**Realistic time estimates:**
- AI draft generation: 1–2 hours per state (automated)
- Clinical SME review: 1–5 business days depending on state protocol complexity and AI draft quality

The efficiency gain is real — going from 100% manual authoring to reviewing and correcting a draft — but schema conformance does not guarantee clinical accuracy. The LLM can produce a valid JSON object with a plausible but incorrect pediatric dose or an inverted contraindication. Human SME review is non-negotiable.

### 8.4 State Expansion Strategy

In order of implementation priority:

1. **NASEMSO National Base** — Phase 1A prerequisite; enables any agency to onboard immediately on the provisional tier
2. **Fork-and-Diff** — states structurally similar to Michigan (Midwest neighbors) can be derived as delta overrides on the MI base rather than full re-authoring
3. **AI-Assisted Draft + SME Review** — for states requiring full authoring; internal tool + contracted clinical reviewer
4. **Paid State Onboarding Tier** — agencies or state EMS offices pay a one-time fee to fund clinical authoring of their state's base protocols
5. **State EMS Office Partnerships** — long-term; state offices with interest in digital protocol distribution provide authoritative content directly

---

## 9. Versioning and Change Management

### 9.1 Schema Evolution Policy

The core protocol schemas (`pfd_protocol_v1`, `pfd_medication_reference_v1`) will evolve as new states are added and edge cases are found. To prevent breaking changes across hundreds of static JSON files:

**Schema is append-only:**
- New fields are always **optional** — never required
- Application code reading from the schema must provide safe fallbacks for any new field that may be absent from older files
- Fields are never renamed or removed — they are deprecated with a note and left in place

This policy avoids complex data migration scripts for static file-based protocol content. A Michigan file authored in 2025 must remain valid and parseable in 2028 even as the schema grows.

**Version tracking:** The `"_schema"` field in each JSON file records the schema version (`pfd_protocol_v1`, `pfd_protocol_v2`, etc.). Application code branches on this field when parsing if backward compatibility requires different handling.

### 9.2 State Base Version Notifications (Admin)

When the state base `version` field is updated, agency admin dashboards display a notification:

> "The Michigan base protocols have been updated (v2025-04-01). Review your current selections to ensure they remain appropriate for your agency."

The notification persists until acknowledged. Protocol selections made against the old version are flagged with the version they were based on.

### 9.3 Protocol Change Notifications (Provider-Facing)

When an agency's snapshot is recompiled and `active_protocol_snapshot_id` is updated, a notification is generated for all active users in that agency. On next login, they see a "What's New" modal.

**Change summary generation:** Auto-generated from the JSON diff between old and new `compiled_json` using the Phase 2 template-only policy:

- **Template-based for known change types:** Predefined sentence templates for common changes (dose change, drug added/removed, scope level changed). Covers the majority of cases with no LLM cost.
- **Fallback for unknown types:** "Protocols have been updated — review with your Training Officer." Displayed when the change type does not match any template.

The template library requires ongoing maintenance as new change types emerge. This is recurring operational work, not a one-time build.

LLM-generated provider-facing change summaries are out of scope for Phase 2.

---

## 10. Admin Dashboard

### 10.1 Agency Admin Dashboard Information Architecture

Agency configuration should move toward a tabbed structure:

| Tab | Purpose |
|---|---|
| **EMS** | Current agency clinical configuration: service type, transport behavior, ALS dispatch, equipment, provider-level ceiling |
| **Fire** | Fire/rescue operations configuration — TBD; should not be coupled to EMS protocol rules |
| **MCA / Protocols** | Agency Protocol Profiles: base protocol set, profile naming, protocol selections, local SOP/custom protocol additions |

The top-level dashboard should not force fire/rescue agencies through EMS-only language. The protocol profile model supports EMS now and can support fire/rescue operational protocols later without making "MCA" the only authority concept.

### 10.2 Protocol Profile UI

The MCA / Protocols tab lets admins create and manage **Protocol Profiles**:

- Create profile: name, base protocol set (`NASEMSO`, `MI`, future state sets), optional official MCA linkage, default/active flag
- Review selections: grouped list of `mca_selections_required` options with source protocol reference and section number
- Scope floors: disabled choices where the base set does not authorize the level
- Local additions: custom local SOP/protocol rules, handled through the reviewed SOP pipeline in Phase 2
- Multiple profiles: agency may create more than one profile, but one default must be explicit
- User/session assignment: agency members inherit default profile unless assigned another active agency-approved profile

**Naming rule:** UI may display "MCA" because EMS users understand it, but persisted objects should be named `ProtocolProfile` / `agency_protocol_profiles` unless they represent an official shared MCA authority.

### 10.3 Protocol Toggle UI

The admin dashboard presents protocol selections as structured toggle controls — not free text. For each `mca_selections_required` entry in the state base:

- Checkbox or toggle per provider level (MFR / EMT / AEMT / Paramedic)
- Scope floor levels are **disabled** (grayed out with tooltip, not hidden) for levels outside state-authorized range
- Changes are staged — admin sees a diff preview before submitting
- Submission enqueues a compile job; admin sees "Protocol update queued — changes will be live within a few minutes"

### 10.4 Versioning Notifications

When the state base `version` field is updated, each agency admin dashboard displays a prompt to review selections. The notification persists until acknowledged. Protocol selections made against the old version are flagged with the version at time of selection.

---

## 11. Session Immutability

### 11.1 Snapshot at Session Start

When a student starts a scenario:

1. Backend reads `agency.active_protocol_snapshot_id`
2. Records `protocol_snapshot_id` and `protocol_hash` in the session row
3. Records `active_sop_ids` (all `status = 'active'` SOPs for the agency at this moment)
4. Session is permanently linked to this exact protocol state

No future protocol changes affect in-progress or historical sessions.

### 11.2 Debrief Immutability

When a debrief is generated for a session for the first time:

1. LLM generates the debrief markdown
2. Markdown is written to `sessions.debrief_markdown`
3. `sessions.feedback` also stores the latest displayed debrief text
4. Instructor re-debrief may update `sessions.feedback`, but must not overwrite `sessions.debrief_markdown`

This preserves the original debrief for audit and drift comparison while allowing explicit instructor/admin regeneration workflows to remain available.

### 11.3 Tamper Verification

To verify a historical session's protocol integrity:

1. Load `protocol_snapshots` row via `session.protocol_snapshot_id`
2. Compute SHA-256 of `snapshot.compiled_json` (sorted keys, deterministic serialization)
3. Compare to `session.protocol_hash`
4. Match = integrity confirmed; mismatch = post-session data tampering detected

### 11.4 Snapshot vs. Session Excerpt — Conceptual Split

These two things are distinct and must not be conflated:

- **`protocol_snapshots.compiled_json`** — the full compiled jurisdiction/agency protocol stack. May be 500KB–1MB. Stored once per compile event. Many sessions may share the same snapshot row. This is the audit-verifiable corpus.

- **`session.effective_protocol_excerpt`** (Phase 2, added when tree-shaking is live) — the filtered subset actually injected into the LLM prompt for this session's specific scenario. Much smaller. Directly auditable without re-running the tree-shaker. Keyed to the scenario's `clinical_context` tags at the time of the session.

Phase 1A stores only `protocol_snapshot_id` and `protocol_hash`. The excerpt field is a Phase 2 addition when the tree-shaker is built. Debrief auditability in Phase 1A means "we can verify the full corpus was unmodified" — not "we can reproduce the exact filtered context injected into the LLM." Both are needed eventually; the excerpt is the one that makes individual session debriefs fully self-contained.

---

## 12. Testing and Validation Strategy

For a system where a misconfigured protocol means students train on medically incorrect information, testing is load-bearing — not optional.

### 12.1 Cascade Correctness (Integration Tests)

The compile-on-write worker must have integration tests verifying the full patch chain resolves correctly. A wrong merge fails silently and pushes a wrong protocol to production with no exception thrown.

**Required test cases:**
- Dict key override: downstream value replaces upstream correctly
- Array `add` patch: new item appended; existing items preserved
- Array `remove` patch: target item removed; other items preserved
- Scope floor enforcement: attempting to allow a below-floor intervention at the patch-write step returns a validation error
- Full cascade: national → state → MCA → agency, verify final compiled JSON matches expected output fixture
- Atomic pointer update: after a compile job completes, `active_protocol_snapshot_id` is updated and prior snapshot has `superseded_at` set

### 12.2 Tree-Shaker Correctness (Unit Tests)

The relevance filter must return exactly the right protocol sections and SOP rules for a given scenario's `clinical_context` tags — not more, not less.

**Required test cases:**
- Tag present in both protocol and SOP: both are returned
- Tag present in protocol only: only protocol section returned; no SOP noise
- Tag present in SOP only: only SOP returned; no unrelated protocol sections
- Tag not present anywhere: empty result returned (not an error; upstream logic must handle gracefully)
- Partial tag match (e.g., `reactive_airway` vs `reactive_airway_disease`): confirm no match — enforce exact string equality

### 12.3 Scoring Discrimination (Unit Tests with Fixtures)

`_intervention_in_scope()` must be covered by fixture-based unit tests verifying correct reason codes.

**Required test cases:**
- Intervention at state-forbidden level: returns `{ reason: "scope_floor" }`
- Intervention restricted by MCA but allowed by state: returns `{ reason: "mca_restriction" }`
- Intervention forbidden by agency SOP: returns `{ reason: "agency_sop" }`
- Intervention clinically contraindicated for presentation: returns `{ reason: "clinical_contraindication" }`
- Intervention fully allowed: returns `{ allowed: True }`

### 12.4 Clinical Accuracy Review (Human Process)

Automated tests can verify schema conformance and code logic, but cannot verify that a drug dose is clinically correct. The process mandates:

- A named Clinical SME performs a full review whenever a major version of a State Base is published
- The SME review is documented and signed (analog or digital) before the version is marked production-ready
- Minor patch releases (e.g., typo corrections, metadata changes) require SME spot-check, not full review
- The SME is identified by name in the release record for each state base version

### 12.5 Load and Fan-Out Testing

Before enabling state base updates with fan-out compilation, verify the worker queue handles concurrency correctly.

**Required tests:**
- Enqueue 100 simultaneous compile jobs; verify all complete successfully and none corrupt each other's snapshot
- Verify worker concurrency limit is respected (e.g., 10 simultaneous) — queue depth increases correctly under load
- Verify that a compile job failure does not silently leave `active_protocol_snapshot_id` pointing to a stale or partially-compiled snapshot

---

## 13. Phased Rollout

### Recommended Build Sequence (Updated 2026-05-02)

The following sequence reflects the contract-first approach required by the Pre-Phase 1A decisions above. Steps 1–3 are prerequisite decisions; Steps 4–6 are implementation phases.

1. **Define ProtocolResolver output contract** — resolved protocols, citations, level permissions, med-control requirements, contraindications, equipment/not-carried flags, and content hash. The interface signature must be frozen before any code is written against it.
2. **Define canonical clinical concept taxonomy AND intervention action ID vocabulary together** — these are co-dependent (see Decision 5). Doing concept tags first and action IDs later produces a mismatch that breaks scope analysis.
3. **Add protocol snapshot / session hash persistence** (Phase 1A — the only engineering in this step).
4. **Add scene/debrief protocol context injection** — feed resolved protocol context into the scene chat system prompt and the evidence packet builder. Medical Control blindness must be preserved throughout.
5. **Add deterministic evidence-packet scope analysis** — using canonical action IDs and the classification taxonomy from Decision 6. This is the first time the evidence packet can make authoritative scope deductions.
6. **Expand `adapt_scenario_to_context()` into full Layer 3 scoring** — only after the compiled protocol stack and scope analysis are in place. Not before.

---

### Phase 1A — Foundation Only ✓ COMPLETE (2026-05-02)

**Goal:** Lay the two foundational pieces that prevent future rewrites without building anything that requires a Clinical SME, a compile worker, or an admin UI.

**Implementation notes:**
- Partial unique index used for `(agency_id, mca_id, content_hash)` because `agency_id` is nullable — a standard unique constraint cannot enforce uniqueness over NULL values in PostgreSQL. The partial index correctly handles null `agency_id` (national/state base snapshots) while still preventing duplicate rows for agency-specific snapshots.
- Legacy path-style protocol refs in existing scenario JSON are accepted internally by `get_resolved_protocol()` and treated as deprecated; the public interface is ID-first going forward.
- Snapshot capture wired to scenario, random call, and random quick drill session starts in `main.py`.

**Step 1 — DB migration:** ✓
- [x] Add `ProtocolSnapshot` model (`id`, `agency_id` nullable, `mca_id` TEXT, `compiled_json`, `content_hash`, `created_at`, `superseded_at`) with partial unique index on `(agency_id, mca_id, content_hash)`
- [x] Add `protocol_snapshot_id` (UUID, nullable FK → protocol_snapshots) and `protocol_hash` (TEXT, nullable) to `SimSession` model
- [x] Add `legacy_protocol` (BOOLEAN, default False) column to `SimSession` — set True on existing rows via migration

**Step 2 — `app/protocol_engine.py`:** ✓
- [x] `get_resolved_protocol(agency_id, protocol_id)` — ID-based public interface; path-style refs tolerated internally as deprecated legacy form
- [x] `get_all_protocols_for_mca(agency_id, mca_id)` — replaces `rglob` scan in `ai_client.py`
- [x] `create_protocol_snapshot(db, agency_id, mca_id)` — idempotent; hash-checks before inserting; uses partial-index-safe conflict handling

**Step 3 — `scenario_engine.py`:** ✓
- [x] `_load_protocol_file` removed; replaced with `get_resolved_protocol` from `protocol_engine`
- [x] `_resolve_protocol` and `adapt_scenario_to_context` unchanged; only file-loading primitive changed

**Step 4 — `ai_client.py`:** ✓
- [x] `_build_med_control_protocol_summary` filesystem scan replaced with `get_all_protocols_for_mca`
- [x] `agency_id` threaded through to `get_medical_control_response` and `_build_med_control_protocol_summary`
- [x] Medical Control remains broad, blinded, budget-capped — no scenario tags passed

**Step 5 — Session start wiring (`main.py`):** ✓
- [x] `create_protocol_snapshot` called at scenario, random call, and random quick drill session starts
- [x] `protocol_snapshot_id` and `protocol_hash` assigned before session row committed

**Step 6 — Regression tests:** ✓
- [x] `test_protocol_engine.py`: resolver and hash regression coverage
- [x] 311 tests passing (protocol, checklist, scoring, gold standard, evidence packet, gamification)

**What was NOT built in Phase 1A (confirmed):**
- No `agency_protocol_selections` table
- No compile-on-write worker
- No admin dashboard
- No RBAC
- No `agency` table changes (active_protocol_snapshot_id is V2/Phase 1B+)

**Outcome:** ✓ Codebase safe to extend. Every future V2 component is additive. Historical sessions are immutable. Phase 1B backend profile foundation is now layered on top of this work.

---

### Phase 1B — Protocol Profile Foundation ✓ COMPLETE (2026-05-02)

**Gate:** Opened by product decision on 2026-05-02 to support agency-created MCA/protocol profiles.

**Goal:** Manually onboard 2–3 pilot agencies by adding the minimum database support for agency protocol profiles and per-profile selections. The admin UI may show a basic MCA / Protocols profile screen, but full local SOP ingestion and custom protocol authoring remain Phase 2.

**Engineering (only after gate is met):**
- [x] Create `agency_protocol_profiles` table and default-profile assignment rules
- [x] Create `agency_protocol_selections` table with `protocol_profile_id` and `base_protocol_version`
- [x] Update `create_protocol_snapshot()` to compile against the selected agency protocol profile, not just `agency_id + mca_id`
- [x] Update registration/account creation: agency users inherit agency-approved profiles only; open/generic users inherit the selected open agency's default base profile
- [x] Add minimal admin API for profile create/edit: name, base protocol set, optional official MCA linkage, default flag
- [x] Add admin member assignment to another active profile from the same agency
- [x] Add minimal admin MCA / Protocols tab UI for profile create/default management
- [x] Add structured selection review grouped by protocol section/reference
- [x] Manually configure pilot profiles if the full UI is not ready; do not allow unreviewed custom free-text protocol additions in Phase 1B
- [x] Add regression coverage that profile selections alter only matching structured MCA option blocks
- [x] Add regression coverage that profile selections change the compiled snapshot hash
- [x] Confirm Phase 1 only compiles profile-specific protocol context; deterministic scoring/scope changes are Phase 2+ because they require canonical intervention action IDs

**Implemented foundation (2026-05-02):**
- `AgencyProtocolProfile` and `AgencyProtocolSelection` relational models added.
- `Agency.default_protocol_profile_id`, `AgencyMember.protocol_profile_id`, and `SimSession.protocol_profile_id` added.
- `create_protocol_snapshot()` now resolves the effective profile, creates a default agency profile when needed, compiles from the profile's base protocol set, overlays structured `mca_selections_required` toggles into the snapshot, and hashes that profile-specific corpus.
- Admin API endpoints added for base protocol sets, profile list/create/update, and structured selection list/replace.
- Agency Config dashboard now has EMS, Fire, and MCA / Protocols sub-tabs; Fire is intentionally placeholder-only, while MCA / Protocols supports profile create/default management.
- Structured MCA selections now support option values, not only booleans, so protocols such as "Primary SGA device" can store the selected option without distorting it into a yes/no toggle.
- New memberships, open-agency joins, context switches, and login fast paths now assign or persist the agency-approved default `protocol_profile_id`; frontend response payloads include that profile ID for audit/debug visibility.
- Admin member editing now supports protocol profile assignment. The backend validates that the selected profile is active and belongs to the member's agency before writing `AgencyMember.protocol_profile_id`, records whether the assignment is default-inherited or manual, and logs assignment changes in `agency_audit_logs`.
- Agency default profile changes propagate to members with `protocol_profile_assignment_source = "default"`; manually assigned members are not overwritten.
- Default profiles and profiles with manual member assignments cannot be deactivated until the dependency is removed.
- Structured selection saves validate against the profile's base protocol option list and fail loudly on unknown `protocol_id:selection_id` pairs or invalid option values; typos cannot silently persist as no-op selections.
- Changing a profile's base protocol set clears prior structured selections before compiling the new snapshot.
- Session snapshotting re-checks the member's current database assignment at session start, so a recently changed profile applies to new sessions even if the student's active token still contains the prior profile ID.
- Regression coverage now verifies profile selections overlay only the matching `mca_selections_required` block in the compiled snapshot, do not mutate unrelated protocol options, and produce a distinct compiled snapshot hash.
- No free-text local protocol ingestion is allowed in this phase.

**Pilot validation criteria** (product/market validation, not Phase 1 engineering blockers):
- At least 2 pilot agencies confirm profile-specific scoring reflects their actual training/protocol configuration
- At least 1 Training Officer confirms each pilot profile is clinically accurate for their agency
- Pilot agencies indicate they would pay for this or that it solves a real training problem

**Outcome:** Multi-tenant protocol profile resolution works end-to-end. Pilot agencies still need to validate demand and confirm profile-specific training value, but that validation gates Phase 2 investment rather than Phase 1 engineering completion.

---

### Phase 1C — Self-Serve Protocol Profile Admin UI ✓ COMPLETE FOR PILOT (2026-05-02)

**Gate:** The self-serve UI exists behind agency admin access for pilot use. Broad release depends on pilot validation and Phase 2 governance decisions.

**Goal:** Replace manual profile configuration with a safer self-serve interface.

- [x] Create `agency_audit_logs` table
- [x] Create `protocol_change_notifications` table
- [x] Implement Phase 1 RBAC model: protocol profile/admin endpoints require agency admin or superuser context; future Training Officer/MCA Admin separation remains Phase 2 governance
- [x] Build full admin dashboard tab structure: EMS, Fire (placeholder), MCA / Protocols
- [x] Build Protocol Profile list/detail UI with default-profile management
- [x] Build admin dashboard protocol toggle UI for structured selections
- [x] Build Phase 1 compile-on-write materialization: synchronous profile compilation with active snapshot pointer
- [x] Add Phase 1 compile observability: profile compile status, error, and timestamp surfaced in admin UI

**Implemented safety foundation (2026-05-02):**
- `agency_audit_logs` is append-only and records protocol profile create/update plus structured selection changes with previous/new state and request IP.
- `protocol_change_notifications` is created for active agency members when protocol profiles or selections change. Notifications are conservative until the compile worker exists: `snapshot_id` is nullable and summaries name the profile/selection change rather than claiming a compiled snapshot was published.
- Users can fetch and acknowledge protocol-change notifications through `/api/me/protocol-change-notifications` and `/api/me/protocol-change-notifications/seen`.
- Admins can fetch recent agency audit events through `/api/agency/audit-logs`; the MCA / Protocols dashboard surfaces recent profile/selection audit activity.
- The frontend checks for unseen protocol-change notifications after active login/context selection and shows an acknowledgement modal before the user starts new work.
- Lightweight compile-on-write materialization is implemented at the profile level: `agency_protocol_profiles.active_protocol_snapshot_id` points to the latest immutable snapshot for that profile. Profile create/update/selection changes compile synchronously and update that pointer; session starts reuse the active profile snapshot when available.
- If a profile is auto-created or first compiled during session start, the snapshot builder opportunistically backfills `active_protocol_snapshot_id` and compile status so the admin UI does not remain in "Snapshot pending" after a valid session snapshot exists.
- Synchronous materialization observability is stored on the profile (`last_compile_status`, `last_compile_error`, `last_compiled_at`) and surfaced in the MCA / Protocols profile list. The async background worker, queue-depth monitoring, and alerting remain pending.

**Deferred beyond Phase 1:**
- Async compile worker / queue-depth monitoring / external failure alerting. The synchronous materialization path is adequate for pilot scale; a DB-backed worker becomes necessary when compile fan-out or state-base update propagation is implemented.
- Fine-grained Training Officer and official MCA Admin role separation. Phase 1 safely restricts protocol profile mutation to agency admins/superusers; Phase 2 SOP review requires separation-of-duties and more granular RBAC.

---

### Phase 1 Closeout Follow-Up Tracker

This tracker is the handoff between the completed Phase 1 infrastructure and any Phase 2 implementation work. Phase 1 is complete, but Phase 2 must not start as a coding effort until the blocking follow-ups below are resolved or explicitly accepted as risks.

| Follow-up | Status | Blocks Phase 2 implementation? | Notes |
|---|---|---:|---|
| Pilot agency validation | Not started | No, but gates investment | Validate with 2-3 agencies that profile-specific configuration matches how they train and is valuable enough to justify Phase 2 work. |
| User acquisition path | Open | No, but gates prioritization | Decide how real providers/training officers will find the product before expanding protocol customization scope. Mirrors Open Question #15. |
| Clinical concept taxonomy | SME approved with revisions addressed | No for Phase 2B implementation | `docs/clinical_concept_taxonomy.md` now records SME review dated 2026-05-03. Missing OB/GYN, behavioral/psychiatric, infectious disease/sepsis, pulmonary edema, croup, tension pneumothorax, cardiac arrest, stroke, dysrhythmia, hypothermia, frostbite, and heat illness concepts were added. |
| Canonical intervention action ID vocabulary | SME approved with revisions addressed | No for Phase 2B implementation | `vocabulary.INTERVENTION_ACTIONS` now includes required BLS resuscitation, airway adjunct, hemorrhage-control, chest-seal, traction-splint, pediatric assessment, ALS airway, vascular access, electrical therapy, and high-risk medication action families. |
| Protocol JSON tagging contract | Initial indexed retrofit complete; SME-approved for Phase 2B pilot, inline tags preferred long-term | No for Phase 2B implementation | Static mapping layer created in `app/protocol_concept_index.py`; 48 MI and 19 NASEMSO indexed protocol files now carry mirrored `clinical_context.concepts` with `sme_review_status: pending`. Future protocol expansion should migrate toward inline tags to reduce drift. |
| Scenario tagging retrofit | Initial current-library pass complete; SME-approved for Phase 2B pilot | No for Phase 2B implementation | Existing EMS scenarios now carry `clinical_context` tags and `jurisdiction`; tests verify tags reference `CLINICAL_CONCEPTS` and produce at least one non-authoritative protocol preview match. |
| Admin protocol excerpt preview | Initial UI complete | No | Agency admins can preview scenario-to-protocol matches from the MCA/Protocols dashboard tab. This is diagnostic only and explicitly non-authoritative. |
| SOP approval governance | Resolved for Phase 2 | No | Submitter cannot approve their own SOP. One-person agencies route to a second named reviewer or internal/Enterprise clinical review; no self-approval override. Scope-expansion rules require internal/MCA review. |
| Async compile/fan-out queue | Sequencing contract resolved | No for Phase 2A pilot; yes before scale triggers | Phase 2A uses synchronous compile-on-write. DB-backed queue is required before state-base update propagation or high-volume agency rollout. External broker deferred until measured need. |
| Protocol change summary policy | Resolved for Phase 2 | No | Template-based summaries only. LLM-generated summaries remain deferred and may only assist internal drafts later, not authoritative provider notifications. |
| RFC 6902 patch validation policy | Resolved for Phase 2 | No | Validate patches at write time and compile time. Bad paths/no-op patches fail loudly; last known good snapshot remains active on compile failure. |
| Tiering and sales packaging | Initial contract resolved | No for pilot; yes for pricing | Open/Free excludes local SOP ingestion. Pro Agency gets profiles/manual SOP/PDF cap. Enterprise covers onboarding, one-person agency review, higher caps, and BAA/security review. |
| HIPAA/BAA posture | Initial contract resolved | No for local dev; yes before enterprise sales | No-PHI policy required; agency-custom content requires attestation. BAA/security review routes to Enterprise/onboarding. Custom scenario authoring remains deferred. |

**Phase 2 entry rule:** The taxonomy/action-ID vocabulary, scenario tags, static mapping layer, indexed protocol tag retrofit, and non-authoritative preview tooling are complete for the Phase 2B pilot. SME review closed with required revisions addressed on 2026-05-03. Authoritative clinical use is still not automatically enabled: build and test Phase 2B tree-shaking, prompt injection, and scope-analysis paths before any production prompt/scoring/debrief use.

**SME review note (2026-05-03):** SME review approved the taxonomy/action-ID architecture with revisions. Required additions were made for OB/GYN, behavioral/psychiatric, infectious disease/sepsis, pulmonary edema, croup, tension pneumothorax, cardiac arrest, stroke, dysrhythmias, hypothermia/frostbite/heat illness, BLS resuscitation, airway adjuncts, hemorrhage control, chest seals, traction splints, ALS airways, vascular access, electrical therapy, and high-risk ALS medications. Static mappings are acceptable for the Phase 2B pilot; moving tags inline into protocol JSON is recommended to reduce drift.

**Prerequisite closeout note (2026-05-03):** Phase 2 governance/policy blockers are resolved at the contract level for SOP approval, change summaries, patch validation, tiering, and HIPAA/BAA posture. Taxonomy/tagging implementation prerequisites are complete for the Phase 2B pilot. The remaining blockers before authoritative runtime use are engineering implementation, regression coverage, and explicit enablement of tree-shaking/scope-analysis paths.

---

### Phase 2 — Local SOP / Custom Protocol Ingestion, Relevance Filtering, and Tagging Retrofit

**Goal:** Enable agencies to add reviewed local SOPs/custom protocol rules to Protocol Profiles and enable accurate, token-efficient protocol injection.

**Prerequisites:**
- [x] Finalize and publish complete `clinical_concept_taxonomy.md` through SME review (approved with revisions addressed 2026-05-03)
- [x] Finalize canonical intervention action ID vocabulary alongside the concept taxonomy through SME review (approved with revisions addressed 2026-05-03)
- [x] Choose initial protocol tagging strategy: static mapping layer in `app/protocol_concept_index.py` for pilot tree-shaking
- [x] Add initial indexed protocol JSON tags: 48 MI and 19 NASEMSO files now carry `clinical_context.concepts`, `tag_source: "initial_static_mapping"`, and `sme_review_status: "pending"`
- [x] Add initial `clinical_context` and `jurisdiction` tags to existing EMS scenarios
- [x] Add regression coverage that every current EMS scenario produces at least one non-authoritative protocol preview match from its `clinical_context`
- [x] Build non-authoritative protocol excerpt preview/helper scaffold for validating scenario tags against the static protocol index, including per-protocol `matched_concepts` rationale for SME/developer review
- [x] Add admin-only non-authoritative preview endpoint: `GET /api/admin/protocol-excerpt-preview?scenario_id=...&base_protocol_set=MI`
- [x] Add admin dashboard preview panel in the MCA/Protocols tab for inspecting matched concepts/protocols without affecting scoring, prompts, debriefs, Medical Control, or session persistence; scenario IDs are selectable from the loaded scenario catalog
- [x] Resolve SOP approval governance for Phase 2: no submitter self-approval, no one-person clinical override, internal/MCA review required for scope expansions
- [x] Resolve protocol change summary policy for Phase 2: template-based only; no LLM-generated authoritative provider notifications
- [x] Resolve RFC 6902 patch validation policy: write-time and compile-time validation, fail loudly, keep last known good snapshot
- [x] Resolve initial tiering contract: Open/Free excludes local SOPs; Pro supports agency profiles/manual SOP/PDF cap; Enterprise handles onboarding, one-person external review, and BAA/security review
- [x] Resolve initial HIPAA/BAA posture: no-PHI attestation for custom content, BAA/security review through Enterprise, custom scenario authoring remains deferred
- [x] Resolve compile/fan-out sequencing: Phase 2A can use synchronous compile-on-write; DB-backed queue required before state-base propagation or high-volume rollout; external broker deferred until measured need
- [ ] **Full tagging retrofit:** Move from pilot static mappings toward inline protocol JSON tags for the broader protocol corpus as scenario coverage expands.
- [x] SME-review taxonomy, action IDs, static protocol mappings, and scenario `clinical_context` tags before tree-shaking or scoring consumes them authoritatively (approved with revisions addressed 2026-05-03)

**Phase 2A Engineering — allowed before SME review (non-authoritative / persistence / workflow):**
- [x] Create `agency_sops` table (append-only, versioned, with `clinical_concept_tags`, `sme_review_status`, and review-state fields)
- [x] Associate SOP/custom protocol rules with `protocol_profile_id`
- [x] Build agency SOP/custom protocol ingestion backend — rich-text/manual rule draft path
- [x] Build agency SOP/custom protocol ingestion UI — manual rich-text rule draft path
- [x] Build human review / Training Officer certification UI (manual rule/source quote + concept/action ID review step)
- [x] Implement separation-of-duties enforcement in the API and DB constraint (submitter ≠ approver)
- [x] Update `sessions` table to capture `active_sop_ids`, `effective_protocol_excerpt`, and `debrief_markdown`
- [x] Implement debrief immutability (store first generated debrief in `sessions.debrief_markdown`)
- [x] Implement template-based change summary for provider notifications (profile create/update/selection changes; no LLM-generated summaries)
- [x] Add scenario jurisdiction mismatch warning modal as advisory UI only
- [x] Keep all tag-derived protocol excerpts behind admin preview / non-authoritative validation flags until Phase 2B runtime use is explicitly enabled
- [x] Add Phase 2B helper scaffold for action-ID lookup and protocol/SOP excerpt assembly. This was introduced as non-authoritative test/admin infrastructure and now backs the explicit Phase 2B runtime path.

**Phase 2B Engineering — runtime wiring status:**
- [x] Implement authoritative two-pass tree-shaker (protocol filter + active-SOP filter)
- [x] Write unit tests for tree-shaker correctness (Section 12.2)
- [x] Add production SOP prompt injection (clearly demarcated inside the session-pinned protocol excerpt block)
- [x] Add deterministic evidence-packet scope analysis from canonical intervention action IDs
- [x] Expand `adapt_scenario_to_context()` into Layer 3 scoring for active SOP scope restrictions, contraindications, and explicit not-carried rules through generated checklist overlay items
- [x] Allow tag-based protocol excerpts to feed production chat prompts and debrief prompts through the session-pinned excerpt

**Phase 2B note (2026-05-03):** Authoritative runtime use is enabled only through `session.effective_protocol_excerpt`, built from the immutable protocol snapshot plus active agency SOP rows at session start. Scope-analysis rows are deterministic evidence-packet facts for debrief/audit. Active SOP `scope_restriction` rules generate `protocol_scope` checklist overlay items in `scope_adherence`; active SOP `contraindication` and `not_carried` rules generate `protocol_scope` checklist overlay items in `protocols_treatment`. Matching restricted, contraindicated, or explicitly unavailable interventions therefore affect `score_snapshot` through the standard deterministic scoring path. Broad `equipment_policy` prose and protocol-derived non-SOP scoring rules remain future expansion after their structured rule contracts are finalized. Successful Medical Control calls now emit trusted backend `medical_control_contact` session events, Tier 1 scoring can match `session_event` records generally, and `before_item` / `after_item` timing constraints are evaluated from timestamped evidence. Score-bearing "medical control required before intervention" SOP overlays still need an explicit rule generator before they should be enabled.

**Phase 2C Engineering — scale / paid-tier expansion:**
- [ ] Add PDF vision extraction (Pro/Enterprise tier; 5/month limit)
- [ ] Build fan-out queue for state base update propagation
- [ ] Write load tests for fan-out (Section 12.5)

**Phase 2C deferral decision (2026-05-03):** Phase 2C is not required to begin Phase 3. PDF extraction, state-base fan-out, and load testing are scale/paid-tier work. They should be triggered by pilot usage volume, multiple active agency protocol profiles, or a paid onboarding need that would make manual protocol authoring/review inefficient.

**Outcome:** Agency training accurately reflects local SOPs/custom profile rules. LLM prompt is token-efficient and scenario-relevant. Debrief output is consistent and immutable.

---

### Phase 3 — Multi-State Expansion

**Goal:** Enable agencies outside Michigan to train on jurisdiction-accurate protocols.

- [ ] Build internal AI-assisted state protocol draft generation CLI tool
- [ ] Establish clinical SME review process and contractor pipeline
- [ ] Publish first additional state base (target state: Ohio / OH)
- [ ] Implement Fork-and-Diff data model for structurally similar states
- [ ] Build paid state onboarding tier pricing and workflow
- [ ] Begin state EMS office partnership outreach
- [ ] Migrate existing Michigan-specific scenarios to `jurisdiction: national` where applicable
- [ ] Resolve HIPAA/BAA compliance posture before enabling agency-custom content in enterprise accounts

**Outcome:** Platform viable for agencies in any state. Michigan is no longer the only accurate jurisdiction.

---

## 14. Open Questions

| # | Question | Impact | Phase |
|---|---|---|---|
| 1 | ~~What is the canonical clinical concept taxonomy AND canonical intervention action ID vocabulary?~~ **RESOLVED FOR PHASE 2B PILOT (2026-05-03):** Registries live in `docs/clinical_concept_taxonomy.md` and `app/scenarios/vocabulary.py`; current scenarios are tagged and preview-tested. SME review approved the contract with revisions addressed. Runtime prompt/scoring/scope use still requires Phase 2B implementation and tests. | High | Resolved |
| 2 | ~~Who is the Clinical SME for the NASEMSO base authoring?~~ **RESOLVED (2026-04-17):** Jonathan Frastaci will serve as Clinical SME reviewer for Michigan base and NASEMSO content. For Phase 3 states outside Michigan, a contracted clinical reviewer is required. Phase 1A is unblocked. | High | ~~Phase 1A prerequisite~~ Resolved |
| 3 | ~~Small agency RBAC: What is the policy when a single person must serve as both Admin and Training Officer?~~ **RESOLVED FOR PHASE 2 (2026-05-02):** Self-approval is not allowed. One-person agencies can draft SOPs, but activation requires a second named agency reviewer or internal/Enterprise clinical review. | High | Resolved |
| 4 | ~~What technology stack for the compile-on-write worker? DB-backed job queue for Phase 1C; Redis/Celery for Phase 2 fan-out scale. Confirm sequencing is acceptable.~~ **RESOLVED FOR PHASE 1 (2026-05-02):** synchronous profile materialization with compile status/error/timestamp is sufficient for pilot scale. DB-backed queue is deferred until Phase 2 fan-out/state update propagation. | Medium | Phase 2 |
| 5 | ~~Change summary generation: template-based (Phase 2) vs. LLM-generated?~~ **RESOLVED FOR PHASE 2 (2026-05-02):** Template-based only. LLM-generated change summaries are deferred and may not become authoritative provider notifications without deterministic review. | Medium | Resolved |
| 6 | ~~Which state is the Phase 3 pilot target?~~ **RESOLVED (2026-05-03):** Ohio (OH) is the first non-Michigan state target. Phase 3 planning should determine whether Ohio is best authored as a fork/diff from NASEMSO or as a full state base, then estimate SME review time/cost from that decision. | Medium | Resolved |
| 7 | ~~Should RFC 6902 patch operations be validated against the base schema at write time or compile time?~~ **RESOLVED (2026-05-02):** Both. Write-time validation prevents bad/stale patches from entering the ledger; compile-time validation catches base-version drift and preserves the last known good snapshot on failure. | Medium | Resolved |
| 8 | ~~Protocol snapshot storage: full compiled JSON vs. diff chain only?~~ **RESOLVED (2026-05-02):** full compiled JSON with content hash. Patch chain remains in profile selection/patch tables for future recompilation. | Medium | Resolved |
| 9 | ~~Tiering strategy: which features belong to Free vs. Pro vs. Enterprise?~~ **INITIAL CONTRACT RESOLVED (2026-05-02):** Open/Free = generic/base profiles only; Pro Agency = profiles/manual SOP/PDF cap/template notices; Enterprise = assisted onboarding, one-person external review, higher caps, BAA/security review. Pricing still TBD. | High | Pricing TBD |
| 10 | Scenario library governance: will agencies eventually create custom scenarios? If so, what are the scoping, sharing, and taxonomy enforcement rules? | Low | Phase 3+ |
| 11 | ~~HIPAA/Compliance: when does a BAA become required?~~ **INITIAL CONTRACT RESOLVED (2026-05-02):** Protocol/SOP content must be no-PHI with attestation. Agencies requiring BAA/security review route to Enterprise/onboarding. Agency-authored custom scenarios remain deferred until separate PHI/BAA review. Legal review still required before enterprise sales. | High | Legal review TBD |
| 12 | ~~MCA Admin role: how are official regional MCA Admins credentialed and managed?~~ **RESOLVED FOR PHASE 2 (2026-05-02):** No public MCA Admin portal in Phase 2. Official MCA/shared regional authority and scope-expansion approvals use internal/superadmin-held review until credentialed MCA Admin governance is designed. | Medium | Resolved for Phase 2 |
| 13 | ~~**Legacy session migration:** Should existing sessions receive `legacy_protocol: true` or a best-effort retroactive snapshot?~~ **RESOLVED (2026-05-02):** Phase 1A Step 1 sets `legacy_protocol = True` on all existing rows via migration. No retroactive snapshot is created — existing sessions are non-verifiable for tamper evidence and are graded on the current protocol state if a debrief is generated. Confirm no retroactive snapshot is needed before the migration runs. | Low | Resolved |
| 14 | ~~**Resolver scope — single protocol vs. compiled context:** `get_resolved_protocol()` currently resolves one protocol at a time by ID. The V2 snapshot contains the full compiled agency context. At what point does the resolver need to return a compiled multi-protocol context rather than individual protocol objects? Does this change the interface contract?~~ **RESOLVED FOR PHASE 1 (2026-05-02):** session snapshotting stores the compiled profile context; legacy single-protocol lookup remains for scenario file refs. Prompt tree-shaking/scope analysis may add an excerpt resolver in Phase 2 without changing Phase 1 session immutability. | Medium | Resolved |
| 15 | **User acquisition path:** How do real EMS providers and training officers find the product? Answering this determines the timeline for everything in this document. Without an acquisition path, Phase 1B may never have a gate to open. | High | Now |
| 16 | ~~**Protocol Profile assignment:** If an agency has multiple active profiles, are members assigned a default profile, allowed to choose at session start, or assigned by training track/category?~~ **RESOLVED (2026-05-02):** Agency members inherit the agency default profile unless an agency admin assigns another active profile from the same agency. Default-inherited members follow agency default changes; manual assignments stay pinned. Students do not self-select agency protocol profiles at session start. Training-track/category assignment is deferred. | Medium | Resolved |

---

*This document is a living planning artifact. The full V2 architecture is the correct destination. Phase 1 and Phase 2A/2B are complete for pilot use. Phase 2C scale features are deferred until volume/paid-tier demand justifies them. The immediate protocol expansion priority is Phase 3 Ohio planning, SME workflow, and first-state authoring strategy.*
