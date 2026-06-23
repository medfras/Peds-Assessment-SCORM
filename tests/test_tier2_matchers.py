"""
Tier 2 matcher regression tests — Phase 3.

Validates that every checklist item with tier2_patterns:
  1. Matches all positive samples (should satisfy the item)
  2. Rejects all negative samples (should NOT satisfy the item)
  3. Has at least one positive + one negative sample defined here
  4. Uses valid regex syntax

Samples are written from the student (user) perspective — EMS student messages
only, never model/AI responses. The transcript source is student messages only.

Adding a new checklist item with tier2_patterns requires adding entries to
POSITIVE_SAMPLES and NEGATIVE_SAMPLES below or the structural enforcement test
will fail.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ── Load all checklist items with tier2_patterns ──────────────────────────────

_SCENARIO_DIR = Path(__file__).parent.parent / "app" / "scenarios"
_RUBRIC_DIR = Path(__file__).parent.parent / "app" / "rubrics" / "nasemso"
_MIGRATED_CALL_TYPE_TIER2_ITEMS = {
    "hypoglycemia.blood_glucose_check",
    "hypoglycemia.swallow_assessment",
    "hypoglycemia.oral_glucose_administered",
    "head_injury.neuro_assessment",
    "head_injury.pupil_assessment",
    "head_injury.dcap_btls_head",
    "head_injury.smr",
    "head_injury.priority_transport",
    "head_injury.high_flow_o2",
}


def _load_tier2_items() -> dict[str, list[str]]:
    """Return {item_id: [pattern, ...]} for every item that has tier2_patterns."""
    result: dict[str, list[str]] = {}
    for path in sorted(_SCENARIO_DIR.rglob("*.json")):
        with path.open() as f:
            data = json.load(f)
        for item in data.get("checklist", []):
            patterns = item.get("tier2_patterns", [])
            if patterns:
                result[item["id"]] = patterns
    for path in sorted(_RUBRIC_DIR.glob("*_v*.json")):
        with path.open() as f:
            data = json.load(f)
        for item in data.get("checklist_items", []):
            item_id = item.get("id")
            patterns = item.get("tier2_patterns", [])
            if item_id in _MIGRATED_CALL_TYPE_TIER2_ITEMS and patterns:
                result[item_id] = patterns
    return result


_ALL_T2_ITEMS: dict[str, list[str]] = _load_tier2_items()


def _matches(item_id: str, text: str) -> bool:
    """True if text matches any pattern for item_id."""
    return any(re.search(p, text) for p in _ALL_T2_ITEMS[item_id])


# ── Sample corpus ─────────────────────────────────────────────────────────────
#
# Format: (item_id, text)
# Positive = text that SHOULD match (student correctly demonstrates the item)
# Negative = text that should NOT match (legitimate EMS comms, wrong item)

POSITIVE_SAMPLES: list[tuple[str, str]] = [

    # ── adult_acs_01_stemi ────────────────────────────────────────────────────
    ("adult_acs_01_stemi.cardiac_monitoring",
     "I want to put him on the cardiac monitor and get a rhythm strip"),
    ("adult_acs_01_stemi.cardiac_monitoring",
     "Applying 4-lead EKG now — I need to see what the rhythm is"),

    ("adult_acs_01_stemi.twelve_lead_ecg",
     "I need a 12-lead ECG right now"),
    ("adult_acs_01_stemi.twelve_lead_ecg",
     "12-lead shows ST elevation in the inferior leads — this is a STEMI"),

    ("adult_acs_01_stemi.aspirin_admin",
     "I'm going to give aspirin 324mg chewable — no allergy, no contraindications"),
    ("adult_acs_01_stemi.aspirin_admin",
     "Please chew this ASA, don't swallow it whole"),

    ("adult_acs_01_stemi.priority_transport",
     "We need to load and go to Central City Medical Center"),
    ("adult_acs_01_stemi.priority_transport",
     "Priority transport — lights and sirens to the PCI-capable hospital"),

    ("adult_acs_01_stemi.hospital_notification",
     "Central City, I need to call a STEMI alert — cath lab activation"),
    ("adult_acs_01_stemi.hospital_notification",
     "Notifying the hospital — cardiac alert, please activate the cath lab"),

    # ── peds_anaphylaxis_01 ───────────────────────────────────────────────────
    ("peds_anaphylaxis_01.pat_assessment",
     "PAT shows increased work of breathing with audible wheeze and hives"),
    ("peds_anaphylaxis_01.pat_assessment",
     "Appearance frightened, wheeze audible, circulation shows urticaria and flush"),

    ("peds_anaphylaxis_01.anaphylaxis_recognition",
     "This is anaphylaxis — he has both bronchospasm and hypotension"),
    ("peds_anaphylaxis_01.anaphylaxis_recognition",
     "I need to give epinephrine — this is a systemic anaphylactic reaction"),

    ("peds_anaphylaxis_01.epinephrine_im",
     "Drawing up epinephrine 0.15mg — doing a 5-rights check before I draw"),
    ("peds_anaphylaxis_01.epinephrine_im",
     "Injecting epinephrine IM into the anterolateral thigh"),

    ("peds_anaphylaxis_01.weight_dosing_check",
     "How much does he weigh? I need to confirm the dose"),
    ("peds_anaphylaxis_01.weight_dosing_check",
     "He's 27kg so we're in the 0.15mg range on the Broselow tape"),

    # ── peds_asthma_01 ────────────────────────────────────────────────────────
    ("peds_asthma_01.pat_assessment",
     "PAT shows retractions and audible wheeze — work of breathing is increased"),
    ("peds_asthma_01.pat_assessment",
     "Assessing appearance — anxious, breathing with effort, skin appropriate"),

    ("peds_asthma_01.albuterol_svn",
     "I'm setting up the nebulizer with albuterol 2.5mg"),
    ("peds_asthma_01.albuterol_svn",
     "Albuterol SVN — bronchodilator via small volume nebulizer"),

    ("peds_asthma_01.foreign_body_screen",
     "Does she have a history of asthma? Has she always had breathing problems?"),
    ("peds_asthma_01.foreign_body_screen",
     "Was the onset sudden, or did she choke on anything? Any food involved?"),

    # ── peds_croup_01 ─────────────────────────────────────────────────────────
    ("peds_croup_01.pat_assessment",
     "PAT — alert and crying, retractions visible, inspiratory stridor audible"),
    ("peds_croup_01.pat_assessment",
     "Work of breathing elevated with stridor, circulation pink, appearing frightened"),

    ("peds_croup_01.lung_sound_auscultation",
     "Auscultating lung sounds now to check for stridor versus wheeze"),
    ("peds_croup_01.lung_sound_auscultation",
     "Let me listen to breath sounds with my stethoscope"),

    ("peds_croup_01.croup_recognition",
     "This is croup — barking cough with inspiratory stridor, upper airway obstruction"),
    ("peds_croup_01.croup_recognition",
     "Upper airway issue, not bronchospasm — blow-by O2 and ALS for racepinephrine"),

    ("peds_croup_01.positioning_calm",
     "Keep him with mom — don't separate them, let her hold him upright"),
    ("peds_croup_01.positioning_calm",
     "Place her upright in a position of comfort"),

    ("peds_croup_01.o2_blowby",
     "Blow-by oxygen — I'll hold the mask near his face so he doesn't get upset"),
    ("peds_croup_01.o2_blowby",
     "Supplemental O2 via nasal cannula or holding NRB close — blow-by technique"),

    ("peds_croup_01.als_intercept",
     "Medic 2 — patient is 9kg, SpO2 93%, inspiratory stridor at rest, please have racepinephrine ready"),
    ("peds_croup_01.als_intercept",
     "Notifying ALS and updating them with weight and stridor severity"),

    ("peds_croup_01.epiglottitis_screen",
     "No drooling, no tripod posturing — this doesn't look like epiglottitis"),
    ("peds_croup_01.epiglottitis_screen",
     "He was sick for a couple days before this — gradual onset, not sudden like a foreign body"),

    # ── peds_diabetic_emergency_01 ────────────────────────────────────────────
    ("peds_diabetic_emergency_01.pat_assessment",
     "PAT — altered appearance, not interactive, pale and diaphoretic circulation"),
    ("peds_diabetic_emergency_01.pat_assessment",
     "Appearance confused, circulation to skin is cool and pale, work of breathing normal"),

    ("peds_diabetic_emergency_01.history_diabetes",
     "Does she have Type 1 diabetes? Is she on an insulin pump?"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "CGM reads 38 — that's hypoglycemia, low blood sugar for sure"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "He is diabetic and his CGM is alarming low"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "Medications: insulin via Omnipod pump"),

    ("hypoglycemia.blood_glucose_check",
     "I need to check her blood glucose right now"),
    ("hypoglycemia.blood_glucose_check",
     "Let me do a finger stick — glucometer reading to confirm the CGM value"),

    ("hypoglycemia.swallow_assessment",
     "Before I give oral glucose I need to confirm she can swallow safely — GCS intact?"),
    ("hypoglycemia.swallow_assessment",
     "Checking for gag reflex and that she's not seizing or vomiting before oral glucose"),
    ("hypoglycemia.swallow_assessment",
     "Check AVPU and level of consciousness before oral glucose"),
    ("hypoglycemia.swallow_assessment",
     "He is talking and answering questions, following directions, airway is patent"),

    ("hypoglycemia.oral_glucose_administered",
     "I'm giving the oral glucose gel now — placing between cheek and gum"),
    ("hypoglycemia.oral_glucose_administered",
     "Administering glucose gel per protocol for hypoglycemia"),

    # ── peds_febrile_seizure_01 ───────────────────────────────────────────────
    ("peds_febrile_seizure_01.pat_assessment",
     "PAT — active seizure appearance, airway gurgling with secretions, flushed and warm"),
    ("peds_febrile_seizure_01.pat_assessment",
     "Appearance abnormal, work of breathing shows airway secretions, circulation flushed and febrile"),

    ("peds_febrile_seizure_01.recovery_position",
     "I'm rolling her onto her side into the recovery position"),
    ("peds_febrile_seizure_01.recovery_position",
     "Left lateral recumbent to protect her airway from aspiration"),

    ("peds_febrile_seizure_01.suction_airway",
     "Suction her mouth now to clear the saliva and secretions"),
    ("peds_febrile_seizure_01.suction_airway",
     "Use the Yankauer to clear the gurgling from her airway"),

    ("peds_febrile_seizure_01.protect_from_injury",
     "Clear the area and protect her from injury, but don't restrain her"),
    ("peds_febrile_seizure_01.protect_from_injury",
     "Do not put anything in her mouth while she is seizing"),
    ("peds_febrile_seizure_01.protect_from_injury",
     "Prevent injuries while she is seizing"),
    ("peds_febrile_seizure_01.protect_from_injury",
     "Keep her safe from injury and protect the airway"),

    ("peds_febrile_seizure_01.seizure_history",
     "How long has she been seizing? Was it generalized or focal?"),
    ("peds_febrile_seizure_01.seizure_history",
     "Has she had seizures before? Has she had a fever recently?"),

    ("peds_febrile_seizure_01.temperature_assessment",
     "Do you have a thermometer? I need to check her temperature"),
    ("peds_febrile_seizure_01.temperature_assessment",
     "What is her fever? How many degrees?"),

    # ── peds_syncope_01 ───────────────────────────────────────────────────────
    ("peds_syncope_01.prodrome_history",
     "What did you feel right before you passed out — any dizziness or nausea?"),
    ("peds_syncope_01.prodrome_history",
     "Did you notice any warning signs? Tunnel vision, lightheadedness, or warmth?"),

    ("peds_syncope_01.cardiac_red_flag_screen",
     "Does anyone in your family have a history of sudden cardiac death?"),
    ("peds_syncope_01.cardiac_red_flag_screen",
     "Were you exercising or running when this happened? Any palpitations before?"),

    ("peds_syncope_01.blood_glucose_checked",
     "I need to check a blood glucose right now"),
    ("peds_syncope_01.blood_glucose_checked",
     "Let me do a finger stick — checking blood sugar"),

    ("peds_syncope_01.seizure_screen",
     "Was there any shaking or jerking of the arms or legs?"),
    ("peds_syncope_01.seizure_screen",
     "Did she bite her tongue or have any incontinence during the episode?"),

    ("peds_syncope_01.supine_positioning",
     "I'm going to lay her flat with her legs elevated"),
    ("peds_syncope_01.supine_positioning",
     "Let me put her supine — legs up to improve cerebral perfusion"),

    # ── peds_trauma_01_soft_tissue ────────────────────────────────────────────
    ("peds_trauma_01_soft_tissue.pat_assessment",
     "PAT — alert with vigorous cry, work of breathing non-labored, skin pink and warm"),
    ("peds_trauma_01_soft_tissue.pat_assessment",
     "Appearance good, crying appropriately, circulation warm and pink"),

    ("peds_trauma_01_soft_tissue.direct_pressure",
     "I'm applying direct pressure to control the bleeding from the scalp"),
    ("peds_trauma_01_soft_tissue.direct_pressure",
     "Let me put a pressure dressing on that wound to stop the hemorrhage"),

    ("peds_trauma_01_soft_tissue.neuro_baseline",
     "Can you check his pupils? And what's the GCS?"),
    ("peds_trauma_01_soft_tissue.neuro_history",
     "Did he lose consciousness at any point? Any vomiting since the fall?"),

    ("peds_trauma_01_soft_tissue.mechanism_screen",
     "How far did he fall? What did he land on?"),
    ("peds_trauma_01_soft_tissue.mechanism_screen",
     "What happened — how high was it when he hit his head?"),

    ("peds_trauma_01_soft_tissue.transport_decision",
     "We need to transport him to the pediatric emergency department"),
    ("peds_trauma_01_soft_tissue.transport_decision",
     "Let's load him up and take him in — head injury needs hospital evaluation"),

    # ── peds_trauma_02_partial_choking ────────────────────────────────────────
    ("peds_trauma_02_partial_choking.pat_assessment",
     "PAT — alert, forceful cough, I can hear air moving, she's crying between coughs"),
    ("peds_trauma_02_partial_choking.pat_assessment",
     "Appearance appropriate, vigorous cough, good air movement — partial obstruction"),

    ("peds_trauma_02_partial_choking.partial_obstruction_classification",
     "This is a partial obstruction with effective cough — we do not intervene"),
    ("peds_trauma_02_partial_choking.partial_obstruction_classification",
     "Good air exchange, let her continue coughing — we don't do back blows on this"),

    ("peds_trauma_02_partial_choking.encourage_coughing",
     "Encourage her to keep coughing — it's working, don't stop"),
    ("peds_trauma_02_partial_choking.encourage_coughing",
     "Let her cough it out — cough harder sweetie"),

    ("peds_trauma_02_partial_choking.airway_monitoring",
     "I'm monitoring her airway closely — watching for the cough to become silent"),
    ("peds_trauma_02_partial_choking.airway_monitoring",
     "Watch her breathing carefully — if she stops coughing that means complete obstruction"),

    ("peds_trauma_02_partial_choking.rapid_transport",
     "Let's load her and transport to the hospital"),
    ("peds_trauma_02_partial_choking.rapid_transport",
     "We need to move — partial obstructions can worsen suddenly"),

    # ── peds_trauma_03_extremity ──────────────────────────────────────────────
    ("peds_trauma_03_extremity.pat_assessment",
     "PAT — alert and crying in pain, work of breathing non-labored, circulation warm"),
    ("peds_trauma_03_extremity.pat_assessment",
     "Appearance appropriate, in pain but crying vigorously, skin pink and warm"),

    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Checking CMS distal to the injury before I do anything — cap refill, motor, and sensation"),
    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Pulse in the hand? Cap refill? Can you move your fingers and feel me touching them?"),

    ("peds_trauma_03_extremity.fracture_realignment",
     "I'm going to attempt one gentle realignment — traction along the long axis"),
    ("peds_trauma_03_extremity.fracture_realignment",
     "One attempt to straighten and reduce this fracture"),

    ("peds_trauma_03_extremity.splinting",
     "Splinting the forearm — padded, joint above and below, secured without restricting circulation"),
    ("peds_trauma_03_extremity.splinting",
     "Immobilizing the fracture with a padded splint, bandaging to stabilize"),

    ("peds_trauma_03_extremity.cms_post_assessment",
     "Reassessing CMS after splinting — checking cap refill again compared to before"),
    ("peds_trauma_03_extremity.cms_post_assessment",
     "Cap refill after splinting — is sensation still intact distally?"),

    # ── peds_trauma_04_burn ───────────────────────────────────────────────────
    ("peds_trauma_04_burn.pat_assessment",
     "PAT — screaming toddler in obvious distress, work of breathing non-labored"),
    ("peds_trauma_04_burn.pat_assessment",
     "Appearance distressed with burn visible, circulation shows reddened skin at burn site"),

    ("peds_trauma_04_burn.stop_burning",
     "Remove the wet coffee-soaked clothing immediately to stop the burning"),
    ("peds_trauma_04_burn.stop_burning",
     "Take off that shirt — we need to stop the burning process now"),

    ("peds_trauma_04_burn.airway_screen",
     "Any soot around the mouth? Singed nasal hairs? Any stridor or hoarseness?"),
    ("peds_trauma_04_burn.airway_screen",
     "Checking for inhalation injury — any smoke involvement or throat irritation?"),

    ("peds_trauma_04_burn.dry_dressing",
     "Cover the burn with dry sterile gauze — not wet dressings"),
    ("peds_trauma_04_burn.dry_dressing",
     "Applying a dry sterile dressing to cover the burn area"),

    ("peds_trauma_04_burn.prevent_hypothermia",
     "Cover her with a blanket to prevent heat loss after the dressing"),
    ("peds_trauma_04_burn.prevent_hypothermia",
     "Keep her warm — hypothermia is a real risk with burns this size"),

    # ── peds_trauma_05_auto_ped ───────────────────────────────────────────────
    ("peds_trauma_05_auto_ped.pat_assessment",
     "PAT — motionless, rapid shallow breathing, mottled skin — immediately life-threatening"),
    ("peds_trauma_05_auto_ped.pat_assessment",
     "Work of breathing rapid and shallow, circulation mottled and poor — critical patient"),

    ("peds_trauma_05_auto_ped.airway_bvm",
     "Jaw thrust to open the airway, I need the BVM for assisted ventilation"),
    ("peds_trauma_05_auto_ped.airway_bvm",
     "Two-person bag-valve-mask ventilation — respirations are inadequate"),

    ("peds_trauma_05_auto_ped.shock_recognition",
     "HR 162, BP 70/40 — this is decompensated hemorrhagic shock"),
    ("peds_trauma_05_auto_ped.shock_recognition",
     "Pale, mottled, cap refill 4 seconds, hypotensive — he's in shock"),

    ("peds_trauma_05_auto_ped.pelvic_binder",
     "Checking pelvic stability — mechanism warrants a pelvic binder at the trochanters"),
    ("peds_trauma_05_auto_ped.pelvic_binder",
     "Applying pelvic binder at the greater trochanters to tamponade internal hemorrhage"),

    ("peds_trauma_05_auto_ped.load_and_go",
     "Load and go — scene time under 10 minutes to the trauma center"),
    ("peds_trauma_05_auto_ped.load_and_go",
     "Rapid transport with lights and sirens — this is a surgical problem"),

    # ── peds_trauma_06_handlebar ──────────────────────────────────────────────
    ("peds_trauma_06_handlebar.pat_assessment",
     "PAT — quiet and pale, not acting like a normal kid after a fall"),
    ("peds_trauma_06_handlebar.pat_assessment",
     "Appearance pale, cool and diaphoretic circulation — something is wrong"),

    ("peds_trauma_06_handlebar.handlebar_sign",
     "I see a circular contusion at the epigastric area — classic handlebar sign"),
    ("peds_trauma_06_handlebar.handlebar_sign",
     "There's bruising on the abdomen consistent with blunt abdominal injury"),

    ("peds_trauma_06_handlebar.shock_recognition",
     "HR 130, pale and diaphoretic, cap refill 3 seconds — compensated shock"),
    ("peds_trauma_06_handlebar.shock_recognition",
     "He nearly passed out when he stood up — near-syncope, signs of shock"),

    ("peds_trauma_06_handlebar.high_flow_o2",
     "High-flow O2 via NRB mask at 15 LPM"),
    ("peds_trauma_06_handlebar.high_flow_o2",
     "Let me put a non-rebreather on him — maximize O2 delivery"),

    ("peds_trauma_06_handlebar.priority_transport",
     "Rapid transport to the trauma center — ALS intercept en route"),
    ("peds_trauma_06_handlebar.priority_transport",
     "We need to go now — this is a surgical emergency, no BLS fix"),

    # ── peds_ams_tox_01 ───────────────────────────────────────────────────────
    ("peds_ams_tox_01.pat_assessment",
     "PAT — appearance unresponsive and limp, snoring respirations, pale gray circulation to skin"),
    ("peds_ams_tox_01.pat_assessment",
     "Work of breathing — bradypneic and snoring; appearance — unresponsive to voice"),

    ("peds_ams_tox_01.airway_management",
     "Head-tilt chin-lift to open the airway — I can hear snoring that resolved"),
    ("peds_ams_tox_01.airway_management",
     "Jaw thrust to open the airway, repositioning his head — airway maneuver first"),

    ("peds_ams_tox_01.bvm_ventilations",
     "BVM ventilations at 12–20 per minute — he's not breathing adequately"),
    ("peds_ams_tox_01.bvm_ventilations",
     "Bag-valve mask to assist ventilation — positive pressure respirations now"),

    ("peds_ams_tox_01.differential_workup",
     "Pupils are pinpoint and miotic — classic opioid toxidrome; also checking BGL"),
    ("peds_ams_tox_01.differential_workup",
     "Finger stick glucose is 95, normal — ruling out hypoglycemia; DCAP-BTLS head negative"),

    ("peds_ams_tox_01.naloxone_administration",
     "Naloxone 2mg intranasal via atomizer now — possible opioid exposure"),
    ("peds_ams_tox_01.naloxone_administration",
     "MAD atomizer, 2mg Narcan intranasal — opioid reversal for this kid"),

    # ── adult_cardiac_arrest_01_bls ───────────────────────────────────────────
    ("adult_cardiac_arrest_01_bls.arrest_recognition",
     "Patient is pulseless and apneic — calling cardiac arrest, starting CPR"),
    ("adult_cardiac_arrest_01_bls.arrest_recognition",
     "No pulse, unresponsive — cardiac arrest, initiating compressions"),

    # ── newborn_resus_01_nrp ─────────────────────────────────────────────────
    ("newborn_resus_01_nrp.non_vigorous_recognition",
     "Newborn is non-vigorous — not breathing, poor tone, starting resuscitation"),
    ("newborn_resus_01_nrp.non_vigorous_recognition",
     "Baby is apneic with poor tone, heart rate below 100 — NRP steps initiated"),

    # ── peds_cardiac_arrest_01_bls ───────────────────────────────────────────
    ("peds_cardiac_arrest_01_bls.arrest_recognition",
     "No pulse on this kid — pulseless and unresponsive, starting compressions"),
    ("peds_cardiac_arrest_01_bls.arrest_recognition",
     "Pediatric cardiac arrest, apneic and agonal — CPR now"),

    # ── ems.medical shared items ─────────────────────────────────────────────
    ("ems.medical.repeat_vitals",
     "Let's repeat vitals — recheck BP, HR, and SpO2 after the glucose gel"),
    ("ems.medical.repeat_vitals",
     "Another set of vitals please, and recheck her glucose in five minutes"),

    ("ems.medical.sample_history",
     "Any medical history? Is she diabetic, does she have an insulin pump?"),
    ("ems.medical.sample_history",
     "PMH — type 1 diabetes, on a CGM, any prior seizures or cardiac history?"),

    ("ems.medical.treatment_response",
     "She's waking up and getting better — GCS improving, glucose responded"),
    ("ems.medical.treatment_response",
     "Any response to treatment? Is she more alert after the oral glucose?"),

    # ── peds_trauma_07_head_injury ───────────────────────────────────────────
    ("peds_trauma_07_head_injury.pat_assessment",
     "PAT shows he's alert but pale, work of breathing looks increased, circulation to skin is pink"),
    ("peds_trauma_07_head_injury.pat_assessment",
     "Appearance he's crying, skin is pale, circulation looks okay"),

    ("head_injury.neuro_assessment",
     "Let me check pupils — equal and reactive. GCS is 14, he's confused"),
    ("head_injury.neuro_assessment",
     "AVPU is alert but oriented times two, checking mental status"),
    ("head_injury.neuro_assessment",
     "I checked pupils, LOC, AVPU, and calculated GCS"),
    ("head_injury.pupil_assessment",
     "Let me check pupils — right is sluggish, left is reactive"),
    ("head_injury.pupil_assessment",
     "PERRLA check: pupils are unequal but reactive"),

    ("head_injury.dcap_btls_head",
     "I'm palpating the head — DCAP-BTLS, checking for step-off or midline tenderness"),
    ("head_injury.dcap_btls_head",
     "Assess the head for tenderness, any deformity or contusion"),
    ("head_injury.dcap_btls_head",
     "I examined the head for DCAP-BTLS"),

    ("head_injury.smr",
     "Applying cervical collar and manual in-line stabilization, spinal motion restriction"),
    ("head_injury.smr",
     "Let's get him on the backboard, initiate SMR"),

    ("head_injury.priority_transport",
     "Load and go — pediatric trauma center, expedite transport"),
    ("head_injury.priority_transport",
     "We need to transport emergent to the hospital now"),
    ("head_injury.high_flow_o2",
     "Apply high-flow O2 via NRB mask at 15 LPM"),
    ("head_injury.high_flow_o2",
     "Put him on a non-rebreather for the head injury"),
    ("ems.trauma.priority_transport",
     "GCS 15 with no LOC and no vomiting — not sick, continue assessment and prepare ALS handoff"),

    # ── peds_trauma_08_nat ───────────────────────────────────────────────────
    ("peds_trauma_08_nat.pat_assessment",
     "PAT — appearance she's alert and tearful, work of breathing normal, circulation to skin is pink"),
    ("peds_trauma_08_nat.pat_assessment",
     "She looks alert but is not interacting much, skin is pale"),

    ("peds_trauma_08_nat.neuro_assessment",
     "GCS is 15, pupils are equal and reactive, she's oriented and follows commands"),
    ("peds_trauma_08_nat.neuro_assessment",
     "AVPU is alert, mental status seems intact, and I am checking pupils"),

    ("peds_trauma_08_nat.dcap_btls_body_survey",
     "Head-to-toe body survey — DCAP-BTLS, I see bruising on the left upper arm and a laceration on the inner lip"),
    ("peds_trauma_08_nat.dcap_btls_body_survey",
     "Palpating the torso and flank, checking for any contusion or injury"),

    ("peds_trauma_08_nat.objective_documentation",
     "Documenting: 3 cm yellow-green contusion on right flank, healing laceration on inner lip, bruising left upper arm"),
    ("peds_trauma_08_nat.objective_documentation",
     "Objective findings — purple contusion, location is right upper arm, size approximately 2 cm"),

    ("peds_trauma_08_nat.transport_and_reporting",
     "Loading now, transport to ED — this is a mandatory report, notifying CPS"),
    ("peds_trauma_08_nat.transport_and_reporting",
     "We need to make a mandatory report to child protective services and transport to the hospital"),

    ("peds_trauma_08_nat.behavioral_observation",
     "She withdraws from the caregiver and avoids eye contact, gives evasive answers — inconsistent with mechanism"),
    ("peds_trauma_08_nat.behavioral_observation",
     "Child is calm without the caregiver present, her demeanor changed when mom stepped out"),
]


NEGATIVE_SAMPLES: list[tuple[str, str]] = [

    # ── adult_acs_01_stemi ────────────────────────────────────────────────────
    ("adult_acs_01_stemi.cardiac_monitoring",
     "Please chew the aspirin tablet, do not swallow it whole"),
    ("adult_acs_01_stemi.cardiac_monitoring",
     "What is his name and date of birth?"),
    ("ems.trauma.priority_transport",
     "I am applying direct pressure to the scalp wound"),

    ("adult_acs_01_stemi.twelve_lead_ecg",
     "I need to get a blood pressure reading"),
    ("adult_acs_01_stemi.twelve_lead_ecg",
     "Let me apply supplemental oxygen via nasal cannula"),

    ("adult_acs_01_stemi.aspirin_admin",
     "Get the 12-lead done first, then I'll reassess"),
    ("adult_acs_01_stemi.aspirin_admin",
     "What was he doing when the chest pain started?"),

    ("adult_acs_01_stemi.priority_transport",
     "Aspirin 324mg chewable — please chew this"),
    ("adult_acs_01_stemi.priority_transport",
     "Apply the cardiac monitor and get a 4-lead strip"),

    ("adult_acs_01_stemi.hospital_notification",
     "Let me check his blood pressure and SpO2"),
    ("adult_acs_01_stemi.hospital_notification",
     "Apply oxygen via nasal cannula at 2 LPM"),

    # ── peds_anaphylaxis_01 ───────────────────────────────────────────────────
    ("peds_anaphylaxis_01.pat_assessment",
     "Draw up epinephrine 0.15mg for the thigh injection"),
    ("peds_anaphylaxis_01.pat_assessment",
     "What is his heart rate and blood pressure?"),

    ("peds_anaphylaxis_01.anaphylaxis_recognition",
     "Let me check his blood pressure and put the monitor on"),
    ("peds_anaphylaxis_01.anaphylaxis_recognition",
     "How much does he weigh? Let me confirm the dose"),

    ("peds_anaphylaxis_01.epinephrine_im",
     "What is his weight on the Broselow tape?"),
    ("peds_anaphylaxis_01.epinephrine_im",
     "Let me listen to his lung sounds"),

    ("peds_anaphylaxis_01.weight_dosing_check",
     "I need to apply the NRB mask right now"),
    ("peds_anaphylaxis_01.weight_dosing_check",
     "Let me position him supine with legs elevated"),

    # ── peds_asthma_01 ────────────────────────────────────────────────────────
    ("peds_asthma_01.pat_assessment",
     "Set up the albuterol nebulizer treatment"),
    ("peds_asthma_01.pat_assessment",
     "Get the NRB mask on her right away"),

    ("peds_asthma_01.albuterol_svn",
     "Let me put the NRB mask on her first"),
    ("peds_asthma_01.albuterol_svn",
     "What is her SpO2 right now?"),

    ("peds_asthma_01.foreign_body_screen",
     "Let me listen to her lung sounds right now"),
    ("peds_asthma_01.foreign_body_screen",
     "Checking his OPQRST — onset, provocation, quality, region, severity, time"),

    # ── peds_croup_01 ─────────────────────────────────────────────────────────
    ("peds_croup_01.pat_assessment",
     "Let me set up the blow-by oxygen delivery"),
    ("peds_croup_01.pat_assessment",
     "Contact ALS for a racepinephrine update"),

    ("peds_croup_01.lung_sound_auscultation",
     "Checking SpO2 and heart rate now"),
    ("peds_croup_01.lung_sound_auscultation",
     "She has audible stridor while crying"),

    ("peds_croup_01.croup_recognition",
     "Let me take his temperature and check his ears"),
    ("peds_croup_01.croup_recognition",
     "What is his heart rate and respiratory rate?"),

    ("peds_croup_01.positioning_calm",
     "Let me set up the oxygen delivery equipment"),
    ("peds_croup_01.positioning_calm",
     "Notify ALS that we have a pediatric airway patient"),

    ("peds_croup_01.o2_blowby",
     "Let me keep the baby calm and with his mother"),
    ("peds_croup_01.o2_blowby",
     "What is his weight? I need to report to ALS"),

    ("peds_croup_01.als_intercept",
     "Keep him upright and minimize stimulation"),
    ("peds_croup_01.als_intercept",
     "Let me do the PAT assessment — appearance and work of breathing"),

    ("peds_croup_01.epiglottitis_screen",
     "Let me apply blow-by oxygen via NRB mask held away from face"),
    ("peds_croup_01.epiglottitis_screen",
     "Keeping the baby with his mother and staying calm"),

    # ── peds_diabetic_emergency_01 ────────────────────────────────────────────
    ("peds_diabetic_emergency_01.pat_assessment",
     "Let me give the oral glucose gel right now"),
    ("peds_diabetic_emergency_01.pat_assessment",
     "I need to check her blood sugar immediately"),

    ("peds_diabetic_emergency_01.history_diabetes",
     "Let me check her blood pressure and respiratory rate"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "I need to apply supplemental oxygen via NRB mask"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "Is he diabetic?"),
    ("peds_diabetic_emergency_01.history_diabetes",
     "Is he diabetic? Administer oral glucose."),

    ("hypoglycemia.blood_glucose_check",
     "Let me ask about her medical history and medications"),
    ("hypoglycemia.blood_glucose_check",
     "Applying supplemental oxygen via nasal cannula"),

    ("hypoglycemia.swallow_assessment",
     "Checking blood glucose via finger stick right now"),
    ("hypoglycemia.swallow_assessment",
     "Asking about diabetes history and insulin use"),

    ("hypoglycemia.oral_glucose_administered",
     "I need to make sure she can swallow before giving anything"),
    ("hypoglycemia.oral_glucose_administered",
     "Checking her GCS and ability to protect her airway"),

    # ── peds_febrile_seizure_01 ───────────────────────────────────────────────
    ("peds_febrile_seizure_01.pat_assessment",
     "Let me put her in the recovery position right now"),
    ("peds_febrile_seizure_01.pat_assessment",
     "Apply supplemental oxygen via NRB mask"),

    ("peds_febrile_seizure_01.recovery_position",
     "Let me check her blood pressure and pulse ox"),
    ("peds_febrile_seizure_01.recovery_position",
     "What medications is she on? Any anticonvulsants?"),

    ("peds_febrile_seizure_01.suction_airway",
     "Apply supplemental oxygen via NRB mask"),
    ("peds_febrile_seizure_01.suction_airway",
     "Move the coffee table and keep her safe"),
    ("peds_febrile_seizure_01.suction_airway",
     "I am preparing suction"),

    ("peds_febrile_seizure_01.protect_from_injury",
     "Suction the saliva from her mouth"),
    ("peds_febrile_seizure_01.protect_from_injury",
     "Check her temperature and blood glucose"),

    ("peds_febrile_seizure_01.seizure_history",
     "Let me apply NRB oxygen and position her on her side"),
    ("peds_febrile_seizure_01.seizure_history",
     "Checking her pupils and skin signs for the primary assessment"),
    ("peds_febrile_seizure_01.seizure_history",
     "Does she have a fever?"),

    ("peds_febrile_seizure_01.temperature_assessment",
     "Let me check her SpO2 and respiratory rate"),
    ("peds_febrile_seizure_01.temperature_assessment",
     "Roll her into the recovery position to protect the airway"),

    # ── peds_syncope_01 ───────────────────────────────────────────────────────
    ("peds_syncope_01.prodrome_history",
     "Does your family have a history of cardiac problems?"),
    ("peds_syncope_01.prodrome_history",
     "Let me check your blood pressure and pulse"),

    ("peds_syncope_01.cardiac_red_flag_screen",
     "How long were you unconscious?"),
    ("peds_syncope_01.cardiac_red_flag_screen",
     "Let me lay you flat with your legs elevated"),

    ("peds_syncope_01.blood_glucose_checked",
     "Were you running or exercising when this happened?"),
    ("peds_syncope_01.blood_glucose_checked",
     "Let me lay you down flat and elevate your legs"),

    ("peds_syncope_01.seizure_screen",
     "Let me check your blood pressure and heart rate"),
    ("peds_syncope_01.seizure_screen",
     "Were you standing up when you passed out?"),

    ("peds_syncope_01.supine_positioning",
     "Did you feel anything unusual before passing out?"),
    ("peds_syncope_01.supine_positioning",
     "Let me check a blood glucose right now"),

    # ── peds_trauma_01_soft_tissue ────────────────────────────────────────────
    ("peds_trauma_01_soft_tissue.pat_assessment",
     "Apply direct pressure to the scalp laceration immediately"),
    ("peds_trauma_01_soft_tissue.pat_assessment",
     "Check his pupils and GCS after the fall"),

    ("peds_trauma_01_soft_tissue.direct_pressure",
     "Do a full neurological assessment — check pupils and GCS"),
    ("peds_trauma_01_soft_tissue.direct_pressure",
     "How far did he fall? What surface did he land on?"),

    ("peds_trauma_01_soft_tissue.neuro_baseline",
     "Apply direct pressure to the wound with a dressing"),
    ("peds_trauma_01_soft_tissue.neuro_history",
     "Let me prepare for transport to the pediatric ER"),
    ("peds_trauma_01_soft_tissue.neuro_history",
     "I calculated GCS 15/15."),

    ("peds_trauma_01_soft_tissue.mechanism_screen",
     "Apply a pressure dressing to the scalp laceration"),
    ("peds_trauma_01_soft_tissue.mechanism_screen",
     "Let me check his pupils and GCS score"),
    ("peds_trauma_01_soft_tissue.mechanism_screen",
     "What happened?"),

    ("peds_trauma_01_soft_tissue.transport_decision",
     "Apply direct pressure to the wound first"),
    ("peds_trauma_01_soft_tissue.transport_decision",
     "Check his neurological status — any LOC, vomiting?"),

    # ── peds_trauma_02_partial_choking ────────────────────────────────────────
    ("peds_trauma_02_partial_choking.pat_assessment",
     "Set up blow-by oxygen delivery equipment now"),
    ("peds_trauma_02_partial_choking.pat_assessment",
     "Transport immediately to the emergency department"),

    ("peds_trauma_02_partial_choking.partial_obstruction_classification",
     "Let me check her SpO2 and respiratory rate"),
    ("peds_trauma_02_partial_choking.partial_obstruction_classification",
     "Apply blow-by oxygen via NRB mask held near her face"),

    ("peds_trauma_02_partial_choking.encourage_coughing",
     "Keep a close eye on her airway for any deterioration"),
    ("peds_trauma_02_partial_choking.encourage_coughing",
     "We need to load her up and transport right away"),

    ("peds_trauma_02_partial_choking.airway_monitoring",
     "Set up the oxygen delivery for blow-by administration"),
    ("peds_trauma_02_partial_choking.airway_monitoring",
     "Make sure she's in a position of comfort"),

    ("peds_trauma_02_partial_choking.rapid_transport",
     "Check her SpO2 and respiratory effort"),
    ("peds_trauma_02_partial_choking.rapid_transport",
     "Check her SpO2 and respiratory effort"),

    # ── peds_trauma_03_extremity ──────────────────────────────────────────────
    ("peds_trauma_03_extremity.pat_assessment",
     "Check CMS before I attempt any realignment"),
    ("peds_trauma_03_extremity.pat_assessment",
     "I need to splint this fracture joint above and below"),

    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Let me attempt one gentle fracture realignment"),
    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Apply a padded splint to immobilize the fracture"),
    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Check cap refill before splinting"),
    ("peds_trauma_03_extremity.cms_pre_assessment",
     "Any numbness or tingling in the fingers?"),

    ("peds_trauma_03_extremity.fracture_realignment",
     "Check the cap refill and sensation before I start"),
    ("peds_trauma_03_extremity.fracture_realignment",
     "After splinting I'll reassess the CMS distally"),

    ("peds_trauma_03_extremity.splinting",
     "Gently traction and realign the forearm fracture"),
    ("peds_trauma_03_extremity.splinting",
     "Reassessing CMS after the procedure is complete"),

    ("peds_trauma_03_extremity.cms_post_assessment",
     "Apply a padded splint to immobilize above and below"),
    ("peds_trauma_03_extremity.cms_post_assessment",
     "One gentle attempt at realignment along the long axis"),

    # ── peds_trauma_04_burn ───────────────────────────────────────────────────
    ("peds_trauma_04_burn.pat_assessment",
     "Let me check her SpO2 and respiratory rate"),
    ("peds_trauma_04_burn.pat_assessment",
     "Screen for inhalation injury — check for stridor"),

    ("peds_trauma_04_burn.stop_burning",
     "Check for inhalation injury — any soot or singed hairs?"),
    ("peds_trauma_04_burn.stop_burning",
     "Apply a dry sterile dressing to the burn"),

    ("peds_trauma_04_burn.airway_screen",
     "Remove her wet clothing immediately to stop burning"),
    ("peds_trauma_04_burn.airway_screen",
     "Cover the burn with a dry sterile dressing"),

    ("peds_trauma_04_burn.dry_dressing",
     "Remove the wet clothing to stop the burning process"),
    ("peds_trauma_04_burn.dry_dressing",
     "Cover her with a blanket to prevent hypothermia"),

    ("peds_trauma_04_burn.prevent_hypothermia",
     "Remove the wet clothing immediately to stop the burning"),
    ("peds_trauma_04_burn.prevent_hypothermia",
     "Remove the wet clothing and screen for inhalation injury"),

    # ── peds_trauma_05_auto_ped ───────────────────────────────────────────────
    ("peds_trauma_05_auto_ped.pat_assessment",
     "Start BVM ventilation right away — jaw thrust first"),
    ("peds_trauma_05_auto_ped.pat_assessment",
     "Apply the pelvic binder at the greater trochanters"),

    ("peds_trauma_05_auto_ped.airway_bvm",
     "HR 162 and BP 70 over 40 — he's in decompensated shock"),
    ("peds_trauma_05_auto_ped.airway_bvm",
     "Let me apply the pelvic binder and prepare for transport"),

    ("peds_trauma_05_auto_ped.shock_recognition",
     "Jaw thrust and BVM for assisted ventilation right now"),
    ("peds_trauma_05_auto_ped.shock_recognition",
     "Load and go to the trauma center immediately"),

    ("peds_trauma_05_auto_ped.pelvic_binder",
     "Rapid transport — load and go to trauma now"),
    ("peds_trauma_05_auto_ped.pelvic_binder",
     "Let me get BVM ventilation going with a jaw thrust"),

    ("peds_trauma_05_auto_ped.load_and_go",
     "Assess pelvic stability and apply a binder if indicated"),
    ("peds_trauma_05_auto_ped.load_and_go",
     "Jaw thrust and BVM to assist ventilation"),

    # ── peds_trauma_06_handlebar ──────────────────────────────────────────────
    ("peds_trauma_06_handlebar.pat_assessment",
     "There's a circular contusion on the epigastric area — handlebar sign"),
    ("peds_trauma_06_handlebar.pat_assessment",
     "Apply high-flow O2 via NRB mask"),

    ("peds_trauma_06_handlebar.handlebar_sign",
     "HR 130, pale and diaphoretic — this is compensated shock"),
    ("peds_trauma_06_handlebar.handlebar_sign",
     "Apply high-flow oxygen and prepare for rapid transport"),

    ("peds_trauma_06_handlebar.shock_recognition",
     "I see bruising at the epigastric region — handlebar pattern"),
    ("peds_trauma_06_handlebar.shock_recognition",
     "Apply high-flow oxygen via NRB mask right now"),

    ("peds_trauma_06_handlebar.high_flow_o2",
     "Rapid transport to the trauma center with ALS en route"),
    ("peds_trauma_06_handlebar.high_flow_o2",
     "He has signs of compensated shock — HR 130 and diaphoretic"),

    ("peds_trauma_06_handlebar.priority_transport",
     "Apply high-flow O2 via NRB mask at 15 liters"),
    ("peds_trauma_06_handlebar.priority_transport",
     "Handlebar sign is visible — circular contusion on the epigastric region"),

    # ── peds_ams_tox_01 ───────────────────────────────────────────────────────
    # Negative = text about a different item that should NOT fire this pattern
    ("peds_ams_tox_01.pat_assessment",
     "Naloxone 2mg via atomizer — opioid reversal for this child"),
    ("peds_ams_tox_01.pat_assessment",
     "BGL 95 mg/dL — not hypoglycemia; administering naloxone now"),

    ("peds_ams_tox_01.airway_management",
     "BVM ventilations at 12–20 per minute — SpO2 is climbing"),
    ("peds_ams_tox_01.airway_management",
     "Supplemental O2 via non-rebreather at 15 LPM"),

    ("peds_ams_tox_01.bvm_ventilations",
     "Naloxone 2mg via atomizer — opioid reversal in progress"),
    ("peds_ams_tox_01.bvm_ventilations",
     "Supplemental O2 via non-rebreather, SpO2 coming up"),

    ("peds_ams_tox_01.differential_workup",
     "Head-tilt chin-lift to open the airway — manual maneuver first"),
    ("peds_ams_tox_01.differential_workup",
     "BVM ventilations and naloxone — opioid reversal protocol"),
    ("peds_ams_tox_01.differential_workup",
     "I am checking a finger-stick glucose"),
    ("peds_ams_tox_01.differential_workup",
     "Pupils are pinpoint"),

    ("peds_ams_tox_01.naloxone_administration",
     "BVM ventilations at 15 per minute — SpO2 is improving"),
    ("peds_ams_tox_01.naloxone_administration",
     "Head-tilt chin-lift to open the airway — manual maneuver done"),

    # ── adult_cardiac_arrest_01_bls ───────────────────────────────────────────
    ("adult_cardiac_arrest_01_bls.arrest_recognition",
     "Patient is breathing but has altered mental status"),
    ("adult_cardiac_arrest_01_bls.arrest_recognition",
     "What medications is she taking?"),

    # ── newborn_resus_01_nrp ─────────────────────────────────────────────────
    ("newborn_resus_01_nrp.non_vigorous_recognition",
     "Baby is crying and has good tone — vigorous newborn, no resuscitation needed"),
    ("newborn_resus_01_nrp.non_vigorous_recognition",
     "Mother is 28 weeks, what is the gestational age?"),

    # ── peds_cardiac_arrest_01_bls ───────────────────────────────────────────
    ("peds_cardiac_arrest_01_bls.arrest_recognition",
     "Child is crying and moving all extremities"),
    ("peds_cardiac_arrest_01_bls.arrest_recognition",
     "What is the child's weight for dosing?"),

    # ── ems.medical shared items ─────────────────────────────────────────────
    ("ems.medical.repeat_vitals",
     "Let's get an IV established before transport"),
    ("ems.medical.repeat_vitals",
     "Patient is awake and asking what happened"),

    ("ems.medical.sample_history",
     "I'm applying high-flow oxygen via NRB mask right now"),
    ("ems.medical.sample_history",
     "SpO2 is 94 percent, let me reassess after O2"),

    ("ems.medical.treatment_response",
     "I'm going to give oral glucose gel now"),
    ("ems.medical.treatment_response",
     "Can you get me the BGL? I need a reading before I treat"),

    # ── peds_trauma_07_head_injury ───────────────────────────────────────────
    ("peds_trauma_07_head_injury.pat_assessment",
     "Let me check his blood pressure and get a BGL"),
    ("peds_trauma_07_head_injury.pat_assessment",
     "What medications is he on?"),

    ("head_injury.neuro_assessment",
     "Let's apply oxygen and get a SpO2 reading"),
    ("head_injury.neuro_assessment",
     "Any allergies? What did he eat last?"),
    ("head_injury.pupil_assessment",
     "GCS is 14 and he is confused"),
    ("head_injury.pupil_assessment",
     "Any loss of consciousness or vomiting?"),

    ("head_injury.dcap_btls_head",
     "Vital signs are stable, SpO2 is 98 percent on room air"),
    ("head_injury.dcap_btls_head",
     "Let me give him oxygen via NRB at 15 liters"),

    ("head_injury.smr",
     "Checking pupils and GCS score now"),
    ("head_injury.smr",
     "Let me get a blood pressure and SpO2"),

    ("head_injury.priority_transport",
     "I'm palpating the abdomen for tenderness"),
    ("head_injury.priority_transport",
     "What is his blood pressure?"),
    ("head_injury.high_flow_o2",
     "Apply nasal cannula at 2 liters"),
    ("head_injury.high_flow_o2",
     "His oxygen saturation is 98 percent on room air"),

    # ── peds_trauma_08_nat ───────────────────────────────────────────────────
    ("peds_trauma_08_nat.pat_assessment",
     "What medications is she on and any allergies?"),
    ("peds_trauma_08_nat.pat_assessment",
     "Let me get a blood pressure and pulse ox"),

    ("peds_trauma_08_nat.neuro_assessment",
     "Applying oxygen via nasal cannula at 2 liters"),
    ("peds_trauma_08_nat.neuro_assessment",
     "Let me check her blood pressure and SpO2"),
    ("peds_trauma_08_nat.neuro_assessment",
     "GCS is 15 and she is alert"),
    ("peds_trauma_08_nat.neuro_assessment",
     "Pupils are equal and reactive"),

    ("peds_trauma_08_nat.dcap_btls_body_survey",
     "Vital signs are stable, she's breathing at 24 per minute"),
    ("peds_trauma_08_nat.dcap_btls_body_survey",
     "What did she eat today? Any prior medical history?"),

    ("peds_trauma_08_nat.objective_documentation",
     "She is alert and following commands"),
    ("peds_trauma_08_nat.objective_documentation",
     "Applying oxygen and monitoring SpO2"),

    ("peds_trauma_08_nat.transport_and_reporting",
     "Let me assess her pupils and check GCS"),
    ("peds_trauma_08_nat.transport_and_reporting",
     "Any allergies? What is her weight?"),

    ("peds_trauma_08_nat.behavioral_observation",
     "Let me apply oxygen and get a SpO2 reading"),
    ("peds_trauma_08_nat.behavioral_observation",
     "What is her blood pressure? Let me check vitals"),
]


# ── Derived lookup: item_id → set of positive/negative texts ─────────────────

_POSITIVE_COVERAGE: dict[str, list[str]] = {}
_NEGATIVE_COVERAGE: dict[str, list[str]] = {}

for _item_id, _text in POSITIVE_SAMPLES:
    _POSITIVE_COVERAGE.setdefault(_item_id, []).append(_text)

for _item_id, _text in NEGATIVE_SAMPLES:
    _NEGATIVE_COVERAGE.setdefault(_item_id, []).append(_text)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("item_id,text", POSITIVE_SAMPLES)
def test_tier2_positive_match(item_id: str, text: str) -> None:
    """Student text that demonstrates the item must be caught by at least one pattern."""
    assert item_id in _ALL_T2_ITEMS, f"Unknown item_id: {item_id!r} — check spelling"
    assert _matches(item_id, text), (
        f"{item_id}: no pattern matched positive sample {text!r}\n"
        f"  patterns: {_ALL_T2_ITEMS[item_id]}"
    )


@pytest.mark.parametrize("item_id,text", NEGATIVE_SAMPLES)
def test_tier2_negative_no_match(item_id: str, text: str) -> None:
    """Unrelated student text must not be caught by any pattern for that item."""
    assert item_id in _ALL_T2_ITEMS, f"Unknown item_id: {item_id!r} — check spelling"
    assert not _matches(item_id, text), (
        f"{item_id}: unexpected match on negative sample {text!r}\n"
        f"  patterns: {_ALL_T2_ITEMS[item_id]}"
    )


def test_all_tier2_patterns_compile() -> None:
    """Every tier2 pattern must be valid regex — bad patterns are silently skipped in prod."""
    errors: list[str] = []
    for item_id, patterns in _ALL_T2_ITEMS.items():
        for pat in patterns:
            try:
                re.compile(pat)
            except re.error as exc:
                errors.append(f"{item_id}: {pat!r} — {exc}")
    assert not errors, "Invalid regex patterns found:\n" + "\n".join(errors)


def test_all_t2_items_have_positive_samples() -> None:
    """
    Every checklist item with tier2_patterns must have at least one positive sample here.

    Enforcement: adding a new T2 item without a positive sample is a CI failure.
    This prevents silent regressions where a pattern never matches real student text.
    """
    missing = sorted(
        item_id for item_id in _ALL_T2_ITEMS if item_id not in _POSITIVE_COVERAGE
    )
    assert not missing, (
        "These items have tier2_patterns but no positive samples in POSITIVE_SAMPLES:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\nAdd at least one positive sample per item."
    )


def test_all_t2_items_have_negative_samples() -> None:
    """
    Every checklist item with tier2_patterns must have at least one negative sample here.

    Enforcement: a pattern that matches everything is useless — having a negative sample
    proves the pattern is not vacuously broad.
    """
    missing = sorted(
        item_id for item_id in _ALL_T2_ITEMS if item_id not in _NEGATIVE_COVERAGE
    )
    assert not missing, (
        "These items have tier2_patterns but no negative samples in NEGATIVE_SAMPLES:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\nAdd at least one negative sample per item."
    )


def test_no_stale_sample_item_ids() -> None:
    """
    Every item_id in POSITIVE_SAMPLES and NEGATIVE_SAMPLES must exist in a loaded
    scenario checklist.  Catches typos and orphaned samples after checklist refactors.
    """
    known = set(_ALL_T2_ITEMS.keys())
    stale: list[str] = []
    for item_id, _ in POSITIVE_SAMPLES + NEGATIVE_SAMPLES:
        if item_id not in known:
            stale.append(item_id)
    unique_stale = sorted(set(stale))
    assert not unique_stale, (
        "Sample entries reference item_ids not found in any scenario checklist:\n"
        + "\n".join(f"  {s}" for s in unique_stale)
        + "\nRename or remove the stale entries."
    )
