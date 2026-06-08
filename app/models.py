import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, Date, Float, Index, Text, text, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.database import Base


def new_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id              = Column(String, primary_key=True, default=new_uuid)
    username        = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    is_superuser    = Column(Boolean, nullable=False, default=False)
    is_active       = Column(Boolean, nullable=False, default=True)
    email           = Column(String, nullable=True)
    first_name      = Column(String, nullable=True)
    last_name       = Column(String, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    last_login        = Column(DateTime, nullable=True)
    xp                = Column(Integer,  nullable=False, default=0)
    treats            = Column(Integer,  nullable=False, default=3)
    badges            = Column(JSONB,    nullable=False, default=list)
    peds_count        = Column(Integer,  nullable=False, default=0)
    peds_trauma_count = Column(Integer,  nullable=False, default=0)
    treat_tokens      = Column(JSONB,    nullable=False, default=list)  # pending spend tokens
    drill_xp_day      = Column(Date,     nullable=True)
    drill_xp_today    = Column(Integer,  nullable=False, default=0)
    drill_runs_today  = Column(Integer,  nullable=False, default=0)
    drill_paid_ids    = Column(JSONB,    nullable=False, default=list)  # scenario_ids paid today
    rc_xp_day         = Column(Date,     nullable=True)
    rc_xp_today       = Column(Integer,  nullable=False, default=0)
    pat_xp_day        = Column(Date,     nullable=True)
    pat_xp_today      = Column(Integer,  nullable=False, default=0)
    pat_runs_today    = Column(Integer,  nullable=False, default=0)
    pat_total_correct = Column(Integer,  nullable=False, default=0)
    pat_total_cards   = Column(Integer,  nullable=False, default=0)
    pat_best_accuracy = Column(Integer,  nullable=False, default=0)
    dev_sort_xp_day        = Column(Date,     nullable=True)
    dev_sort_xp_today      = Column(Integer,  nullable=False, default=0)
    dev_sort_runs_today    = Column(Integer,  nullable=False, default=0)
    dev_sort_total_correct = Column(Integer,  nullable=False, default=0)
    dev_sort_total_cards   = Column(Integer,  nullable=False, default=0)
    dev_sort_best_accuracy = Column(Integer,  nullable=False, default=0)
    lexi_group_treat_day   = Column(Date,    nullable=True)
    lexi_group_treats_today = Column(Integer, nullable=False, default=0)
    orientation_completed_at = Column(DateTime, nullable=True, default=None)

    memberships  = relationship("AgencyMember", back_populates="user", lazy="selectin")
    # noload: never auto-fetch — routes query sessions explicitly with filters.
    # Auto-loading all sessions (+ their 7 child relationships each) on every
    # User fetch was the primary latency driver for login and page load.
    sessions     = relationship("SimSession",   back_populates="user", lazy="noload")
    lexi_rounds  = relationship("LexiRound",    back_populates="user", lazy="noload")


class Agency(Base):
    __tablename__ = "agencies"

    id               = Column(String, primary_key=True, default=new_uuid)
    name             = Column(String, nullable=False)
    agency_join_code = Column(String, nullable=True,  unique=True)   # NULL for open-join agencies
    agency_file      = Column(String, nullable=True)    # file stem used for config seeding (e.g. "my_agency"); nullable for DB-only agencies
    is_active        = Column(Boolean, nullable=False, default=True)
    is_open_join     = Column(Boolean, nullable=False, default=False)  # True → joinable without a code
    config           = Column(JSONB,   nullable=True)   # full clinical config JSONB
    narrative_required = Column(Boolean, nullable=False, default=False)
    default_protocol_profile_id = Column(
        String,
        ForeignKey(
            "agency_protocol_profiles.id",
            use_alter=True,
            name="fk_agencies_default_protocol_profile",
        ),
        nullable=True,
        index=True,
    )
    created_at       = Column(DateTime, default=datetime.utcnow)

    members  = relationship("AgencyMember", back_populates="agency", lazy="selectin")
    # noload: loading all agency sessions (+ their 7 child relationships each) on every
    # Agency fetch cascaded into hundreds of queries per request.  Routes that need
    # session data query SimSession directly with agency_id filter.
    sessions = relationship("SimSession",   back_populates="agency", lazy="noload")
    protocol_profiles = relationship(
        "AgencyProtocolProfile",
        back_populates="agency",
        lazy="selectin",
        foreign_keys="AgencyProtocolProfile.agency_id",
    )


class ProtocolSnapshot(Base):
    """Immutable compiled protocol corpus used to pin sessions to a protocol version."""
    __tablename__ = "protocol_snapshots"
    __table_args__ = (
        Index(
            "uq_protocol_snapshots_agency_mca_hash",
            "agency_id",
            "mca_id",
            "content_hash",
            unique=True,
            postgresql_where=text("agency_id IS NOT NULL"),
        ),
        Index(
            "uq_protocol_snapshots_base_mca_hash",
            "mca_id",
            "content_hash",
            unique=True,
            postgresql_where=text("agency_id IS NULL"),
        ),
    )

    id            = Column(String, primary_key=True, default=new_uuid)
    agency_id     = Column(String, ForeignKey("agencies.id"), nullable=True, index=True)
    mca_id        = Column(String, nullable=False, index=True)
    compiled_json = Column(JSONB, nullable=False)
    content_hash  = Column(String, nullable=False, index=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    superseded_at = Column(DateTime, nullable=True)

    agency = relationship("Agency", lazy="selectin")
    sessions = relationship("SimSession", back_populates="protocol_snapshot", lazy="noload")


class AgencyMember(Base):
    """Association object — carries payload columns (role, provider_level, mca)."""
    __tablename__ = "agency_members"
    __table_args__ = (UniqueConstraint("user_id", "agency_id", name="uq_user_agency"),)

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(String, ForeignKey("users.id"),    nullable=False, index=True)
    agency_id      = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    role           = Column(String, nullable=False, default="student")  # student | instructor | admin
    provider_level = Column(String, nullable=False, default="EMT")
    mca            = Column(String, nullable=False, default="mi_base")
    protocol_profile_id = Column(String, ForeignKey("agency_protocol_profiles.id"), nullable=True, index=True)
    protocol_profile_assignment_source = Column(String, nullable=False, default="default")
    joined_at      = Column(DateTime, default=datetime.utcnow)

    user   = relationship("User",   back_populates="memberships")
    agency = relationship("Agency", back_populates="members")
    protocol_profile = relationship("AgencyProtocolProfile", lazy="selectin")


class AgencyProtocolProfile(Base):
    """Agency-approved protocol configuration profile.

    This is intentionally not an official MCA authority record. It captures how
    an agency trains against a base protocol set and any reviewed local profile
    selections. Phase 2 local SOP ingestion adds to this table rather than
    replacing it.
    """
    __tablename__ = "agency_protocol_profiles"
    __table_args__ = (
        Index("ix_agency_protocol_profiles_default", "agency_id", "is_default"),
        UniqueConstraint("agency_id", "display_name", name="uq_agency_protocol_profile_name"),
    )

    id                  = Column(String, primary_key=True, default=new_uuid)
    agency_id           = Column(String, ForeignKey("agencies.id"), nullable=True, index=True)
    display_name        = Column(String, nullable=False)
    profile_type        = Column(String, nullable=False, default="agency_local")
    base_protocol_set   = Column(String, nullable=False, default="NASEMSO")
    official_mca_id     = Column(String, nullable=True, index=True)
    active_protocol_snapshot_id = Column(String, ForeignKey("protocol_snapshots.id"), nullable=True, index=True)
    last_compile_status = Column(String, nullable=True)
    last_compile_error  = Column(String, nullable=True)
    last_compiled_at    = Column(DateTime, nullable=True)
    is_default          = Column(Boolean, nullable=False, default=False)
    is_active           = Column(Boolean, nullable=False, default=True)
    created_by          = Column(String, ForeignKey("users.id"), nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agency = relationship(
        "Agency",
        back_populates="protocol_profiles",
        lazy="selectin",
        foreign_keys=[agency_id],
    )
    selections = relationship(
        "AgencyProtocolSelection",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    active_protocol_snapshot = relationship(
        "ProtocolSnapshot",
        lazy="selectin",
        foreign_keys=[active_protocol_snapshot_id],
    )


class AgencyProtocolSelection(Base):
    """Structured protocol option toggle for a profile.

    Free-text SOP/protocol authoring is deliberately excluded from Phase 1B.
    """
    __tablename__ = "agency_protocol_selections"
    __table_args__ = (
        UniqueConstraint(
            "protocol_profile_id",
            "protocol_id",
            "selection_id",
            name="uq_agency_protocol_selection",
        ),
    )

    id                    = Column(String, primary_key=True, default=new_uuid)
    protocol_profile_id   = Column(String, ForeignKey("agency_protocol_profiles.id"), nullable=False, index=True)
    agency_id             = Column(String, ForeignKey("agencies.id"), nullable=True, index=True)
    mca_id                = Column(String, nullable=True, index=True)
    protocol_id           = Column(String, nullable=False, index=True)
    selection_id          = Column(String, nullable=False)
    is_selected           = Column(Boolean, nullable=False, default=False)
    selected_value        = Column(JSONB, nullable=True)
    base_protocol_version = Column(String, nullable=True)
    updated_by            = Column(String, ForeignKey("users.id"), nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    profile = relationship("AgencyProtocolProfile", back_populates="selections", lazy="selectin")


class AgencySOP(Base):
    """Reviewed agency-local SOP/custom protocol rule scaffold.

    Phase 2A stores and reviews these records only. They are not authoritative
    for prompts, scoring, debriefs, or Medical Control until SME review closes
    and Phase 2B explicitly enables tree-shaking/scope analysis.
    """
    __tablename__ = "agency_sops"
    __table_args__ = (
        Index("ix_agency_sops_agency_status", "agency_id", "status"),
        Index("ix_agency_sops_profile_status", "protocol_profile_id", "status"),
        CheckConstraint(
            "approved_by IS NULL OR submitted_by IS NULL OR approved_by <> submitted_by",
            name="ck_agency_sops_no_self_approval",
        ),
    )

    id                    = Column(String, primary_key=True, default=new_uuid)
    agency_id             = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    protocol_profile_id   = Column(String, ForeignKey("agency_protocol_profiles.id"), nullable=False, index=True)
    version_id            = Column(String, nullable=False, index=True)
    rule_type             = Column(String, nullable=False, index=True)
    status                = Column(String, nullable=False, default="draft", index=True)
    extracted_rule        = Column(Text, nullable=False)
    source_quote          = Column(Text, nullable=True)
    source_label          = Column(String, nullable=True)
    page_number           = Column(Integer, nullable=True)
    clinical_concept_tags = Column(JSONB, nullable=False, default=list)
    intervention_action_ids = Column(JSONB, nullable=False, default=list)
    patch_operations      = Column(JSONB, nullable=True)
    sme_review_status     = Column(String, nullable=False, default="pending", index=True)
    submitted_by          = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    submitted_at          = Column(DateTime, nullable=True)
    approved_by           = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    approved_at           = Column(DateTime, nullable=True)
    rejected_by           = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    rejected_at           = Column(DateTime, nullable=True)
    superseded_at         = Column(DateTime, nullable=True)
    metadata_json         = Column(JSONB, nullable=False, default=dict)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    agency = relationship("Agency", lazy="selectin")
    protocol_profile = relationship("AgencyProtocolProfile", lazy="selectin")


class AgencyAuditLog(Base):
    """Append-only audit trail for agency-level administrative changes."""
    __tablename__ = "agency_audit_logs"

    id             = Column(String, primary_key=True, default=new_uuid)
    agency_id      = Column(String, ForeignKey("agencies.id"), nullable=True, index=True)
    user_id        = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    action         = Column(String, nullable=False, index=True)
    previous_state = Column(JSONB, nullable=True)
    new_state      = Column(JSONB, nullable=True)
    ip_address     = Column(String, nullable=True)
    timestamp      = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProtocolChangeNotification(Base):
    """Provider/admin-facing notification that protocol profile content changed."""
    __tablename__ = "protocol_change_notifications"

    id               = Column(String, primary_key=True, default=new_uuid)
    user_id          = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    agency_id        = Column(String, ForeignKey("agencies.id"), nullable=True, index=True)
    snapshot_id      = Column(String, ForeignKey("protocol_snapshots.id"), nullable=True, index=True)
    summary_markdown = Column(Text, nullable=False)
    seen_at          = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)


class SimSession(Base):
    __tablename__ = "sessions"

    id             = Column(String, primary_key=True, default=new_uuid)
    user_id        = Column(String, ForeignKey("users.id"),    nullable=False, index=True)
    agency_id      = Column(String, ForeignKey("agencies.id"), nullable=True,  index=True)
    agency_file    = Column(String, nullable=True)   # file stem, e.g. "plainfield_fd"
    scenario_id    = Column(String, nullable=False)
    start_time     = Column(DateTime, default=datetime.utcnow)
    ended_at       = Column(DateTime, nullable=True)
    provider_level = Column(String, nullable=True)
    mca            = Column(String, nullable=True)
    treatment_submitted = Column(Boolean, default=False)
    treatment_data      = Column(JSONB,   nullable=True)
    narrative_submitted = Column(Boolean, default=False)
    narrative_data      = Column(JSONB,   nullable=True)
    dmist_submitted          = Column(Boolean, default=False)
    dmist_report             = Column(String,  nullable=True)
    dmist_primary_impression = Column(String,  nullable=True)
    feedback            = Column(String,  nullable=True)
    score               = Column(Integer, nullable=True)   # base assessment score (scenario-specific denominator, legacy field name preserved)
    assessment_score    = Column(Integer, nullable=True)   # raw assessment score (e.g. 80 legacy, 100 migrated rubric)
    narrative_score     = Column(Integer, nullable=True)   # bonus narrative score (XP only); null if not attempted
    narrative_attempted = Column(Boolean, nullable=False, default=False)
    session_type        = Column(String,  nullable=False, default="scenario")  # scenario|random_call
    xp_gross            = Column(Integer, nullable=True)
    xp_earned           = Column(Integer, nullable=True)
    assessment_xp       = Column(Integer, nullable=True)
    narrative_xp        = Column(Integer, nullable=True)
    treats_earned       = Column(Integer, nullable=True)
    treats_spent        = Column(Integer, nullable=False, default=0)  # treat hints used this session
    new_badges          = Column(JSONB,   nullable=True)
    elapsed_min         = Column(Integer, nullable=True)
    scene_entry         = Column(JSONB,   nullable=True)   # PPE, scene approach, PAT assessment
    evidence_packet     = Column(JSONB,   nullable=True)   # Phase 3 adjudication record for audit/instructor review
    # ── Unified scoring engine columns (Phase 1) ──────────────────────────────
    effective_context       = Column(JSONB,   nullable=True)  # resolved session context at scoring time
    effective_checklist_hash = Column(String,  nullable=True)  # SHA-256 of the effective checklist items
    checklist_states        = Column(JSONB,   nullable=True)  # list[ChecklistItemState] — AdjudicationSnapshot
    evidence_references     = Column(JSONB,   nullable=True)  # list[EvidenceReference] keyed by item_id
    score_snapshot          = Column(JSONB,   nullable=True)  # dict[category, CategoryScore] — ScoreSnapshot
    protocol_snapshot_id    = Column(String, ForeignKey("protocol_snapshots.id"), nullable=True, index=True)
    protocol_profile_id     = Column(String, ForeignKey("agency_protocol_profiles.id"), nullable=True, index=True)
    protocol_hash           = Column(String, nullable=True)
    legacy_protocol         = Column(Boolean, nullable=False, default=False)
    active_sop_ids          = Column(JSONB, nullable=False, default=list)
    effective_protocol_excerpt = Column(JSONB, nullable=True)
    debrief_markdown        = Column(Text, nullable=True)

    user   = relationship("User",   back_populates="sessions")
    agency = relationship("Agency", back_populates="sessions")
    protocol_snapshot = relationship("ProtocolSnapshot", back_populates="sessions", lazy="selectin")
    protocol_profile = relationship("AgencyProtocolProfile", lazy="selectin")
    interventions = relationship(
        "Intervention", back_populates="session",
        order_by="Intervention.applied_at", lazy="selectin",
    )
    messages = relationship(
        "ChatMessage", back_populates="session",
        order_by="ChatMessage.timestamp", lazy="selectin",
    )
    findings = relationship(
        "SessionFinding", back_populates="session",
        order_by="SessionFinding.captured_at", lazy="selectin",
    )
    adjudications = relationship(
        "AdjudicatedOutcome", back_populates="session",
        order_by="AdjudicatedOutcome.created_at", lazy="selectin",
    )
    events = relationship(
        "SessionEvent", back_populates="session",
        order_by="SessionEvent.occurred_at", lazy="selectin",
    )


class SessionEvent(Base):
    """Authoritative backend-emitted action record — the migration target for SessionFinding.

    SessionFinding originates from frontend tag parsing and is not independently verified.
    SessionEvent is emitted by the backend on confirmed student actions or auto-detected
    from authoritative simulation state. Evidence packet prefers SessionEvent over
    SessionFinding when both exist for the same clinical dimension.

    event_type taxonomy:
      explicit_assessment — student explicitly confirmed a clinical assessment action
      vital_check         — student explicitly checked vitals (used for reassessment detection)
      clinical_decision   — student made an explicit clinical decision (scope, safety)
      medical_control_contact — backend-confirmed successful Medical Control contact
      intervention_applied — backend-confirmed intervention (redundant with Intervention table
                             but provides a unified event timeline for evidence packet queries)

    source taxonomy:
      frontend_explicit — frontend UI explicit action (button, dedicated form submission)
      backend_auto      — automatically emitted by backend on confirmed state change
      instructor_note   — added by instructor after session (for calibration/review)
    """
    __tablename__ = "session_events"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    event_type   = Column(String, nullable=False)   # see taxonomy above
    event_key    = Column(String, nullable=False)   # normalized stable ID (e.g. "lung_sounds_assessed")
    event_data   = Column(JSONB,   nullable=True)   # additional context (value, notes, linked finding)
    source       = Column(String, nullable=False, default="backend_auto")
    occurred_at  = Column(DateTime, default=datetime.utcnow)

    session = relationship("SimSession", back_populates="events")


class Intervention(Base):
    __tablename__ = "interventions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    name       = Column(String, nullable=False)
    applied_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("SimSession", back_populates="interventions")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role       = Column(String, nullable=False)   # "user" | "model"
    content    = Column(String, nullable=False)
    timestamp  = Column(DateTime, default=datetime.utcnow)

    session = relationship("SimSession", back_populates="messages")


class SessionFinding(Base):
    """Structured assessment findings captured during a simulation.

    TRANSITIONAL INGESTION — findings originate from frontend tag parsing
    (addPcrExam / addPcrHistory / addPcrVitals), not from independently
    verified backend events. Do NOT treat persisted findings as authoritative
    clinical state. This table exists to make findings available to the debrief
    pipeline; the target architecture migrates capture to backend-detected events.

    finding_type: "exam" | "history" | "vital"
    key:          normalized field name (e.g. "Onset", "PMH", "Heart Rate")
    value:        string value as reported by the LLM in-character
    """
    __tablename__ = "session_findings"
    # Dedup rules (enforced by DB indexes, not application code):
    #   history — partial unique index uq_session_finding_history_key on (session_id, finding_type, key).
    #             Re-asked questions upsert in place (last value wins).
    #   exam/vital — partial expression index uq_session_finding_minute_bucket on
    #             (session_id, finding_type, key, value, date_trunc('minute', captured_at)).
    #             Identical readings within the same clock minute are discarded (UI noise);
    #             the same value in a later minute is kept (deliberate reassessment).
    #             Repeated assessments accumulate to preserve disease progression and treatment response.

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    finding_type = Column(String, nullable=False)   # "exam" | "history" | "vital"
    key          = Column(String, nullable=False)
    value        = Column(String, nullable=False)
    source       = Column(String, nullable=True)    # FindingSource enum; NULL = legacy/untyped
    captured_at  = Column(DateTime, default=datetime.utcnow)

    session = relationship("SimSession", back_populates="findings")


class AdjudicatedOutcome(Base):
    """Append-only re-score record.  Never overwrites the original session score.
    Reason taxonomy:
      protocol_revocation — agency published a bad protocol snapshot
      human_appeal        — student/instructor successfully appealed a grade
      system_error        — scoring pipeline bug; correction by system admin
    """
    __tablename__ = "adjudicated_outcomes"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    session_id      = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    reason_type     = Column(String, nullable=False)   # see taxonomy above
    reason_notes    = Column(String, nullable=True)    # free-text explanation
    adjudicated_by  = Column(String, ForeignKey("users.id"), nullable=False)
    corrected_score = Column(Integer, nullable=True)   # normalized 0–100
    corrected_subscores = Column(JSONB, nullable=True) # {clinical, narrative, scope, dmist, professionalism}
    override_findings   = Column(JSONB, nullable=True) # cited evidence packet dimensions being corrected
    created_at      = Column(DateTime, default=datetime.utcnow)

    session = relationship("SimSession", back_populates="adjudications")


class AdjudicationRevision(Base):
    """Append-only archive of superseded adjudication packets.

    Written by adjudicate_and_persist() immediately before overwriting the
    live checklist_states / score_snapshot / evidence_references columns on
    SimSession.  Each row is the complete, verbatim snapshot that was replaced
    so that reruns on changed inputs do not destroy prior audit history.

    Query pattern: SELECT * FROM adjudication_revisions
                   WHERE session_id = :sid ORDER BY superseded_at.
    """
    __tablename__ = "adjudication_revisions"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    session_id          = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    superseded_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    input_hash          = Column(String, nullable=False)   # hash of the inputs that produced this revision
    checklist_states    = Column(JSONB, nullable=True)
    score_snapshot      = Column(JSONB, nullable=True)
    evidence_references = Column(JSONB, nullable=True)


class LexiRound(Base):
    __tablename__ = "lexi_rounds"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    played_at      = Column(DateTime, default=datetime.utcnow)
    score          = Column(Integer, nullable=False)          # 0–5 correct
    xp_earned      = Column(Integer, nullable=False, default=0)
    provider_level = Column(String, nullable=True)
    mca            = Column(String, nullable=True)

    user = relationship("User", back_populates="lexi_rounds")


class LexiGroupSession(Base):
    __tablename__ = "lexi_group_sessions"

    id                       = Column(String, primary_key=True, default=new_uuid)
    agency_id                = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    host_user_id             = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    room_code                = Column(String, nullable=False, unique=True, index=True)
    status                   = Column(String, nullable=False, default="lobby")  # lobby | active | finished
    phase                    = Column(String, nullable=False, default="lobby")  # lobby | question | feedback | round_results | final_results
    round_index              = Column(Integer, nullable=False, default=1)       # 1-based, max 3
    max_rounds               = Column(Integer, nullable=False, default=3)
    current_question_index   = Column(Integer, nullable=False, default=0)       # 0-based
    phase_started_at         = Column(DateTime, nullable=True)
    phase_ends_at            = Column(DateTime, nullable=True)
    effective_provider_level = Column(String, nullable=True)
    mca                      = Column(String, nullable=True)
    participants             = Column(JSONB, nullable=False, default=list)      # [{user_id, display, provider_level, round_wins}]
    rounds                   = Column(JSONB, nullable=False, default=list)      # [{questions:[...], answers:{qidx:{uid:{...}}}, winner_user_id}]
    started_at               = Column(DateTime, nullable=True)
    ended_at                 = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FeedEvent(Base):
    """Append-only log of notable accomplishments shown in the agency ticker."""
    __tablename__ = "feed_events"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    agency_id    = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False)
    display_name = Column(String, nullable=False)
    event_type   = Column(String, nullable=False)  # 'level_up' | 'badge'
    event_label  = Column(String, nullable=False)  # level name or badge name
    event_icon   = Column(String, nullable=True)   # emoji
    created_at   = Column(DateTime, default=datetime.utcnow)


class Challenge(Base):
    __tablename__ = "challenges"

    id           = Column(String, primary_key=True, default=new_uuid)
    agency_id    = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    name         = Column(String, nullable=False)
    description  = Column(String, nullable=True)
    icon         = Column(String, nullable=True)          # emoji
    scenario_ids = Column(JSONB,  nullable=False, default=list)   # legacy — kept for backward compat
    requirements = Column(JSONB,  nullable=True)                  # structured requirements list
    min_score         = Column(Integer, nullable=False, default=70)    # kept in DB; always PASSING_SCORE
    is_active         = Column(Boolean, nullable=False, default=True)
    time_goal_minutes = Column(Integer, nullable=True)                 # optional time target displayed on card
    repeatable        = Column(Boolean, nullable=False, default=False) # allows future per-user repeat attempts
    created_by        = Column(String, ForeignKey("users.id"), nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)


class ChallengeAttempt(Base):
    """Per-user run of a repeatable instructor challenge.

    Challenge rows define the assignment. Attempt rows define a learner's
    start-scoped run so repeat completions do not inherit historical progress.
    """
    __tablename__ = "challenge_attempts"
    __table_args__ = (
        Index("ix_challenge_attempt_user_challenge", "user_id", "challenge_id", "started_at"),
        Index("ix_challenge_attempt_agency_challenge", "agency_id", "challenge_id", "status"),
    )

    id                = Column(String, primary_key=True, default=new_uuid)
    challenge_id      = Column(String, ForeignKey("challenges.id"), nullable=False, index=True)
    agency_id         = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    user_id           = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    attempt_number    = Column(Integer, nullable=False, default=1)
    status            = Column(String(24), nullable=False, default="active")  # active|completed|cancelled
    started_at        = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at      = Column(DateTime, nullable=True)
    completion_summary = Column(JSONB, nullable=True)


class AgencyGroup(Base):
    __tablename__ = "agency_groups"
    __table_args__ = (
        UniqueConstraint("agency_id", "name", name="uq_agency_group_name"),
    )

    id          = Column(String, primary_key=True, default=new_uuid)
    agency_id   = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    name        = Column(String, nullable=False)
    group_type  = Column(String, nullable=False, default="custom")  # station|shift|crew|custom
    created_by  = Column(String, ForeignKey("users.id"), nullable=True)
    is_system   = Column(Boolean, nullable=False, default=False)    # admin/instructor seeded
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgencyGroupMember(Base):
    __tablename__ = "agency_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_agency_group_user"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    group_id   = Column(String, ForeignKey("agency_groups.id"), nullable=False, index=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role       = Column(String, nullable=False, default="member")  # member|creator
    joined_at  = Column(DateTime, default=datetime.utcnow)


class ChallengeTeam(Base):
    __tablename__ = "challenge_teams"

    id                     = Column(String, primary_key=True, default=new_uuid)
    agency_id              = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    name                   = Column(String, nullable=False)
    join_code              = Column(String, nullable=False, unique=True, index=True)
    challenge_type         = Column(String, nullable=False, default="lexi_group")
    created_by_user_id     = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    representative_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    min_members            = Column(Integer, nullable=False, default=2)
    max_members            = Column(Integer, nullable=False, default=5)
    status                 = Column(String, nullable=False, default="forming")  # forming|locked|finished|disbanded
    created_at             = Column(DateTime, default=datetime.utcnow)
    locked_at              = Column(DateTime, nullable=True)
    ended_at               = Column(DateTime, nullable=True)
    metadata_json          = Column(JSONB, nullable=False, default=dict)


class ChallengeTeamMember(Base):
    __tablename__ = "challenge_team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_challenge_team_user"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    team_id    = Column(String, ForeignKey("challenge_teams.id"), nullable=False, index=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role       = Column(String, nullable=False, default="member")  # creator|member
    joined_at  = Column(DateTime, default=datetime.utcnow)
    is_active  = Column(Boolean, nullable=False, default=True)
    left_at    = Column(DateTime, nullable=True)


class TeamInvite(Base):
    __tablename__ = "team_invites"

    id              = Column(String, primary_key=True, default=new_uuid)
    agency_id       = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    challenge_type  = Column(String, nullable=False, default="lexi_group")
    match_id        = Column(String, nullable=True, index=True)
    source_team_id  = Column(String, ForeignKey("challenge_teams.id"), nullable=False, index=True)
    target_team_id  = Column(String, ForeignKey("challenge_teams.id"), nullable=False, index=True)
    created_by      = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    status          = Column(String, nullable=False, default="pending")  # pending|accepted|declined|expired|canceled
    created_at      = Column(DateTime, default=datetime.utcnow)
    expires_at      = Column(DateTime, nullable=False)
    responded_at    = Column(DateTime, nullable=True)
    responded_by    = Column(String, ForeignKey("users.id"), nullable=True)


class TeamMatch(Base):
    __tablename__ = "team_matches"

    id                 = Column(String, primary_key=True, default=new_uuid)
    agency_id          = Column(String, ForeignKey("agencies.id"), nullable=False, index=True)
    challenge_type     = Column(String, nullable=False, default="lexi_group")
    host_team_id       = Column(String, ForeignKey("challenge_teams.id"), nullable=False, index=True)
    host_user_id       = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    status             = Column(String, nullable=False, default="forming")  # forming|ready|active|finished|canceled
    started_session_id = Column(String, ForeignKey("lexi_group_sessions.id"), nullable=True, index=True)
    created_at         = Column(DateTime, default=datetime.utcnow)
    ready_at           = Column(DateTime, nullable=True)
    started_at         = Column(DateTime, nullable=True)
    ended_at           = Column(DateTime, nullable=True)
    metadata_json      = Column(JSONB, nullable=False, default=dict)


class TeamMatchParticipant(Base):
    __tablename__ = "team_match_participants"
    __table_args__ = (
        UniqueConstraint("match_id", "team_id", name="uq_team_match_team"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    match_id    = Column(String, ForeignKey("team_matches.id"), nullable=False, index=True)
    team_id     = Column(String, ForeignKey("challenge_teams.id"), nullable=False, index=True)
    invite_id   = Column(String, ForeignKey("team_invites.id"), nullable=True, index=True)
    is_host     = Column(Boolean, nullable=False, default=False)
    accepted_at = Column(DateTime, nullable=True)
    status      = Column(String, nullable=False, default="accepted")  # accepted|dropped|completed


# ══════════════════════════════════════════════════════════════════════════════
# TOY CHEST GAMIFICATION MODELS
# ══════════════════════════════════════════════════════════════════════════════

class ToySeries(Base):
    """A named release wave of toys (e.g. 'Series 1').  Published_at drives the
    'New Arrivals' badge — any series published after a user's last login that
    they haven't viewed yet gets flagged on their next login."""
    __tablename__ = "toy_series"

    series_tag   = Column(String, primary_key=True)          # e.g. "series_1"
    display_name = Column(String, nullable=False)             # e.g. "Series 1"
    published_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    toys        = relationship("Toy",            back_populates="series", lazy="select")
    user_views  = relationship("UserSeriesView", back_populates="series", lazy="select")


class ToyCategory(Base):
    """Maps to an adventure district on the game map (e.g. 'Puppy Park').
    scenario_categories is a JSONB list of scenario category strings that belong
    to this district, used to route a completed session to the right toy pool."""
    __tablename__ = "toy_categories"

    id                        = Column(String, primary_key=True, default=new_uuid)
    name                      = Column(String, nullable=False, unique=True)  # e.g. "puppy_park"
    display_name              = Column(String, nullable=False)               # e.g. "Puppy Park"
    scenario_categories       = Column(JSONB,   nullable=False, default=list)
    # e.g. ["pediatric_medical", "pediatric_trauma"]
    default_mastery_threshold = Column(Integer, nullable=False, default=85)
    # Percentage of assessment_score (out of 80) required for a Mastery clear

    toys          = relationship("Toy",             back_populates="category",      lazy="select")
    pity_counters = relationship("UserPityCounter", back_populates="category",      lazy="select")


class Toy(Base):
    """A single collectible toy.  Rarities: common | rare | epic.
    Epics are always is_earn_only=True and cannot appear in the shop.
    duplicate_treat_value: Treats awarded when this toy is granted but already owned.
    map_gate_id: peds map_id (e.g. "pm2") that must be completed before this toy
                 appears in the shop; NULL = no gate (always purchasable when in shop)."""
    __tablename__ = "toys"

    id                    = Column(String,  primary_key=True, default=new_uuid)
    category_id           = Column(String,  ForeignKey("toy_categories.id"), nullable=False, index=True)
    series_tag            = Column(String,  ForeignKey("toy_series.series_tag"), nullable=False, index=True)
    name                  = Column(String,  nullable=False)           # internal key
    display_name          = Column(String,  nullable=False)           # shown in UI
    rarity                = Column(String,  nullable=False)           # common | rare | epic
    image_key             = Column(String,  nullable=True)            # frontend asset key
    duplicate_treat_value = Column(Integer, nullable=False, default=1)
    # Defaults: common=1, rare=3, epic=5 per spec
    is_shop_only          = Column(Boolean, nullable=False, default=False)
    is_earn_only          = Column(Boolean, nullable=False, default=False)  # Epics
    shop_price            = Column(Integer, nullable=True)            # Treats; NULL = not in shop
    is_active             = Column(Boolean, nullable=False, default=True)
    map_gate_id           = Column(String,  nullable=True)            # peds map_id gate; NULL = ungated
    created_at            = Column(DateTime, default=datetime.utcnow)

    category = relationship("ToyCategory",  back_populates="toys", lazy="select")
    series   = relationship("ToySeries",    back_populates="toys", lazy="select")
    grants   = relationship("ToyGrantLog",  back_populates="toy",  lazy="select")
    owners   = relationship("UserToy",      back_populates="toy",  lazy="select")


class UserToy(Base):
    """Association: which toys a user owns (one row per unique toy earned)."""
    __tablename__ = "user_toys"
    __table_args__ = (UniqueConstraint("user_id", "toy_id", name="uq_user_toy"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    toy_id       = Column(String, ForeignKey("toys.id"),  nullable=False, index=True)
    granted_at   = Column(DateTime, default=datetime.utcnow)
    grant_source = Column(String, nullable=False)
    # first_clear | mastery | personal_best | pity | shop

    toy  = relationship("Toy",  back_populates="owners", lazy="select")
    user = relationship("User",                           lazy="select")


class ToyGrantLog(Base):
    """Immutable audit log of every toy grant attempt (including duplicates)."""
    __tablename__ = "toy_grant_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(String, ForeignKey("users.id"),    nullable=False, index=True)
    toy_id         = Column(String, ForeignKey("toys.id"),     nullable=False, index=True)
    session_id     = Column(String, ForeignKey("sessions.id"), nullable=True,  index=True)
    grant_source   = Column(String, nullable=False)
    # first_clear | mastery | epic_attempt | personal_best | pity_common | pity_rare | shop
    is_duplicate   = Column(Boolean, nullable=False, default=False)
    treats_awarded = Column(Integer, nullable=False, default=0)
    # Treats given instead of toy when is_duplicate=True
    created_at     = Column(DateTime, default=datetime.utcnow)

    toy = relationship("Toy", back_populates="grants", lazy="select")


class UserPityCounter(Base):
    """Per-user, per-category bad-luck protection counters.  Tracks how many
    eligible scenario completions have passed without a toy drop at each rarity.
    All counters reset (cascade) when a toy of that rarity or higher is granted."""
    __tablename__ = "user_pity_counters"
    __table_args__ = (UniqueConstraint("user_id", "category_id", name="uq_user_pity_category"),)

    id                         = Column(Integer, primary_key=True, autoincrement=True)
    user_id                    = Column(String, ForeignKey("users.id"),           nullable=False, index=True)
    category_id                = Column(String, ForeignKey("toy_categories.id"),  nullable=False, index=True)
    attempts_since_last_common = Column(Integer, nullable=False, default=0)
    attempts_since_last_rare   = Column(Integer, nullable=False, default=0)
    attempts_since_last_epic   = Column(Integer, nullable=False, default=0)

    category = relationship("ToyCategory", back_populates="pity_counters", lazy="select")


class UserSeriesView(Base):
    """Records when a user has dismissed the 'New Arrivals' badge for a series.
    Absence of a row means the badge should be shown."""
    __tablename__ = "user_series_views"
    __table_args__ = (UniqueConstraint("user_id", "series_tag", name="uq_user_series_view"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(String, ForeignKey("users.id"),                 nullable=False, index=True)
    series_tag = Column(String, ForeignKey("toy_series.series_tag"),    nullable=False, index=True)
    viewed_at  = Column(DateTime, default=datetime.utcnow)

    series = relationship("ToySeries", back_populates="user_views", lazy="select")


class UserNote(Base):
    """Personal learning notes authored by a student.

    Notes are user-scoped only — no agency visibility, no instructor access.
    A note may be linked to a specific session (session_id set), linked to a
    scenario without a session (scenario_id set, session_id null), or free-form
    (both null).  session_id is SET NULL on session deletion so the note survives.

    tags is a JSONB array of lowercase, stripped, deduplicated strings.
    updated_at uses onupdate=datetime.utcnow so the ORM refreshes it on every flush.
    """
    __tablename__ = "user_notes"

    id          = Column(String,   primary_key=True, default=new_uuid)
    user_id     = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    session_id  = Column(String,   ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    scenario_id = Column(String,   nullable=True)
    title       = Column(String(200), nullable=False)
    body        = Column(String,   nullable=False)
    tags        = Column(JSONB,    nullable=False, default=list)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=False, default=datetime.utcnow,
                         onupdate=datetime.utcnow)


class StudentScenarioHistory(Base):
    """Per-user, per-scenario SM-2 spaced repetition state for Random Call selection.

    One row per (user_id, agency_id, scenario_id). Updated after every Random Call
    completion via _update_rc_history(). SimSession is not used for this because
    SM-2 requires aggregate state that must survive across multiple runs.
    """
    __tablename__ = "student_scenario_history"
    __table_args__ = (
        UniqueConstraint("user_id", "agency_id", "scenario_id", name="uq_student_scenario"),
    )

    id                    = Column(String,   primary_key=True, default=new_uuid)
    user_id               = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    agency_id             = Column(String,   ForeignKey("agencies.id"), nullable=False, index=True)
    scenario_id           = Column(String,   nullable=False)
    interval_days         = Column(Float,    nullable=False, default=1.0)
    ease_factor           = Column(Float,    nullable=False, default=2.5)
    last_random_call_date = Column(DateTime, nullable=True)
    last_rc_score         = Column(Integer,  nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# PEDIATRIC MAP PROGRESSION MODELS
# ══════════════════════════════════════════════════════════════════════════════

class PedsMapProgress(Base):
    """Records per-user map completion for gateway and convergence nodes that
    cannot be tracked via scenario completion (PM1, PT1, PM7, PT8).

    map_id values: "pm1" | "pt1" | "pm7" | "pt8"
      pm1 — written by submit_dev_sort_result on first play
      pt1 — written by POST /api/me/peds/gateway-complete (rule_of_nines, or auto on map visit)
      pm7 — written by POST /api/me/peds/keys/claim when medical key is awarded
      pt8 — written by POST /api/me/peds/keys/claim when trauma key is awarded
    """
    __tablename__ = "peds_map_progress"
    __table_args__ = (UniqueConstraint("user_id", "map_id", name="uq_peds_map_progress"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(String,  ForeignKey("users.id"), nullable=False, index=True)
    map_id       = Column(String,  nullable=False)
    completed_at = Column(DateTime, default=datetime.utcnow)


class PedsKey(Base):
    """Records which Scout's Toy Quest convergence keys a user has earned.

    key_id values:
      "key_peds_med_golden_stethoscope" — awarded at PM7 when all 6 medical toys collected
      "key_peds_trm_silver_shears"      — awarded at PT8 when all 7 trauma toys collected
    """
    __tablename__ = "peds_keys"
    __table_args__ = (UniqueConstraint("user_id", "key_id", name="uq_peds_key"),)

    id        = Column(Integer, primary_key=True, autoincrement=True)
    user_id   = Column(String,  ForeignKey("users.id"), nullable=False, index=True)
    key_id    = Column(String,  nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow)


class MinigameResult(Base):
    """Generic per-play result record for mini-games that don't have dedicated User columns.

    Used by POST /api/me/minigames/result for ten4_facesp, adult_child_ap_swipe,
    lung_sounds_matcher, history_maker, peds_gcs_calculator, and future games.
    """
    __tablename__ = "minigame_results"

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    user_id     = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    game_id     = Column(String(64), nullable=False)
    run_id      = Column(String(128), nullable=True)
    score       = Column(Integer,  default=0)   # 0–100
    total       = Column(Integer,  default=0)
    correct     = Column(Integer,  default=0)
    elapsed_sec = Column(Integer,  default=0)
    xp_earned   = Column(Integer,  default=0)
    mistake_tags = Column(JSONB,    nullable=True)
    mode         = Column(String(64), nullable=True)
    hint_count   = Column(Integer,  default=0)
    sequence_data = Column(JSONB,    nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class MinigameReferenceCard(Base):
    """Earned mini-game reference cards unlocked by deterministic pass gates."""

    __tablename__ = "minigame_reference_cards"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_minigame_reference_card"),)

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    user_id     = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    card_id     = Column(String(128), nullable=False)
    unlocked_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# NOTEBOOK MODELS
# ══════════════════════════════════════════════════════════════════════════════

class NotebookConditionEntry(Base):
    """Condition + treatment reference unlocked when a learner correctly identifies
    the primary impression in a scenario's impression_challenge.

    One row per (user_id, scenario_id).  Upserted on correct/acceptable debrief;
    never written when the condition is locked.  reference_md is the rendered
    sections 8–9 markdown from the AI debrief (Condition — and Treatment & Protocol
    Reference sections).
    """
    __tablename__ = "notebook_condition_entries"
    __table_args__ = (UniqueConstraint("user_id", "scenario_id", name="uq_nb_condition"),)

    id             = Column(Integer,  primary_key=True, autoincrement=True)
    user_id        = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    scenario_id    = Column(String,   nullable=False)
    scenario_title = Column(String,   nullable=False)
    condition_name = Column(String,   nullable=False)
    reference_md   = Column(String,   nullable=False)
    unlocked_at    = Column(DateTime, nullable=False, default=datetime.utcnow)


class NotebookLearningEntry(Base):
    """Learning page unlocked after completing a mini-game that has a learning_page.md.

    One row per (user_id, game_id).  Upserted on first completion of a game that
    has a static learning page.  content_md is the raw markdown from the game's
    learning_page.md file (served from static/data/games/<game_id>/learning_page.md).
    """
    __tablename__ = "notebook_learning_entries"
    __table_args__ = (UniqueConstraint("user_id", "game_id", name="uq_nb_learning"),)

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    user_id     = Column(String,   ForeignKey("users.id"), nullable=False, index=True)
    game_id     = Column(String(64), nullable=False)
    game_title  = Column(String,   nullable=False)
    content_md  = Column(String,   nullable=False)
    unlocked_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CeTimeLog(Base):
    """Append-only CE time ledger.

    Each row records a discrete block of time a user spent on a CE-eligible
    activity.  Total CE time for a user is SUM(seconds).  Repeats accumulate —
    every scenario or drill play adds a row.

    activity_type values:
      "orientation" — fixed award on first orientation completion
      "scenario"    — wall-clock duration of a full simulation session
      "drill"       — elapsed_sec from a mini-game play (PAT, dev-sort, etc.)
    """
    __tablename__ = "ce_time_log"

    id            = Column(Integer,    primary_key=True, autoincrement=True)
    user_id       = Column(String,     ForeignKey("users.id"), nullable=False, index=True)
    activity_type = Column(String(32), nullable=False)
    source_id     = Column(String(128), nullable=True)   # session_id or run_id
    scenario_id   = Column(String(128), nullable=True)   # optional context
    seconds       = Column(Integer,    nullable=False)
    created_at    = Column(DateTime,   nullable=False, default=datetime.utcnow)


class WsTicket(Base):
    """Short-lived single-use ticket for WebSocket authentication.

    Issued by POST /api/ws-ticket; consumed atomically by the WebSocket handler
    using UPDATE ... RETURNING to prevent replay. Expires 30 seconds after issuance.
    Replaces JWT in the WebSocket URL query parameter.
    """
    __tablename__ = "ws_tickets"

    ticket_id  = Column(String, primary_key=True, default=new_uuid)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    agency_id  = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    consumed   = Column(Boolean, nullable=False, default=False)


class ScormAttempt(Base):
    """SCORM attempt record: tracks node completion and scores for LMS-launched learners.

    One row per (lms_student_id, module_id). Resume returns the existing row.
    Backend is authoritative; cmi.suspend_data is a compact read-only mirror
    written by the SCORM client after each node completion.

    node_scores:       {node_id: int 0-100} — best score per node
    node_completed:    {node_id: bool}      — ever reached completed=true
    node_mistake_tags: {node_id: [str]}     — latest mistake tags per node
    """
    __tablename__ = "scorm_attempts"
    __table_args__ = (
        UniqueConstraint("lms_student_id", "module_id", name="uq_scorm_attempt"),
    )

    attempt_id        = Column(String, primary_key=True, default=new_uuid)
    lms_student_id    = Column(String, nullable=False, index=True)
    lms_student_name  = Column(String, nullable=True)
    module_id         = Column(String(64), nullable=False)
    user_id           = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    node_scores       = Column(JSONB, nullable=False, default=dict)
    node_completed    = Column(JSONB, nullable=False, default=dict)
    node_mistake_tags = Column(JSONB, nullable=True)
    status            = Column(String(32), nullable=False, default="incomplete")
    active_launch_id  = Column(String(64), nullable=True)
    active_launch_seen_at = Column(DateTime, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at        = Column(DateTime, nullable=False, default=datetime.utcnow)


class RefreshToken(Base):
    """Server-side refresh token for JWT rotation (S-07).

    Issued at login and at each /api/token/refresh call (rotation).
    Logout revokes the active token immediately. agency_id stores the
    active agency context so the refresh endpoint can reconstruct the
    same-scope access token without requiring the (possibly expired)
    session cookie.
    """
    __tablename__ = "refresh_tokens"

    token_id    = Column(String, primary_key=True, default=new_uuid)
    user_id     = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    agency_id   = Column(String, nullable=True)
    expires_at  = Column(DateTime, nullable=False)
    revoked     = Column(Boolean, nullable=False, default=False)
    replaced_by = Column(String, nullable=True)
