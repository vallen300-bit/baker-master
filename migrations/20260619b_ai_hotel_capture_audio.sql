-- AI_HOTEL_FIELD_NOTES_AND_AUDIO_1 (WP-A): persist raw dictation audio.
--
-- Until now the recorder transcribed audio and DISCARDED the bytes — Baker kept
-- the transcript + photos + card but no replayable audio. For site visits and
-- counterparty conversations that's weaker than "recording" implies. This child
-- table stores the raw audio (base64, like the image child table) linked to its
-- capture, persisted BEFORE transcription so a transcription failure never loses
-- the recording. The transcript is mirrored here on success.
--
-- List views must NOT load audio_b64 (payload blowup) — the feed returns audio
-- METADATA only; the full base64 is fetched on demand from card detail.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS ai_hotel_capture_audio (
    id               BIGSERIAL PRIMARY KEY,
    capture_id       BIGINT NOT NULL REFERENCES ai_hotel_captures(id) ON DELETE CASCADE,
    ordinal          INT NOT NULL DEFAULT 0,
    audio_b64        TEXT NOT NULL,            -- raw recorded audio, base64 (cap = capture audio cap)
    audio_media      TEXT NOT NULL,            -- e.g. audio/webm, audio/mp4
    duration_seconds INT,                       -- client-reported clip length (nullable)
    transcript_text  TEXT,                      -- mirror of the transcript folded into the capture note
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_capture_audio_capture
    ON ai_hotel_capture_audio (capture_id, ordinal);

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- drop the table it just created on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- DROP TABLE IF EXISTS ai_hotel_capture_audio;
-- COMMIT;
