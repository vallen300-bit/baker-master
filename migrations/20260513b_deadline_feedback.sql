-- DEADLINE_FEEDBACK_LOOP_1: labeled click-feedback corpus for phase-3 classifier training.
--
-- Each row is one Director click on a surfaced deadline. Rows accumulate as the
-- ground-truth corpus for SIGNAL_CLASSIFIER_TIER2_1 (phase 3, dispatched after
-- 2+ weeks of clicks land here).
--
-- feedback_type values:
--   'confirm'        — Director marked the deadline as done (Mark Done click)
--   'mute'           — Director dismissed the deadline as noise (Dismiss click)
--   'wrong_matter'   — Director flagged matter_slug as incorrect; corrected_matter_slug captures the right one
--   'wrong_deadline' — Director flagged the row as "not actually a deadline" (extraction error)
--
-- The deadline row's status flip (dismiss/complete) happens in the same request
-- — feedback rows are write-only and additive. Deleting a deadline does NOT
-- cascade-delete its feedback rows (history-preserving by design; phase 3
-- reads even orphaned feedback to learn from past mistakes).

CREATE TABLE IF NOT EXISTS deadline_feedback (
    id                       SERIAL PRIMARY KEY,
    deadline_id              INTEGER NOT NULL,
    feedback_type            VARCHAR(20) NOT NULL,
    original_matter_slug     TEXT,
    corrected_matter_slug    TEXT,
    original_description     TEXT NOT NULL,
    original_source_type     VARCHAR(50),
    director_note            TEXT,
    clicked_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT deadline_feedback_type_check
        CHECK (feedback_type IN ('confirm', 'mute', 'wrong_matter', 'wrong_deadline'))
);

CREATE INDEX IF NOT EXISTS idx_deadline_feedback_clicked_at
    ON deadline_feedback (clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_deadline_feedback_deadline_id
    ON deadline_feedback (deadline_id);
CREATE INDEX IF NOT EXISTS idx_deadline_feedback_type
    ON deadline_feedback (feedback_type);
