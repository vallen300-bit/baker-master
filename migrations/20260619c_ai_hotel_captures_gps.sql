-- AI_HOTEL_GPS_CAPTURE_1: capture-level GPS evidence on a field capture.
--
-- Director (site-scouting): "add the exact GPS location… the location is very
-- important for me to research." The phone reads its GPS at capture time
-- (navigator.geolocation, with permission) — Baker cannot recover location
-- after the fact. GPS is therefore HARD EVIDENCE, stored SEPARATELY from any
-- dictated `address_or_location_clue` (a claim that site_visit deliberately
-- leaves null to avoid hallucinated locations). Director ratified: the
-- GPS-derived address is verified evidence, distinct from the dictated clue.
--
-- One GPS fix per capture (capture-level), linked to all its cards. Reverse-
-- geocoding runs ONCE server-side at insert (never on the Field Notes render)
-- and is non-fatal: a geocode failure leaves the coordinates intact with
-- gps_address_status='geocode_failed'.

-- == migrate:up ==

ALTER TABLE ai_hotel_captures
    ADD COLUMN IF NOT EXISTS gps_lat            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS gps_lng            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS gps_accuracy_m     REAL,
    ADD COLUMN IF NOT EXISTS gps_captured_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS gps_address        TEXT,
    ADD COLUMN IF NOT EXISTS gps_address_source TEXT,
    ADD COLUMN IF NOT EXISTS gps_address_status TEXT;

-- CHECK constraints as defense-in-depth (server-side validation is the first
-- line). Wrapped in a DO block so the migration is idempotent — ADD CONSTRAINT
-- has no IF NOT EXISTS form, and re-running must not error.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_hotel_captures_gps_lat_range') THEN
        ALTER TABLE ai_hotel_captures
            ADD CONSTRAINT ai_hotel_captures_gps_lat_range
            CHECK (gps_lat IS NULL OR (gps_lat BETWEEN -90 AND 90));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_hotel_captures_gps_lng_range') THEN
        ALTER TABLE ai_hotel_captures
            ADD CONSTRAINT ai_hotel_captures_gps_lng_range
            CHECK (gps_lng IS NULL OR (gps_lng BETWEEN -180 AND 180));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_hotel_captures_gps_accuracy_nonneg') THEN
        ALTER TABLE ai_hotel_captures
            ADD CONSTRAINT ai_hotel_captures_gps_accuracy_nonneg
            CHECK (gps_accuracy_m IS NULL OR gps_accuracy_m >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_hotel_captures_gps_address_source') THEN
        ALTER TABLE ai_hotel_captures
            ADD CONSTRAINT ai_hotel_captures_gps_address_source
            CHECK (gps_address_source IN ('google','nominatim') OR gps_address_source IS NULL);
    END IF;
END
$$;

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- undo the columns it just added on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- ALTER TABLE ai_hotel_captures
--     DROP CONSTRAINT IF EXISTS ai_hotel_captures_gps_lat_range,
--     DROP CONSTRAINT IF EXISTS ai_hotel_captures_gps_lng_range,
--     DROP CONSTRAINT IF EXISTS ai_hotel_captures_gps_accuracy_nonneg,
--     DROP CONSTRAINT IF EXISTS ai_hotel_captures_gps_address_source,
--     DROP COLUMN IF EXISTS gps_lat,
--     DROP COLUMN IF EXISTS gps_lng,
--     DROP COLUMN IF EXISTS gps_accuracy_m,
--     DROP COLUMN IF EXISTS gps_captured_at,
--     DROP COLUMN IF EXISTS gps_address,
--     DROP COLUMN IF EXISTS gps_address_source,
--     DROP COLUMN IF EXISTS gps_address_status;
-- COMMIT;
