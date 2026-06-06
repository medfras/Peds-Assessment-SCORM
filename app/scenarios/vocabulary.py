from __future__ import annotations

"""
Scenario vocabulary — stable identifier registry.

IDs are internal and stable. Labels are display-facing and may change without
breaking scoring or runtime logic. Never compare against labels in code; always
use the ID as the key. Labels are resolved through this registry for display only.

ID format: flat snake_case keys (e.g. albuterol_svn, clinical_performance).
The logical groupings below are for documentation purposes only — they are NOT
literal key prefixes. Do not use dot-notation keys in scenario JSON or code.

  Group: interventions — clinical interventions available in vitals.interventions
  Group: rubric        — scoring dimensions in scoring_rubric
  Group: out_of_scope  — intervention categories always outside BLS scope

Labels in this registry are authoritative. If vitals.interventions[key].label
diverges from INTERVENTIONS[key], validation logs a warning at load time.
The vocabulary label is the source of truth; the scenario JSON label must match
it exactly. A mismatch is a drift error, not an intentional override.

Load-time validation (see validate_scenario()) enforces:
  - vitals.interventions keys must be registered in INTERVENTIONS
  - scoring_rubric keys must be registered in RUBRIC_DIMENSIONS
  - lung_sound_challenge.post_treatment.requires_intervention_id (if present)
    must be registered in INTERVENTIONS

Migration note:
  lung_sound_challenge.post_treatment.requires_treatment_label is deprecated.
  New scenarios must use requires_intervention_id instead. Existing scenarios
  using requires_treatment_label are still supported but should be migrated.
"""

# ── In-scope BLS interventions ─────────────────────────────────────────────────
# Keys are the stable IDs used in vitals.interventions blocks.
# Values are the display labels shown in the UI and debrief.
INTERVENTIONS: dict[str, str] = {
    "abdominal_assessment": "Abdominal Assessment — Gentle Palpation",
    "aggressive_palpation": "Aggressive Abdominal Compression/Repeated Palpation",
    "airway_assessment": "Inhalation Injury Screen",
    "airway_bvm_reassess": "Reassess airway / BVM ventilation",
    "airway_suction": "Suction airway",
    "albuterol_mdi_patient_assisted": "Patient-assisted albuterol MDI (patient's own prescription)",
    "albuterol_svn": "Albuterol 2.5 mg via SVN (nebulizer)",
    "aspirin_po": "Aspirin 324 mg PO (4 × 81 mg chewable)",
    "als_intercept": "ALS intercept acknowledged",
    "assess_cms": "CMS Assessment — Pre-Splint",
    "assess_cms_post": "CMS Re-Assessment — Post-Splint",
    "back_blows": "Back Blows / Chest Thrusts",
    "bvm": "BVM ventilation",
    "calculate_bsa": "Estimate Burn BSA",
    "calm_environment": "Minimize stimulation — calm environment",
    "cooling_measures": "Cooling — remove excess clothing and blankets",
    "cpap": "CPAP (Continuous Positive Airway Pressure)",
    "direct_pressure": "Direct Pressure & Pressure Dressing",
    "dry_dressing": "Apply Dry Sterile Dressing",
    "encourage_coughing": "Encourage Coughing",
    "ekg_monitoring": "Cardiac Monitor — 4-Lead",
    "epi_draw_up": "Epinephrine 1:1,000 IM (draw-up)",
    "epinephrine_im": "Epinephrine 0.15 mg IM (draw-up)",
    "ice_pack": "Cold Pack Application",
    "head_tilt_chin_lift": "Head-Tilt / Chin-Lift Airway Maneuver",
    "blood_glucose_check": "Blood Glucose Check — Fingerstick (glucometer)",
    "dcap_btls_head_neck": "DCAP-BTLS Assessment — Head, Neck, and Cervical Spine",
    "jaw_thrust": "Jaw Thrust Airway Maneuver",
    "load_and_go": "Load and Go / Rapid Transport Decision",
    "naloxone_im": "Naloxone 0.4–2 mg IM (vastus lateralis)",
    "naloxone_in": "Naloxone 2 mg intranasal (MAD atomizer)",
    "neuro_assessment": "Neurological Assessment (GCS/AVPU + Pupils)",
    "o2_blowby": "Blow-by O2 (NRB mask held near face, high flow)",
    "o2_nc": "Supplemental O2 via nasal cannula",
    "o2_nrb": "High-flow O2 via NRB mask (15 LPM)",
    "o2_supplemental": "Supplemental O2 — nasal cannula",
    "oral_glucose": "Oral glucose gel administered",
    "pelvic_binder": "Pelvic Binder Application",
    "pms": "PMS Assessment - Pulse, Movememnt, Sensation",
    "position_of_comfort": "Position of Comfort — Semi-Recumbent",
    "positioning": "Position of comfort — sitting upright",
    "positioning_supine": "Position supine, legs elevated (Trendelenburg-modified)",
    "protect_from_injury": "Protect from injury — clear hazards, no restraint, nothing in mouth",
    "prevent_hypothermia": "Cover Patient / Prevent Hypothermia",
    "racepinephrine_svn": "Racepinephrine 2.25% via SVN (nebulized)",
    "12_lead_ecg": "12-Lead ECG",
    "waveform_capnography": "Waveform Capnography (ETCO2)",
    "rapid_transport": "Priority Transport with ALS Intercept",
    "realign_fracture": "Gentle Fracture Realignment",
    "recovery_position": "Recovery position — lateral recumbent",
    "remove_clothing": "Remove Wet Clothing",
    "remove_stinger": "Remove bee stinger from right forearm",
    "smr": "Spinal Motion Restriction",
    "splinting": "Forearm Splint — Padded Board or SAM Splint",
    "supraglottic_airway_insert": "Supraglottic airway insertion",
    "suction_airway": "Suction airway — oral suctioning for secretions",
    "wet_dressing": "Apply Wet/Moist Dressing",
}

# Backward-compatible UI intervention aliases. Keep legacy keys loadable, but
# collapse them before future evidence-packet action matching so one clinical
# action cannot be double-counted.
INTERVENTION_ALIASES: dict[str, str] = {
    "high_flow_o2": "o2_nrb",
}

# ── Intervention paraphrase patterns ─────────────────────────────────────────
# Used by app/corroboration.py to match free-text documentation claims against
# applied intervention IDs without requiring exact label matches.
#
# Keys: stable intervention IDs from INTERVENTIONS above.
# Values: lists of lowercase substrings matched case-insensitively against
#   documentation text. A claim text containing ANY entry is considered a
#   mention of that intervention.
#
# Coverage: interventions used across the 10 clinical calibration scenarios +
# common oxygen/delivery and albuterol variants. Extend conservatively — add
# new entries when a false positive or false negative is confirmed in testing,
# not preemptively.
INTERVENTION_PARAPHRASE_PATTERNS: dict[str, list[str]] = {
    # ── Albuterol / bronchodilator ─────────────────────────────────────────────
    "albuterol_svn": [
        "albuterol", "breathing treatment", "nebulizer", "neb treatment",
        "svn", "small volume nebulizer", "bronchodilator", "aerosol treatment",
    ],
    "albuterol_mdi_patient_assisted": [
        "albuterol", "inhaler", "mdi", "metered dose inhaler", "rescue inhaler",
    ],
    # ── Oxygen delivery ───────────────────────────────────────────────────────
    "o2_nrb": [
        "non-rebreather", "nonrebreather", "non rebreather", "nrb",
        "high-flow oxygen", "high flow oxygen", "high flow o2", "15 lpm",
        "15l oxygen", "nrb mask",
        # generic oxygen terms cross-listed → multi-match with o2_nc/o2_blowby/o2_supplemental
        "supplemental oxygen", "supplemental o2", "oxygen",
    ],
    "o2_nc": [
        "nasal cannula", "nasal cannula oxygen", "low-flow oxygen",
        # generic oxygen terms cross-listed → multi-match
        "supplemental oxygen", "supplemental o2", "oxygen",
    ],
    "o2_blowby": [
        "blow-by", "blow by", "blowby", "held near face", "wafting",
        # generic oxygen terms cross-listed → multi-match
        "supplemental oxygen", "supplemental o2", "oxygen",
    ],
    "o2_supplemental": [
        "supplemental oxygen", "supplemental o2", "oxygen",
    ],
    # ── Epinephrine ───────────────────────────────────────────────────────────
    "epinephrine_im": [
        "epinephrine", "epi", "epipen", "auto-injector", "autoinjector",
        "intramuscular epinephrine", "im epi", "0.15 mg",
    ],
    # ── Naloxone ──────────────────────────────────────────────────────────────
    "naloxone_in": [
        "naloxone", "narcan", "intranasal naloxone", "nasal naloxone",
        "mad", "nasal atomizer", "in naloxone",
    ],
    "naloxone_im": [
        "naloxone", "narcan", "intramuscular naloxone", "im naloxone",
    ],
    # ── Glucose ───────────────────────────────────────────────────────────────
    "oral_glucose": [
        "oral glucose", "glucose gel", "instaglucose", "dextrose gel",
        "oral dextrose",
    ],
    # ── ALS intercept ─────────────────────────────────────────────────────────
    "als_intercept": [
        "als intercept", "als requested", "advanced life support intercept",
        "called for als", "requested als",
    ],
    # ── Positioning ───────────────────────────────────────────────────────────
    "positioning": [
        "position of comfort", "sitting upright", "upright position",
        "semi-fowler", "fowler",
    ],
    "positioning_supine": [
        "supine", "lying flat", "legs elevated", "trendelenburg",
        "position supine",
    ],
    "recovery_position": [
        "recovery position", "lateral recumbent", "on their side",
        "on her side", "on his side", "side-lying",
    ],
    # ── BVM / airway maneuvers ────────────────────────────────────────────────
    "bvm": [
        "bvm", "bag valve mask", "bag-valve-mask", "bag mask ventilation",
        "assisted ventilation", "bagging", "bvm ventilation",
    ],
    "airway_bvm_reassess": [
        "reassess airway", "bvm reassess", "chest rise", "ventilation reassessment",
    ],
    "airway_suction": [
        "suction airway", "airway suction", "suctioning", "clear secretions",
    ],
    "head_tilt_chin_lift": [
        "head-tilt chin-lift", "head tilt chin lift", "head tilt", "chin lift",
    ],
    "jaw_thrust": [
        "jaw thrust", "jaw-thrust",
    ],
    "supraglottic_airway_insert": [
        "supraglottic airway", "i-gel", "igel", "sg airway",
    ],
    # ── Trauma interventions ──────────────────────────────────────────────────
    "direct_pressure": [
        "direct pressure", "pressure dressing", "hemorrhage control",
        "pressure to wound", "wound pressure",
    ],
    "dry_dressing": [
        "dry dressing", "sterile dressing", "burn dressing",
        "dry sterile dressing",
    ],
    "pelvic_binder": [
        "pelvic binder", "pelvic stabilization", "pelvis stabilized",
        "binder applied",
    ],
    "splinting": [
        "splint", "splinted", "immobilized fracture", "board splint",
        "sam splint", "padded splint",
    ],
    "realign_fracture": [
        "realign", "fracture realignment", "gentle realignment",
        "gentle traction", "traction realignment",
    ],
    "prevent_hypothermia": [
        "blanket", "prevent hypothermia", "cover patient",
        "keep warm", "prevent heat loss",
    ],
    # ── Cardiac monitoring ────────────────────────────────────────────────────
    "ekg_monitoring": [
        "cardiac monitor", "4-lead", "4 lead ekg", "ekg applied",
        "ecg monitor",
    ],
    "12_lead_ecg": [
        "12-lead", "12 lead", "twelve lead", "12-lead ecg",
    ],
    # ── Aspirin ───────────────────────────────────────────────────────────────
    "aspirin_po": [
        "aspirin", "asa", "324 mg aspirin",
    ],
    # ── Blood glucose ─────────────────────────────────────────────────────────
    "blood_glucose_check": [
        "blood glucose", "glucose check", "fingerstick", "glucometer",
        "blood sugar check", "bgl check",
    ],
    # ── Neurological assessment ───────────────────────────────────────────────
    "neuro_assessment": [
        "neuro assessment", "neurological assessment", "pupils checked",
        "gcs assessed", "avpu",
    ],
    # ── Load and go / transport ───────────────────────────────────────────────
    "load_and_go": [
        "load and go", "rapid transport", "priority transport",
        "load-and-go", "rapid extrication",
    ],
}

# ── Out-of-scope intervention categories ──────────────────────────────────────
# Stable IDs for categories referenced in out_of_scope_bls arrays.
# New scenarios should use these IDs in out_of_scope_bls instead of free text.
# Existing scenarios using free text are still supported but should be migrated.
OUT_OF_SCOPE: dict[str, str] = {
    "iv_io_access": "IV/IO Access (ALS skill)",
    "iv_fluid_resuscitation": "IV Fluid Resuscitation (ALS skill)",
    "iv_pain_medication": "IV/IM Pain Medication (ALS skill)",
    "endotracheal_intubation": "Endotracheal Intubation (ALS skill)",
    "advanced_airway_als": "Advanced Airway — ETT/LMA (ALS skill)",
    "direct_laryngoscopy": "Direct Laryngoscopy / Magill Forceps (ALS/Paramedic skill)",
    "chest_decompression": "Chest Needle Decompression (ALS/Paramedic skill)",
    "dextrose_iv_io": "Dextrose IV/IO (ALS skill)",
    "push_dose_epinephrine": "Push-dose Epinephrine IV/IO (ALS/Paramedic skill)",
    "epinephrine_nebulized_als": "Nebulized Epinephrine — ALS dose (not protocol-indicated at BLS)",
    "racepinephrine_als": "Racepinephrine 2.25% SVN (Paramedic skill — not on this unit)",
    "glucagon_im_in": "Glucagon IM/IN (Paramedic scope)",
    "midazolam": "Midazolam (Paramedic scope)",
    "diphenhydramine_im_iv": "Diphenhydramine IM/IV (ALS skill)",
    "methylprednisolone": "Methylprednisolone IV/IO/IM (ALS skill)",
    "dexamethasone": "Dexamethasone PO/IM (ED/ALS — not a prehospital BLS intervention)",
    "magnesium_sulfate": "Magnesium Sulfate Infusion (ALS skill)",
    "mannitol": "Mannitol or Hyperosmolar Therapy (ALS/hospital skill)",
    "albuterol_ipratropium_combo": "Albuterol/Ipratropium Combination (Paramedic only)",
    "heliox": "Heliox (ALS/hospital therapy)",
    "sedation_paralytic": "Sedation or Paralytic Agents (ALS skill)",
    "blood_products": "Blood Product Administration (ALS skill)",
    "blood_glucose_independent": "Blood Glucose Check Independent (MFR scope — EMT defers to ALS)",
    "epinephrine_not_indicated_asthma": "Epinephrine IM — not indicated for isolated bronchospasm (reserve for anaphylaxis)",
    "insulin_pump": "Insulin Pump Programming or Suspension (endocrinology/ALS decision)",
    "12_lead_ecg": "12-Lead ECG (Paramedic skill)",
    "ekg_monitoring": "EKG Monitoring (Paramedic/AEMT skill)",
    "waveform_capnography": "Waveform Capnography (Paramedic/AEMT skill)",
    # ALS-only interventions — for use in out_of_scope_bls/aemt/paramedic on ALS/transport scenarios
    "iv_io_access_als_only": "IV/IO Access — ALS-only skill at this scope level",
    "advanced_airway_als_only": "Advanced Airway (RSI / surgical airway) — ALS only",
    "cardiac_pacing_als_only": "External Cardiac Pacing — ALS only",
    "cardioversion_als_only": "Synchronized Cardioversion — ALS only",
    "antiarrhythmic_als_only": "Antiarrhythmic Medications (amiodarone, adenosine, lidocaine, etc.) — ALS only",
    "vasopressor_als_only": "Vasopressors (dopamine, epinephrine infusion, norepinephrine) — ALS only",
    "fibrinolytic_als_only": "Fibrinolytic Therapy — ALS only; requires hospital authorization",
    "oral_glucose_contraindicated": "Oral Glucose — contraindicated (patient cannot protect airway)",
    "albuterol_contraindicated_croup": "Albuterol SVN — not indicated for croup (upper airway, not lower airway bronchospasm)",
    "suturing": "Suturing or Wound Closure",
    "aggressive_fracture_manipulation": "Repeated or Forceful Fracture Manipulation (only one gentle realignment attempt appropriate)",
    "burn_ointments": "Applying Ointments, Creams, or Butter to Burns",
    "rupture_blisters": "Rupturing Blisters",
    "wet_dressings_large_burns": "Wet Dressings on Large Burns (contraindicated — hypothermia risk)",
    "abdominal_compression": "Applying Pressure to Abdomen for Hemorrhage Control (not effective for intra-abdominal hemorrhage)",
    "prehospital_wound_closure": "Prehospital Wound Closure (wound irrigation and dressing only)",
}

# ── Rubric scoring dimensions ──────────────────────────────────────────────────
# These are the universal scoring axes applied across all scenarios.
# Custom scenario-specific overrides are applied on top of this base structure.
RUBRIC_DIMENSIONS: dict[str, str] = {
    "clinical_performance": "Clinical Performance",
    "protocols_treatment": "Protocols & Treatment",
    "narrative": "ePCR / CHART Narrative",
    "scope_adherence": "Scope of Practice Adherence",
    "dmist": "DMIST Handoff",
    "professionalism": "Professionalism / Safety",
}

# ── Recommended action IDs ────────────────────────────────────────────────────
# Stable IDs for correct_treatment.recommended_actions[].id entries.
# These are durable runtime concepts — not convenience labels. If an ID is added
# here, the scenario JSON, scoring logic, and docs must treat it consistently.
#
# Note: existing scenarios may use pre-registration IDs (e.g. "hospital_notification")
# that are not yet in this registry. Those remain supported. New scenarios must use
# IDs from this registry. Validation is not yet enforced for recommended_action IDs
# (consistent with the out_of_scope_bls migration approach).
RECOMMENDED_ACTIONS: dict[str, str] = {
    # Transport and handoff
    "hospital_pre_arrival_notification": "Hospital Pre-Arrival Notification",
    "als_intercept_requested": "ALS Intercept Requested",
    "transport_destination_verbalized": "Transport Destination Verbalized to Patient/Family",
    # ALS monitoring
    "cardiac_monitoring_applied": "Cardiac Monitor (4-Lead) Applied",
    "twelve_lead_ecg_performed": "12-Lead ECG Performed and Interpreted",
    "waveform_capnography_applied": "Waveform Capnography (ETCO2) Applied",
}

# ── Phase 2 protocol/scenario tagging taxonomy ────────────────────────────────
#
# CLINICAL_CONCEPTS and INTERVENTION_ACTIONS are the Phase 2 contract that lets
# protocol tree-shaking and scope analysis reason over stable IDs instead of
# display labels. These registries are intentionally additive for now: scenario
# load validation does not yet require clinical_context tags, and runtime scoring
# does not yet derive deductions from INTERVENTION_ACTIONS.
#
# Authoring rules:
#   - scenario clinical_context.concepts must use IDs from CLINICAL_CONCEPTS
#   - protocol node tags must use IDs from CLINICAL_CONCEPTS
#   - scope analysis must use INTERVENTION_ACTIONS, not intervention labels
#   - action IDs may map to one or more UI intervention IDs when applicable

CLINICAL_CONCEPTS: dict[str, dict[str, str]] = {
    # Universal assessment / operations
    "scene_safety": {"label": "Scene Safety", "category": "assessment"},
    "ppe_precautions": {"label": "PPE Precautions", "category": "assessment"},
    "primary_survey": {"label": "Primary Survey", "category": "assessment"},
    "patient_assessment": {"label": "Patient Assessment", "category": "assessment"},
    "vital_signs": {"label": "Vital Signs", "category": "assessment"},
    "transport_decision": {"label": "Transport Decision", "category": "operations"},
    "medical_control": {"label": "Medical Control", "category": "operations"},
    "documentation_handoff": {"label": "Documentation and Handoff", "category": "operations"},
    "infectious_disease_precautions": {"label": "Infectious Disease Precautions", "category": "operations"},
    "interfacility_transfer": {"label": "Interfacility Transfer", "category": "operations"},
    "quality_improvement_review": {"label": "Quality Improvement Review", "category": "operations"},
    # Airway / breathing
    "airway_management": {"label": "Airway Management", "category": "airway_breathing"},
    "oxygen_therapy": {"label": "Oxygen Therapy", "category": "airway_breathing"},
    "ventilation_support": {"label": "Ventilation Support", "category": "airway_breathing"},
    "respiratory_distress": {"label": "Respiratory Distress", "category": "airway_breathing"},
    "bronchospasm": {"label": "Bronchospasm / Wheeze", "category": "airway_breathing"},
    "pulmonary_edema": {"label": "Pulmonary Edema", "category": "airway_breathing"},
    "croup": {"label": "Croup", "category": "airway_breathing"},
    "upper_airway_obstruction": {"label": "Upper Airway Obstruction", "category": "airway_breathing"},
    "foreign_body_airway_obstruction": {"label": "Foreign Body Airway Obstruction", "category": "airway_breathing"},
    "tension_pneumothorax": {"label": "Tension Pneumothorax", "category": "airway_breathing"},
    # Cardiovascular / perfusion
    "cardiac_arrest": {"label": "Cardiac Arrest", "category": "cardiovascular"},
    "cpr": {"label": "CPR", "category": "cardiovascular"},
    "high_performance_cpr": {"label": "High-Performance CPR", "category": "cardiovascular"},
    "rosc": {"label": "Return of Spontaneous Circulation (ROSC)", "category": "cardiovascular"},
    "chest_pain_acs": {"label": "Chest Pain / ACS", "category": "cardiovascular"},
    "stemi": {"label": "STEMI", "category": "cardiovascular"},
    "syncope": {"label": "Syncope", "category": "cardiovascular"},
    "stroke": {"label": "Stroke / CVA", "category": "cardiovascular"},
    "bradycardia": {"label": "Bradycardia", "category": "cardiovascular"},
    "tachycardia": {"label": "Tachycardia", "category": "cardiovascular"},
    "shock": {"label": "Shock / Hypoperfusion", "category": "cardiovascular"},
    "cardiac_monitoring": {"label": "Cardiac Monitoring", "category": "cardiovascular"},
    # Neurologic / metabolic / toxicologic
    "altered_mental_status": {"label": "Altered Mental Status", "category": "neurologic"},
    "neurological_assessment": {"label": "Neurological Assessment", "category": "neurologic"},
    "gcs_assessment": {"label": "GCS Assessment", "category": "neurologic"},
    "gcs": {"label": "Glasgow Coma Scale", "category": "neurologic"},
    "seizure": {"label": "Seizure", "category": "neurologic"},
    "febrile_seizure": {"label": "Febrile Seizure", "category": "neurologic"},
    "hypoglycemia": {"label": "Hypoglycemia", "category": "metabolic"},
    "blood_glucose": {"label": "Blood Glucose Assessment", "category": "metabolic"},
    "sepsis": {"label": "Sepsis", "category": "infection"},
    "toxins_overdose": {"label": "Toxins / Overdose", "category": "toxicology"},
    "opioid_overdose": {"label": "Opioid Overdose", "category": "toxicology"},
    # Behavioral / psychiatric
    "behavioral_psychiatric_crisis": {"label": "Behavioral / Psychiatric Crisis", "category": "behavioral"},
    "severe_agitation": {"label": "Severe Agitation / Agitated Delirium", "category": "behavioral"},
    "chemical_restraint": {"label": "Chemical Restraint", "category": "behavioral"},
    "behavioral_assessment": {"label": "Behavioral Assessment", "category": "behavioral"},
    # Obstetrics / gynecology
    "obstetric_emergency": {"label": "Obstetric Emergency", "category": "obstetrics_gynecology"},
    "imminent_delivery": {"label": "Imminent Delivery", "category": "obstetrics_gynecology"},
    "neonatal_resuscitation": {"label": "Neonatal Resuscitation", "category": "obstetrics_gynecology"},
    "postpartum_hemorrhage": {"label": "Postpartum Hemorrhage", "category": "obstetrics_gynecology"},
    "preeclampsia_eclampsia": {"label": "Preeclampsia / Eclampsia", "category": "obstetrics_gynecology"},
    # Allergy / immunology
    "anaphylaxis": {"label": "Anaphylaxis", "category": "allergy_immunology"},
    "allergic_reaction": {"label": "Allergic Reaction", "category": "allergy_immunology"},
    # Trauma / environmental
    "trauma": {"label": "Trauma", "category": "trauma"},
    "bleeding_control": {"label": "Bleeding Control", "category": "trauma"},
    "soft_tissue_injury": {"label": "Soft Tissue Injury", "category": "trauma"},
    "extremity_injury": {"label": "Extremity Injury", "category": "trauma"},
    "fracture_splinting": {"label": "Fracture Splinting", "category": "trauma"},
    "burns": {"label": "Burns", "category": "trauma"},
    "spinal_motion_restriction": {"label": "Spinal Motion Restriction", "category": "trauma"},
    "head_injury": {"label": "Head Injury", "category": "trauma"},
    "traumatic_brain_injury": {"label": "Traumatic Brain Injury", "category": "trauma"},
    "abdominal_trauma": {"label": "Abdominal Trauma", "category": "trauma"},
    "multisystem_trauma": {"label": "Multisystem Trauma", "category": "trauma"},
    "hypothermia_prevention": {"label": "Hypothermia Prevention", "category": "environmental"},
    "hypothermia": {"label": "Hypothermia", "category": "environmental"},
    "frostbite": {"label": "Frostbite", "category": "environmental"},
    "heat_illness": {"label": "Heat Illness", "category": "environmental"},
    "heat_exposure": {"label": "Heat Exposure / Heat Illness Mechanism", "category": "environmental"},
    # Pediatrics
    "pediatric_patient": {"label": "Pediatric Patient", "category": "pediatrics"},
    "pediatric_respiratory_distress": {"label": "Pediatric Respiratory Distress", "category": "pediatrics"},
    "pediatric_cardiac_arrest": {"label": "Pediatric Cardiac Arrest", "category": "pediatrics"},
    "pediatric_trauma": {"label": "Pediatric Trauma", "category": "pediatrics"},
    "child_abuse_neglect": {"label": "Child Abuse / Neglect", "category": "pediatrics"},
    "non_accidental_trauma": {"label": "Non-Accidental Trauma", "category": "pediatrics"},
    "ten_4_bruising_pattern": {"label": "TEN-4 Bruising Pattern", "category": "pediatrics"},
    "child_abuse_recognition": {"label": "Child Abuse Recognition", "category": "pediatrics"},
    "patient_behavior_assessment": {"label": "Patient Behavior Assessment", "category": "pediatrics"},
    "inconsistent_history": {"label": "Inconsistent History", "category": "pediatrics"},
    # Documentation / operations
    "mandatory_reporting": {"label": "Mandatory Reporting", "category": "operations"},
    "objective_documentation": {"label": "Objective Documentation", "category": "operations"},
}

INTERVENTION_ACTIONS: dict[str, dict[str, object]] = {
    "airway_assessment": {
        "label": "Assess airway",
        "category": "airway_breathing",
        "intervention_ids": ["airway_assessment"],
    },
    "airway_open_head_tilt_chin_lift": {
        "label": "Open airway with head-tilt/chin-lift",
        "category": "airway_breathing",
        "intervention_ids": ["head_tilt_chin_lift"],
    },
    "airway_open_jaw_thrust": {
        "label": "Open airway with jaw thrust",
        "category": "airway_breathing",
        "intervention_ids": ["jaw_thrust"],
    },
    "airway_suction": {
        "label": "Suction airway",
        "category": "airway_breathing",
        "intervention_ids": ["suction_airway"],
    },
    "oxygen_supplemental": {
        "label": "Apply supplemental oxygen",
        "category": "airway_breathing",
        "intervention_ids": ["o2_supplemental", "o2_nc", "o2_blowby"],
    },
    "oxygen_high_flow_nrb": {
        "label": "Apply high-flow oxygen by NRB",
        "category": "airway_breathing",
        "intervention_ids": ["o2_nrb"],
    },
    "ventilation_bvm": {
        "label": "Provide BVM ventilation",
        "category": "airway_breathing",
        "intervention_ids": ["bvm"],
    },
    "cpr_initiate": {
        "label": "Initiate CPR",
        "category": "resuscitation",
        "intervention_ids": [],
    },
    "pulse_check": {
        "label": "Check pulse",
        "category": "assessment",
        "intervention_ids": [],
    },
    "aed_apply_use": {
        "label": "Apply/use AED",
        "category": "electrical_therapy",
        "intervention_ids": [],
    },
    "oral_airway_opa_insert": {
        "label": "Insert oral airway / OPA",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "opa_insert": {
        "label": "Insert oral airway / OPA",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "nasal_airway_npa_insert": {
        "label": "Insert nasal airway / NPA",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "npa_insert": {
        "label": "Insert nasal airway / NPA",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "supraglottic_airway_insertion": {
        "label": "Insert supraglottic airway",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "supraglottic_airway_insert": {
        "label": "Insert supraglottic airway",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "endotracheal_intubation": {
        "label": "Perform endotracheal intubation",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "cricothyrotomy": {
        "label": "Perform cricothyrotomy",
        "category": "airway_breathing",
        "intervention_ids": [],
    },
    "cpap_apply": {
        "label": "Apply CPAP",
        "category": "airway_breathing",
        "intervention_ids": ["cpap"],
    },
    "albuterol_administer": {
        "label": "Administer albuterol",
        "category": "medication",
        "intervention_ids": ["albuterol_svn", "albuterol_mdi_patient_assisted"],
    },
    "racepinephrine_administer": {
        "label": "Administer nebulized racepinephrine",
        "category": "medication",
        "intervention_ids": ["racepinephrine_svn"],
    },
    "epinephrine_im_administer": {
        "label": "Administer IM epinephrine",
        "category": "medication",
        "intervention_ids": ["epinephrine_im", "epi_draw_up"],
    },
    "naloxone_administer": {
        "label": "Administer naloxone",
        "category": "medication",
        "intervention_ids": ["naloxone_in", "naloxone_im"],
    },
    "oral_glucose_administer": {
        "label": "Administer oral glucose",
        "category": "medication",
        "intervention_ids": ["oral_glucose"],
    },
    "aspirin_administer": {
        "label": "Administer aspirin",
        "category": "medication",
        "intervention_ids": ["aspirin_po"],
    },
    "narcotic_analgesia_administer": {
        "label": "Administer narcotic analgesia",
        "category": "medication",
        "intervention_ids": [],
    },
    "benzodiazepine_administer": {
        "label": "Administer benzodiazepine",
        "category": "medication",
        "intervention_ids": [],
    },
    "antiarrhythmic_administer": {
        "label": "Administer antiarrhythmic",
        "category": "medication",
        "intervention_ids": [],
    },
    "blood_glucose_check": {
        "label": "Check blood glucose",
        "category": "assessment",
        "intervention_ids": ["blood_glucose_check"],
    },
    "intravenous_access_establish": {
        "label": "Establish intravenous access",
        "category": "vascular_access",
        "intervention_ids": [],
    },
    "intraosseous_access_establish": {
        "label": "Establish intraosseous access",
        "category": "vascular_access",
        "intervention_ids": [],
    },
    "cardiac_monitor_apply": {
        "label": "Apply cardiac monitor",
        "category": "monitoring",
        "intervention_ids": ["ekg_monitoring"],
    },
    "twelve_lead_ecg_acquire": {
        "label": "Acquire 12-lead ECG",
        "category": "monitoring",
        "intervention_ids": ["12_lead_ecg"],
    },
    "waveform_capnography_apply": {
        "label": "Apply waveform capnography",
        "category": "monitoring",
        "intervention_ids": ["waveform_capnography"],
    },
    "defibrillation_aed": {
        "label": "Defibrillate using AED",
        "category": "electrical_therapy",
        "intervention_ids": [],
    },
    "defibrillation_manual": {
        "label": "Defibrillate manually",
        "category": "electrical_therapy",
        "intervention_ids": [],
    },
    "synchronized_cardioversion": {
        "label": "Perform synchronized cardioversion",
        "category": "electrical_therapy",
        "intervention_ids": [],
    },
    "transcutaneous_pacing": {
        "label": "Perform transcutaneous pacing",
        "category": "electrical_therapy",
        "intervention_ids": [],
    },
    "bleeding_control_direct_pressure": {
        "label": "Control bleeding with direct pressure",
        "category": "trauma",
        "intervention_ids": ["direct_pressure"],
    },
    "tourniquet_apply": {
        "label": "Apply tourniquet",
        "category": "trauma",
        "intervention_ids": [],
    },
    "wound_packing_hemostatic": {
        "label": "Pack wound with hemostatic gauze",
        "category": "trauma",
        "intervention_ids": [],
    },
    "chest_seal_apply": {
        "label": "Apply chest seal",
        "category": "trauma",
        "intervention_ids": [],
    },
    "dry_dressing_apply": {
        "label": "Apply dry sterile dressing",
        "category": "trauma",
        "intervention_ids": ["dry_dressing"],
    },
    "wet_dressing_apply": {
        "label": "Apply wet/moist dressing",
        "category": "trauma",
        "intervention_ids": ["wet_dressing"],
    },
    "burn_bsa_estimate": {
        "label": "Estimate burn body surface area",
        "category": "trauma",
        "intervention_ids": ["calculate_bsa"],
    },
    "splint_apply": {
        "label": "Apply splint",
        "category": "trauma",
        "intervention_ids": ["splinting"],
    },
    "traction_splint_apply": {
        "label": "Apply traction splint",
        "category": "trauma",
        "intervention_ids": [],
    },
    "fracture_realign_gentle": {
        "label": "Perform one gentle fracture realignment attempt",
        "category": "trauma",
        "intervention_ids": ["realign_fracture"],
    },
    "cms_assess": {
        "label": "Assess CMS/PMS",
        "category": "trauma",
        "intervention_ids": ["assess_cms", "pms"],
    },
    "cms_reassess_post_splint": {
        "label": "Reassess CMS/PMS after splinting",
        "category": "trauma",
        "intervention_ids": ["assess_cms_post"],
    },
    "spinal_motion_restriction_apply": {
        "label": "Apply spinal motion restriction",
        "category": "trauma",
        "intervention_ids": ["smr"],
    },
    "pelvic_binder_apply": {
        "label": "Apply pelvic binder",
        "category": "trauma",
        "intervention_ids": ["pelvic_binder"],
    },
    "rapid_transport_initiate": {
        "label": "Initiate rapid transport",
        "category": "operations",
        "intervention_ids": ["rapid_transport", "load_and_go"],
    },
    "als_intercept_request": {
        "label": "Request ALS intercept",
        "category": "operations",
        "intervention_ids": ["als_intercept"],
    },
    "pat_perform": {
        "label": "Perform Pediatric Assessment Triangle",
        "category": "assessment",
        "intervention_ids": [],
    },
    "position_comfort": {
        "label": "Position patient for comfort",
        "category": "supportive_care",
        "intervention_ids": ["position_of_comfort", "positioning"],
    },
    "position_supine_legs_elevated": {
        "label": "Position supine with legs elevated",
        "category": "supportive_care",
        "intervention_ids": ["positioning_supine"],
    },
    "recovery_position": {
        "label": "Place patient in recovery position",
        "category": "supportive_care",
        "intervention_ids": ["recovery_position"],
    },
    "hypothermia_prevention": {
        "label": "Prevent hypothermia",
        "category": "supportive_care",
        "intervention_ids": ["prevent_hypothermia"],
    },
    "cooling_measures": {
        "label": "Initiate cooling measures",
        "category": "supportive_care",
        "intervention_ids": ["cooling_measures", "remove_clothing", "ice_pack"],
    },
    "calm_environment": {
        "label": "Minimize stimulation / calm environment",
        "category": "supportive_care",
        "intervention_ids": ["calm_environment"],
    },
}

# ── Agency equipment catalog ───────────────────────────────────────────────────
#
# EQUIPMENT_CATALOG — curated master list of equipment by category.
# MEDICATIONS_CATALOG — curated master list of medications (displayed separately in AI prompts).
# EQUIPMENT_ALIASES — maps normalized free-text variants to canonical catalog IDs.
#   Normalization: strip, lowercase, collapse whitespace, remove trailing punctuation.
#   Used by the migration pass-2 matcher to auto-resolve existing agency free-text entries.
#
# Prompt-format contract (authoritative — _build_agency_prompt_block must match):
#   "Equipment on this unit: <label>; <label>; ..."
#     - All items where carried=True and item_id NOT in MEDICATIONS_CATALOG
#     - Master items: label = EQUIPMENT_CATALOG[category][item_id]
#     - Custom items: label = item["label"] (stored in agency config)
#     - needs_review items are treated as carried — they appear here, not in NOT CARRIED
#
#   "Medications on this unit: <label>; <label>; ..."
#     - All items where carried=True and item_id IN MEDICATIONS_CATALOG
#     - Same label resolution rules as above
#
#   "NOT CARRIED — not available on this unit regardless of provider scope: <label>; <label>; ..."
#     - All items where carried=False, regardless of master/custom status
#     - Followed by the existing enforcement sentence (see _build_agency_prompt_block)
#
# Category keys match the existing agency config schema: airway, monitoring, trauma, other.

EQUIPMENT_CATALOG: dict[str, dict[str, str]] = {
    "airway": {
        "bvm_adult_peds_infant":     "BVM (adult, pediatric, infant)",
        "opa_npa_assorted":          "OPA/NPA assorted sizes",
        "suction_unit_portable":     "Suction unit (portable)",
        "suction_unit_onboard":      "Suction unit (on-board)",
        "oxygen_cylinder_d":         "Oxygen — D cylinder",
        "oxygen_cylinder_m":         "Oxygen — M cylinder",
        "nrb_mask":                  "NRB mask (adult and pediatric)",
        "nasal_cannula":             "Nasal cannula (adult and pediatric)",
        "svn_nebulizer_kit":         "Nebulizer (SVN) kit",
        "cpap_unit":                 "CPAP unit",
        "igel_supraglottic_airway":  "I-Gel supraglottic airway",
        "endotracheal_intubation_kit":"Endotracheal intubation kit",
        "cricothyrotomy_kit":        "Cricothyrotomy kit",
        "transport_ventilator":      "Transport ventilator",
    },
    "monitoring": {
        "pulse_oximeter":            "Pulse oximeter",
        "manual_bp_cuff_stethoscope":"Manual BP cuff and stethoscope",
        "blood_glucose_meter":       "Blood glucose meter",
        "aed":                       "AED",
        "cardiac_monitor_4lead":     "Cardiac monitor — 4-lead",
        "twelve_lead_ecg_device":    "12-lead ECG device",
        "capnography_device":        "Waveform capnography (ETCO2)",
        "thermometer_oral":          "Thermometer (oral)",
    },
    "trauma": {
        "tourniquets":               "Tourniquets",
        "pressure_bandages":         "Pressure bandages",
        "hemostatic_gauze":          "Hemostatic gauze",
        "trauma_dressings":          "Trauma dressings",
        "cervical_collars_assorted": "Cervical collars (assorted)",
        "long_backboard_straps":     "Long backboard and straps",
        "scoop_stretcher":           "Scoop stretcher",
        "pelvic_binder":             "Pelvic binder",
        "traction_splint":           "Traction splint",
        "burn_dressings":            "Burn dressings",
        "splint_kit":                "Splint kit (SAM/padded board)",
        "chest_seal":                "Chest seal",
        "sterile_water":             "Sterile water",
    },
    "other": {
        "stretcher":                 "Stretcher",
        "ob_kit_basic":              "OB kit (basic)",
        "broselow_tape":             "Broselow tape",
        "cold_packs":                "Cold packs",
        "hypothermia_prevention_kit":"Hypothermia prevention kit (blankets/wrap)",
        "auto_chest_compression":    "Automatic chest compression device (LUCAS)",
        "iv_start_kit":              "IV start kit",
        "io_drill_needle":           "IO drill and needles",
        "normal_saline_iv_fluids":   "Normal saline / IV fluids",
        "medication_pump_drip_set":  "Medication pump / drip set",
        "intranasal_atomizer":       "Intranasal atomizer / MAD device",
        "needle_decompression_kit":  "Needle decompression kit",
        "soft_restraints":           "Soft restraints",
    },
}

MEDICATIONS_CATALOG: dict[str, str] = {
    "albuterol_svn_unit_dose":    "Albuterol 2.5 mg / 3 mL unit-dose (SVN)",
    "oral_glucose_gel":           "Oral glucose gel",
    "epi_autoinjector_adult":     "Epinephrine auto-injector 0.3 mg (adult)",
    "epi_autoinjector_pediatric": "Epinephrine auto-injector 0.15 mg (pediatric)",
    "aspirin_324mg_chewable":     "Aspirin 324 mg chewable",
    "naloxone_2mg":               "Naloxone (Narcan) 2 mg/2 mL",
    "racepinephrine_svn":         "Racepinephrine 2.25% unit-dose (SVN)",
    "nitroglycerin_sl":           "Nitroglycerin 0.4 mg SL",
    "diphenhydramine_25mg_oral":  "Diphenhydramine 25 mg (oral)",
    "diphenhydramine_im_iv":      "Diphenhydramine IM/IV",
    "activated_charcoal":         "Activated charcoal",
    "epinephrine_1mg_ml":         "Epinephrine 1 mg/mL (1:1000) — draw-up",
    "push_dose_epinephrine":      "Push-dose epinephrine",
    "ondansetron_4mg_odt":        "Ondansetron 4 mg ODT",
    "ipratropium_svn":            "Ipratropium 0.5 mg unit-dose (SVN)",
    "albuterol_ipratropium_combo":"Albuterol + ipratropium (DuoNeb)",
    "dextrose_iv_io":             "Dextrose IV/IO",
    "glucagon_im_in":             "Glucagon IM/IN",
    "midazolam":                  "Midazolam",
    "diazepam":                   "Diazepam",
    "lorazepam":                  "Lorazepam",
    "methylprednisolone":         "Methylprednisolone",
    "dexamethasone":              "Dexamethasone",
    "magnesium_sulfate":          "Magnesium sulfate",
    "epinephrine_cardiac":        "Epinephrine 1:10,000 IV/IO",
    "adenosine":                  "Adenosine",
    "amiodarone":                 "Amiodarone",
    "lidocaine":                  "Lidocaine",
    "atropine":                   "Atropine",
    "calcium_chloride":           "Calcium chloride",
    "calcium_gluconate":          "Calcium gluconate",
    "sodium_bicarbonate":         "Sodium bicarbonate",
    "norepinephrine":             "Norepinephrine",
    "dopamine":                   "Dopamine",
    "epinephrine_infusion":       "Epinephrine infusion",
    "fentanyl":                   "Fentanyl",
    "morphine":                   "Morphine",
    "ketamine":                   "Ketamine",
    "txa":                        "Tranexamic acid (TXA)",
    "duodote":                    "Duodote / Mark I nerve agent antidote kit",
}

# Keys are normalized (strip, lowercase, collapse whitespace).
# Values are canonical IDs from EQUIPMENT_CATALOG or MEDICATIONS_CATALOG.
# Compound strings (e.g. "suction unit (portable and on-board)") map to the primary item only;
# the secondary item (on-board) remains unmatched and lands in the needs_review queue.
EQUIPMENT_ALIASES: dict[str, str] = {
    # Airway
    "bvm (adult, pediatric, infant)":              "bvm_adult_peds_infant",
    "bvm (adult and pediatric)":                   "bvm_adult_peds_infant",
    "bvm (adult & pediatric)":                     "bvm_adult_peds_infant",
    "opa/npa assorted sizes":                      "opa_npa_assorted",
    "opa / npa assorted sizes":                    "opa_npa_assorted",
    "suction unit (portable and on-board)":        "suction_unit_portable",
    "suction unit (portable & on-board)":          "suction_unit_portable",
    "suction unit (portable)":                     "suction_unit_portable",
    "suction (portable)":                          "suction_unit_portable",
    "suction unit (on-board)":                     "suction_unit_onboard",
    "oxygen — d and m cylinders":             "oxygen_cylinder_d",
    "oxygen - d and m cylinders":                  "oxygen_cylinder_d",
    "oxygen — d cylinder":                    "oxygen_cylinder_d",
    "oxygen - d cylinder":                         "oxygen_cylinder_d",
    "oxygen — m cylinder":                    "oxygen_cylinder_m",
    "oxygen - m cylinder":                         "oxygen_cylinder_m",
    "nrb mask (adult and pediatric)":              "nrb_mask",
    "nrb mask (adult & pediatric)":                "nrb_mask",
    "non-rebreather mask":                         "nrb_mask",
    "nasal cannula (adult and pediatric)":         "nasal_cannula",
    "nasal cannula (adult & pediatric)":           "nasal_cannula",
    "nasal cannula":                               "nasal_cannula",
    "nebulizer (svn) kit":                         "svn_nebulizer_kit",
    "svn nebulizer kit":                           "svn_nebulizer_kit",
    "cpap":                                        "cpap_unit",
    "cpap unit":                                   "cpap_unit",
    "i-gel":                                       "igel_supraglottic_airway",
    "igel":                                        "igel_supraglottic_airway",
    "i-gel supraglottic airway":                   "igel_supraglottic_airway",
    "supraglottic airway":                         "igel_supraglottic_airway",
    "sga":                                         "igel_supraglottic_airway",
    # Monitoring
    "pulse oximeter":                              "pulse_oximeter",
    "spo2 / pulse oximeter":                       "pulse_oximeter",
    "manual bp cuff and stethoscope":              "manual_bp_cuff_stethoscope",
    "manual bp cuff & stethoscope":                "manual_bp_cuff_stethoscope",
    "blood pressure cuff and stethoscope":         "manual_bp_cuff_stethoscope",
    "blood glucose meter":                         "blood_glucose_meter",
    "glucometer":                                  "blood_glucose_meter",
    "aed":                                         "aed",
    "automated external defibrillator":            "aed",
    "cardiac monitor 4-lead":                      "cardiac_monitor_4lead",
    "cardiac monitor (4-lead)":                    "cardiac_monitor_4lead",
    "cardiac monitor — 4-lead":               "cardiac_monitor_4lead",
    "4-lead cardiac monitor":                      "cardiac_monitor_4lead",
    "12-lead ecg device":                          "twelve_lead_ecg_device",
    "12 lead ecg":                                 "twelve_lead_ecg_device",
    "12-lead ecg":                                 "twelve_lead_ecg_device",
    "waveform capnography (etco2)":                "capnography_device",
    "capnography":                                 "capnography_device",
    "etco2":                                       "capnography_device",
    "thermometer (oral)":                          "thermometer_oral",
    "oral thermometer":                            "thermometer_oral",
    "thermometer":                                 "thermometer_oral",
    # Trauma
    "tourniquets":                                 "tourniquets",
    "tourniquet":                                  "tourniquets",
    "pressure bandages":                           "pressure_bandages",
    "hemostatic gauze":                            "hemostatic_gauze",
    "trauma dressings":                            "trauma_dressings",
    "cervical collars (assorted)":                 "cervical_collars_assorted",
    "cervical collars assorted":                   "cervical_collars_assorted",
    "c-collars (assorted)":                        "cervical_collars_assorted",
    "long backboard and straps":                   "long_backboard_straps",
    "long backboard & straps":                     "long_backboard_straps",
    "backboard and straps":                        "long_backboard_straps",
    "backboard & straps":                          "long_backboard_straps",
    "scoop stretcher":                             "scoop_stretcher",
    "pelvic binder":                               "pelvic_binder",
    "traction splint":                             "traction_splint",
    "burn dressings":                              "burn_dressings",
    "splint kit (sam/padded board)":               "splint_kit",
    "sam splint":                                  "splint_kit",
    "chest seal":                                  "chest_seal",
    "chest seal (vented)":                         "chest_seal",
    "chest seal (non-vented)":                     "chest_seal",
    "sterile water":                               "sterile_water",
    "sterile water for irrigation":                "sterile_water",
    # Other
    "stretcher":                                   "stretcher",
    "gurney":                                      "stretcher",
    "ob kit (basic)":                              "ob_kit_basic",
    "ob kit":                                      "ob_kit_basic",
    "broselow tape":                               "broselow_tape",
    "broselow":                                    "broselow_tape",
    "cold packs":                                  "cold_packs",
    "cold pack":                                   "cold_packs",
    "ice pack":                                    "cold_packs",
    "lucas":                                       "auto_chest_compression",
    "lucas device":                                "auto_chest_compression",
    "automatic chest compression device (lucas)":  "auto_chest_compression",
    "mechanical cpr device":                       "auto_chest_compression",
    # Medications
    "albuterol 2.5 mg / 3 ml unit-dose (svn)":    "albuterol_svn_unit_dose",
    "albuterol 2.5mg/3ml unit-dose (svn)":        "albuterol_svn_unit_dose",
    "albuterol svn":                               "albuterol_svn_unit_dose",
    "albuterol":                                   "albuterol_svn_unit_dose",
    "oral glucose gel":                            "oral_glucose_gel",
    "oral glucose":                                "oral_glucose_gel",
    "glucose gel":                                 "oral_glucose_gel",
    "epinephrine auto-injector (0.3 mg adult, 0.15 mg pediatric)": "epi_autoinjector_adult",
    "epinephrine auto-injector (0.3 mg)":          "epi_autoinjector_adult",
    "epi auto-injector":                           "epi_autoinjector_adult",
    "epipen":                                      "epi_autoinjector_adult",
    "epinephrine auto-injector 0.15 mg (pediatric)": "epi_autoinjector_pediatric",
    "epipen jr":                                   "epi_autoinjector_pediatric",
    "aspirin 324 mg (chewable)":                   "aspirin_324mg_chewable",
    "aspirin 324mg chewable":                      "aspirin_324mg_chewable",
    "aspirin":                                     "aspirin_324mg_chewable",
    "naloxone (narcan) 2 mg/2 ml":                 "naloxone_2mg",
    "naloxone (narcan) 2 mg/2ml":                  "naloxone_2mg",
    "naloxone":                                    "naloxone_2mg",
    "narcan":                                      "naloxone_2mg",
    "racepinephrine 2.25% unit-dose (svn)":        "racepinephrine_svn",
    "racepinephrine":                              "racepinephrine_svn",
    "nitroglycerin 0.4 mg sl":                     "nitroglycerin_sl",
    "nitroglycerin sl":                            "nitroglycerin_sl",
    "nitro":                                       "nitroglycerin_sl",
    "ntg":                                         "nitroglycerin_sl",
    "diphenhydramine 25 mg (oral)":                "diphenhydramine_25mg_oral",
    "diphenhydramine im/iv":                       "diphenhydramine_im_iv",
    "benadryl im/iv":                              "diphenhydramine_im_iv",
    "diphenhydramine":                             "diphenhydramine_25mg_oral",
    "benadryl":                                    "diphenhydramine_25mg_oral",
    "activated charcoal":                          "activated_charcoal",
    "epinephrine 1 mg/ml (1:1000)":               "epinephrine_1mg_ml",
    "epinephrine 1 mg/ml (1:1000) — draw-up":     "epinephrine_1mg_ml",
    "epinephrine 1:1000":                          "epinephrine_1mg_ml",
    "epi 1:1000":                                  "epinephrine_1mg_ml",
    "epinephrine draw-up":                         "epinephrine_1mg_ml",
    "push-dose epinephrine":                       "push_dose_epinephrine",
    "push dose epinephrine":                       "push_dose_epinephrine",
    "push-dose epi":                               "push_dose_epinephrine",
    "duoneb":                                      "albuterol_ipratropium_combo",
    "albuterol + ipratropium":                     "albuterol_ipratropium_combo",
    "albuterol and ipratropium":                   "albuterol_ipratropium_combo",
    "ondansetron 4 mg odt":                        "ondansetron_4mg_odt",
    "ondansetron":                                 "ondansetron_4mg_odt",
    "zofran":                                      "ondansetron_4mg_odt",
    "zofran 4mg odt":                              "ondansetron_4mg_odt",
    "epinephrine infusion":                        "epinephrine_infusion",
    "epi infusion":                                "epinephrine_infusion",
}

# ── Equipment helpers ──────────────────────────────────────────────────────────

# Flat map: id → label across all equipment categories and medications.
_ALL_EQUIPMENT_BY_ID: dict[str, str] = {
    item_id: label
    for cat_items in EQUIPMENT_CATALOG.values()
    for item_id, label in cat_items.items()
}
_ALL_EQUIPMENT_BY_ID.update(MEDICATIONS_CATALOG)

# Flat map: normalized label → id (for Pass 1 exact canonical-name matching).
_EQUIPMENT_BY_NORMALIZED_LABEL: dict[str, str] = {
    label.strip().lower(): item_id
    for item_id, label in _ALL_EQUIPMENT_BY_ID.items()
}

_MEDICATION_IDS: frozenset[str] = frozenset(MEDICATIONS_CATALOG)


def equipment_id_for_alias(text: str) -> str | None:
    """Return the canonical ID for a normalized free-text alias, or None if not found."""
    return EQUIPMENT_ALIASES.get(text.strip().lower())


def equipment_id_for_canonical_name(text: str) -> str | None:
    """Return the canonical ID for an exact canonical label match (case-insensitive)."""
    return _EQUIPMENT_BY_NORMALIZED_LABEL.get(text.strip().lower())


def equipment_label_for_id(item_id: str) -> str | None:
    """Return the display label for a catalog item ID, or None if not registered."""
    return _ALL_EQUIPMENT_BY_ID.get(item_id)


def is_known_equipment_id(item_id: str) -> bool:
    """Return True if the item ID exists in the curated equipment or medication catalog."""
    return item_id in _ALL_EQUIPMENT_BY_ID


def is_medication_id(item_id: str) -> bool:
    """Return True if the item ID belongs to the medications catalog."""
    return item_id in _MEDICATION_IDS


def all_equipment_items() -> list[dict]:
    """Return all equipment catalog items as {id, label, category} dicts."""
    result = []
    for category, items in EQUIPMENT_CATALOG.items():
        for item_id, label in items.items():
            result.append({"id": item_id, "label": label, "category": category})
    return result


def all_medication_items() -> list[dict]:
    """Return all medication catalog items as {id, label} dicts."""
    return [{"id": k, "label": v} for k, v in MEDICATIONS_CATALOG.items()]


# ── Reverse lookups ────────────────────────────────────────────────────────────
_INTERVENTION_BY_LABEL: dict[str, str] = {v: k for k, v in INTERVENTIONS.items()}


def intervention_id_for_label(label: str) -> str | None:
    """Return the stable ID for a display label, or None if not found."""
    return _INTERVENTION_BY_LABEL.get(label)


def label_for_intervention(intervention_id: str) -> str | None:
    """Return the display label for a stable intervention ID, or None if not found."""
    return INTERVENTIONS.get(intervention_id)


def canonical_intervention_id(intervention_id: str) -> str:
    """Return the canonical UI intervention ID after legacy alias resolution."""
    return INTERVENTION_ALIASES.get(intervention_id, intervention_id)


def is_known_clinical_concept(concept_id: str) -> bool:
    """Return True if the clinical concept ID exists in the Phase 2 taxonomy."""
    return concept_id in CLINICAL_CONCEPTS


def clinical_concept_label(concept_id: str) -> str | None:
    """Return the display label for a clinical concept ID, or None if not registered."""
    concept = CLINICAL_CONCEPTS.get(concept_id)
    return str(concept["label"]) if concept else None


def is_known_intervention_action(action_id: str) -> bool:
    """Return True if the intervention action ID exists in the Phase 2 taxonomy."""
    return action_id in INTERVENTION_ACTIONS


def intervention_action_label(action_id: str) -> str | None:
    """Return the display label for an intervention action ID, or None if not registered."""
    action = INTERVENTION_ACTIONS.get(action_id)
    return str(action["label"]) if action else None


def intervention_ids_for_action(action_id: str) -> list[str]:
    """Return UI intervention IDs associated with a canonical action ID."""
    action = INTERVENTION_ACTIONS.get(action_id)
    if not action:
        return []
    ids = action.get("intervention_ids", [])
    return [str(i) for i in ids] if isinstance(ids, list) else []


# ── Scenario validation ────────────────────────────────────────────────────────

class ScenarioVocabularyError(ValueError):
    pass


def _validate_debrief_content(scenario: dict) -> list[str]:
    """Return list of missing required authored debrief content field paths.

    Scenarios with debrief_exempt=true are unconditionally skipped.
    Clinical scenarios must have all three fields non-empty.
    """
    if scenario.get("debrief_exempt"):
        return []
    debrief = scenario.get("debrief") or {}
    missing = []
    for field in ("condition_background", "key_teaching_points", "common_mistakes"):
        if not debrief.get(field):
            missing.append(f"debrief.{field}")
    return missing


def validate_scenario(scenario: dict) -> list[str]:
    """
    Layer 1 — load-time hard failure for invalid vocabulary references.

    Raises ScenarioVocabularyError if the scenario references an ID that does
    not exist in the registered vocabulary. Log the error and refuse to load.

    Also returns a (possibly empty) list of warnings for non-fatal issues
    (e.g. label drift between the scenario JSON and vocabulary registry).

    Checks performed:
      - vitals.interventions keys must be registered in INTERVENTIONS
      - vitals.interventions[key].label must match INTERVENTIONS[key] (warning only)
      - scoring_rubric keys must be registered in RUBRIC_DIMENSIONS
      - lung_sound_challenge.post_treatment.requires_intervention_id (if present)
        must be registered in INTERVENTIONS

    Also checks:
      - _schema must be "pfd_scenario_v1" (warning if absent or wrong)
      - correct_treatment.out_of_scope_bls entries must be registered IDs in OUT_OF_SCOPE (error)
      - rubric_template presence (warning if absent — strongly recommended)
      - lung_sound_challenge.post_treatment.requires_treatment_label is deprecated (warning if present)

    Challenge-domain gating checks (warnings):
      - lung_sound_challenge enabled but missing audio_file / finding / accepted_answers / prompt
      - patient.gcs_assessment.total present but challenge_description missing
      - call_type rubric has a lung sounds item but lung_sound_challenge is not enabled
    """
    scenario_id = scenario.get("id", "<unknown>")
    errors: list[str] = []
    warnings: list[str] = []

    # Check _schema
    schema = scenario.get("_schema")
    if schema is None:
        warnings.append("_schema is missing — should be \"pfd_scenario_v1\"")
    elif schema != "pfd_scenario_v1":
        warnings.append(f"_schema is {schema!r} — expected \"pfd_scenario_v1\"")

    # Check call_type — must resolve to a known NASEMSO rubric file if present.
    # Clinical scenarios without call_type get a warning (not an error) until Group F
    # is activated broadly via CALL_TYPE_RUBRIC_ACTIVE=true.
    _CLINICAL_CATEGORIES = {
        "pediatric_medical", "pediatric_trauma",
        "adult_medical", "adult_trauma",
        "neonatal", "obstetric",
    }
    call_type = scenario.get("call_type")
    if call_type is not None:
        from app.rubric_loader import get_known_call_types
        known_call_types = get_known_call_types()
        if call_type not in known_call_types:
            errors.append(
                f"call_type {call_type!r} does not resolve to any rubric file in "
                f"app/rubrics/nasemso/ — known call types: {sorted(known_call_types)}"
            )
    elif scenario.get("category") in _CLINICAL_CATEGORIES:
        warnings.append(
            "call_type is not set — add a NASEMSO call type (e.g. \"hypoglycemia\") "
            "for deterministic call-type composition; required before CALL_TYPE_RUBRIC_ACTIVE=true"
        )

    # Check rubric_template provenance
    if "rubric_template" not in scenario:
        warnings.append("rubric_template is missing — strongly recommended (\"ems_standard_v1\")")

    # Check turnover_target presence
    if "turnover_target" not in scenario:
        warnings.append(
            "turnover_target is missing — scenarios should explicitly declare "
            "\"als\", \"hospital\", \"none\", or \"dynamic\""
        )

    # Check out_of_scope_bls IDs
    correct = scenario.get("correct_treatment", {})
    oos_bls = correct.get("out_of_scope_bls", [])
    if isinstance(oos_bls, list):
        for entry in oos_bls:
            if isinstance(entry, str) and entry not in OUT_OF_SCOPE:
                errors.append(
                    f"correct_treatment.out_of_scope_bls entry {entry!r} is not registered in "
                    f"vocabulary.OUT_OF_SCOPE — use a vocabulary ID or add the ID to OUT_OF_SCOPE first"
                )

    # Check deprecated requires_treatment_label
    lsc_check = scenario.get("lung_sound_challenge", {})
    if isinstance(lsc_check, dict):
        pt_check = lsc_check.get("post_treatment", {})
        if isinstance(pt_check, dict) and "requires_treatment_label" in pt_check:
            warnings.append(
                "lung_sound_challenge.post_treatment.requires_treatment_label is deprecated — "
                "use requires_intervention_id instead"
            )

    # Check intervention keys and label sync
    vitals = scenario.get("vitals", {})
    interventions = vitals.get("interventions", {}) if isinstance(vitals, dict) else {}
    if isinstance(interventions, dict):
        for key, idata in interventions.items():
            if key not in INTERVENTIONS:
                errors.append(
                    f"vitals.interventions[{key!r}] is not registered in vocabulary.INTERVENTIONS"
                )
            elif isinstance(idata, dict) and "label" in idata:
                # Vocabulary is authoritative — warn on drift so authors keep them in sync
                vocab_label = INTERVENTIONS[key]
                json_label = idata["label"]
                if json_label != vocab_label:
                    warnings.append(
                        f"vitals.interventions[{key!r}].label {json_label!r} differs from "
                        f"vocabulary label {vocab_label!r} — update scenario JSON or vocabulary"
                    )

    # Check rubric dimension keys
    rubric = scenario.get("scoring_rubric", {})
    if isinstance(rubric, dict):
        for key in rubric:
            if key not in RUBRIC_DIMENSIONS:
                errors.append(
                    f"scoring_rubric[{key!r}] is not registered in vocabulary.RUBRIC_DIMENSIONS"
                )

    # Check requires_intervention_id (preferred over deprecated requires_treatment_label)
    lsc = scenario.get("lung_sound_challenge", {})
    if isinstance(lsc, dict):
        pt = lsc.get("post_treatment", {})
        if isinstance(pt, dict):
            req_id = pt.get("requires_intervention_id")
            if req_id is not None and req_id not in INTERVENTIONS:
                errors.append(
                    f"lung_sound_challenge.post_treatment.requires_intervention_id {req_id!r}"
                    f" is not registered in vocabulary.INTERVENTIONS"
                )

    # Challenge-domain gating checks — verify that interactive challenge configs are
    # internally complete and that call-type rubric items requiring challenge-gated findings
    # have a matching enabled challenge.

    # A) Lung sound challenge completeness: if enabled, required sub-fields must be present.
    _lsc = scenario.get("lung_sound_challenge") or {}
    if isinstance(_lsc, dict) and _lsc.get("enabled"):
        for _lsc_field in ("audio_file", "finding", "accepted_answers", "prompt"):
            if not _lsc.get(_lsc_field):
                warnings.append(
                    f"lung_sound_challenge.{_lsc_field} is missing or empty — "
                    f"challenge will be broken at runtime"
                )
        _lsc_answers = _lsc.get("accepted_answers")
        if isinstance(_lsc_answers, list) and len(_lsc_answers) == 0:
            warnings.append(
                "lung_sound_challenge.accepted_answers is an empty list — "
                "no student answer will be accepted as correct"
            )

    # B) GCS challenge completeness: if gcs_assessment scores are present, challenge_description
    #    must also be present (it populates the GCS modal observation text).
    _patient = scenario.get("patient") or {}
    _gcs_obj = _patient.get("gcs_assessment") or scenario.get("gcs_assessment") or {}
    if isinstance(_gcs_obj, dict) and _gcs_obj.get("total") is not None:
        if not _gcs_obj.get("challenge_description"):
            warnings.append(
                "patient.gcs_assessment.challenge_description is missing — "
                "GCS modal will show no observation text; add challenge_description so the "
                "student can score E/V/M components"
            )

    # C) Call-type rubric / lung-sound-challenge alignment: if the call type's rubric has a
    #    lung sounds assessment item but lung_sound_challenge is not enabled, the finding is
    #    obtainable via free-text AI with no challenge gate.
    if call_type is not None and not (isinstance(_lsc, dict) and _lsc.get("enabled")):
        try:
            import json as _json
            import os as _os
            _rubric_dir = _os.path.join(_os.path.dirname(__file__), "..", "rubrics", "nasemso")
            # Resolve the rubric file for this call type
            _rubric_file = None
            for _fn in _os.listdir(_rubric_dir):
                if not _fn.endswith(".json") or "schema" in _fn:
                    continue
                with open(_os.path.join(_rubric_dir, _fn)) as _rf:
                    _rdata = _json.load(_rf)
                _rct = _rdata.get("call_type") or _rdata.get("id", "")
                if _rct == call_type or _rct.startswith(call_type):
                    _rubric_file = _fn
                    _rubric_data = _rdata
                    break
            if _rubric_file:
                _LUNG_KWS = {"lung", "auscult", "breath sounds", "wheez", "crackle", "rhonchi"}
                _has_lung_item = False
                # Rubric files use "checklist_items" (NASEMSO format) or "items"
                _rubric_items = _rubric_data.get("checklist_items") or _rubric_data.get("items") or []
                for _item in _rubric_items:
                    _desc = (_item.get("description") or "").lower()
                    if any(_kw in _desc for _kw in _LUNG_KWS):
                        _has_lung_item = True
                        break
                if _has_lung_item:
                    warnings.append(
                        f"call_type {call_type!r} rubric has a lung sounds assessment item but "
                        f"lung_sound_challenge is not enabled — lung sound findings can be obtained "
                        f"via free-text AI without the challenge gate; set lung_sound_challenge.enabled=true "
                        f"to enforce the interactive auscultation path"
                    )
        except Exception:
            pass  # Rubric scan is best-effort; vocabulary errors are caught by check above

    # Debrief authored content check (warning-only during content migration;
    # escalates to load-time error once all scenarios pass — see SCORING_IMPROVEMENT_PLAN A1)
    for missing_field in _validate_debrief_content(scenario):
        warnings.append(
            f"{missing_field} is missing or empty — required for debrief quality; "
            f"set debrief_exempt=true if this scenario intentionally has no debrief"
        )

    # Feedback metadata check — required scenario-authored checklist items without
    # done_feedback / missed_feedback will fall back to LLM-generated debrief text when
    # Phase 3 (Group E) deterministic renderer is active. Warn now so authors can add
    # these fields incrementally before the renderer goes live.
    # Skips: debrief_exempt scenarios; base rubric items (ems.medical.* / ems.trauma.*).
    if not scenario.get("debrief_exempt"):
        for _ci in scenario.get("checklist", []):
            _ci_id = _ci.get("id", "")
            if _ci_id.startswith("ems.medical.") or _ci_id.startswith("ems.trauma."):
                continue
            if _ci.get("required", "required") != "required":
                continue
            _missing_fb = [
                f for f in ("done_feedback", "missed_feedback")
                if not _ci.get(f)
            ]
            if _missing_fb:
                warnings.append(
                    f"checklist item {_ci_id!r} is missing {', '.join(_missing_fb)} — "
                    f"add for deterministic debrief rendering (Phase 3); "
                    f"without these, the LLM will generate per-item debrief text"
                )

    # Critical action evidence check — required critical actions without an evidence dict
    # will fall to the P4 EVALUATE fallback instead of DONE_EVIDENCED/LIKELY_MISSED.
    # Exempt scene-entry/PAT/ALS IDs and scene_entry_credited actions (have dedicated paths).
    import re as _re
    _SE_IDS = {"scene_safety", "bsi", "ppe", "scene_size_up", "scene_approach"}
    _PAT_IDS = {"pat_assessment", "pat", "pediatric_assessment_triangle"}
    _ALS_TOKENS = {"als", "intercept", "medic", "paramedic"}
    _critical_actions = (scenario.get("correct_treatment") or {}).get("critical_actions") or []
    for _ca in _critical_actions:
        if not _ca.get("required"):
            continue
        _cid = (_ca.get("id") or "").lower()
        if _cid in _SE_IDS or _cid in _PAT_IDS:
            continue
        if bool(set(_re.split(r"[^a-z0-9]+", _cid)) & _ALS_TOKENS):
            continue
        if _ca.get("scene_entry_credited"):
            continue
        if not _ca.get("evidence"):
            warnings.append(
                f"correct_treatment.critical_actions[{_cid!r}] is required but has no "
                f"'evidence' dict — will fall to P4 EVALUATE fallback; add evidence patterns "
                f"or set protocol_indicated=true with an evidence dict to get LIKELY_MISSED"
            )

    if errors:
        raise ScenarioVocabularyError(
            f"Scenario {scenario_id!r} failed vocabulary validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    return warnings
