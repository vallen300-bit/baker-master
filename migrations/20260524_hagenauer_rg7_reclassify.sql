-- HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1 — reclassify 6 mistagged transcripts.
--
-- Source: hag-desk audit (bus #831, 2026-05-24). Each UPDATE is idempotent
-- (uses date/title/source predicate matching exactly one row, with explicit
-- matter_slug='hagenauer-rg7' guard so re-runs are no-ops).
--
-- Pre-flight evidence (b2 verified against prod 2026-05-24, bus #864):
--   Row 1 → ao             HIT=1 id=01KCKEBK01JAV2MJXBF1XD7MXM (by id)
--   Row 2 → brisen         HIT=1 id=01KFN5PBTS28JWYNESAK1FS575
--   Row 3 → mrci           HIT=1 id=01KFDX1HGJJT1XZSJ7Y281XQFK
--   Row 4 → mrci           HIT=1 id=01KEXT8C35FZX1FXVG7N5G3JYR
--   Row 5 → brisen         HIT=1 id=plaud_a2c401c3d1ee1cf92d3d3438f7103903
--   Row 6 → lilienmatt     HIT=1 id=plaud_7e6313b06d70f44a28b9ada0110e6e19
--
-- AH1-T ratified Option A 2026-05-24 (bus #861): 'ao-holding' → 'ao' (canonical
-- per baker-vault/slugs.yml:40). Brief title-ILIKE typos for rows 2/3/6
-- corrected against verified prod titles (bus #864).
--
-- To re-verify before apply:
--   SELECT id, meeting_date, title FROM meeting_transcripts
--    WHERE matter_slug = 'hagenauer-rg7'
--    ORDER BY meeting_date;

-- 1. 2025-12-16 — AO debt restructure → ao
UPDATE meeting_transcripts SET matter_slug = 'ao'
 WHERE id = '01KCKEBK01JAV2MJXBF1XD7MXM' AND matter_slug = 'hagenauer-rg7';

-- 2. 2026-01-23 — Fireflies "Jan 23, 11:16 AM" — RG7 equity participation → brisen
UPDATE meeting_transcripts SET matter_slug = 'brisen'
 WHERE meeting_date::date = DATE '2026-01-23'
   AND source = 'fireflies'
   AND title ILIKE '%Jan 23, 11:16%'
   AND matter_slug = 'hagenauer-rg7';

-- 3. 2026-01-20 — "Baden post meeting with Kogel wife + DV + Siegfried" → mrci
UPDATE meeting_transcripts SET matter_slug = 'mrci'
 WHERE meeting_date::date = DATE '2026-01-20'
   AND title ILIKE '%Baden post meeting with Kogel%'
   AND matter_slug = 'hagenauer-rg7';

-- 4. 2026-01-14 — "MRCI Feasibility DV + EV + Siegfried" → mrci
UPDATE meeting_transcripts SET matter_slug = 'mrci'
 WHERE meeting_date::date = DATE '2026-01-14'
   AND title ILIKE '%MRCI Feasibility%'
   AND matter_slug = 'hagenauer-rg7';

-- 5. 2026-05-05 plaud — "Shareholding Restructuring + Shareholder Loans + Okara Financing" → brisen
UPDATE meeting_transcripts SET matter_slug = 'brisen'
 WHERE meeting_date::date = DATE '2026-05-05'
   AND source = 'plaud'
   AND title ILIKE '%Shareholding Restructuring%'
   AND matter_slug = 'hagenauer-rg7';

-- 6. 2026-05-18 plaud — "Strategy Meeting: Asset Management + F&B + Annaberg + Tools" → lilienmatt
UPDATE meeting_transcripts SET matter_slug = 'lilienmatt'
 WHERE meeting_date::date = DATE '2026-05-18'
   AND source = 'plaud'
   AND title ILIKE '%Strategy Meeting: Asset Management%'
   AND matter_slug = 'hagenauer-rg7';
