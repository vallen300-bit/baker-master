"""
Sentinel Trigger — Whoop Health Data (Read-Only)
Polls Whoop API v2 daily for Recovery, Sleep, Cycle (strain), and Workout data.
Upserts results to whoop_records table via store_back.
Embeds health summaries to baker-health Qdrant collection.
Feeds significant health events into the pipeline for classification + alert drafting.
Called by scheduler every 24 hours (86400s default).
"""
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.whoop_trigger")

_WATERMARK_KEY = "whoop"

# Classification thresholds
_RECOVERY_LOW = 34       # below this → whoop_recovery_low
_RECOVERY_HIGH = 67      # at or above → whoop_recovery_high
_STRAIN_HIGH = 18        # at or above → whoop_strain_high
_SLEEP_DEFICIT_MS = 6 * 3600 * 1000   # 6 hours in milliseconds
_HRV_DEVIATION_PCT = 0.30             # 30% deviation from rolling avg


def _get_client():
    """Get the global WhoopClient singleton."""
    from triggers.whoop_client import WhoopClient
    return WhoopClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _content_hash(record_data: dict) -> str:
    """MD5 hash of key score fields for change detection."""
    parts = [
        str(record_data.get("whoop_id", "")),
        str(record_data.get("record_type", "")),
        str(record_data.get("recovery_score", "")),
        str(record_data.get("hrv_rmssd", "")),
        str(record_data.get("resting_hr", "")),
        str(record_data.get("strain", "")),
        str(record_data.get("sleep_total_ms", "")),
        str(record_data.get("sleep_efficiency", "")),
        str(record_data.get("kilojoule", "")),
        str(record_data.get("avg_hr", "")),
        str(record_data.get("max_hr", "")),
        str(record_data.get("score_state", "")),
    ]
    text = "|".join(parts)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _ms_to_hours(ms) -> float:
    """Convert milliseconds to hours, rounded to 1 decimal."""
    if ms is None:
        return 0.0
    try:
        return round(int(ms) / 3_600_000, 1)
    except (ValueError, TypeError):
        return 0.0


def _build_record_data(record: dict, record_type: str) -> dict:
    """Transform Whoop API response into normalized storage dict.

    record_type: 'recovery', 'sleep', 'cycle', 'workout'

    Returns dict with keys:
        whoop_id, record_type, recorded_at,
        score fields (flattened), raw_json,
        content_text (human-readable for embedding),
        content_hash (MD5 for dedup)
    """
    score = record.get("score") or {}
    record_id = str(record.get("id", ""))

    # Common timestamp — use created_at or start from the record
    recorded_at = (
        record.get("created_at")
        or record.get("start")
        or record.get("updated_at")
        or datetime.now(timezone.utc).isoformat()
    )

    # Parse date for content_text display
    try:
        if isinstance(recorded_at, str):
            dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        else:
            dt = recorded_at
        date_str = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_str = str(recorded_at)[:10]

    # Initialize all score fields as None
    data = {
        "whoop_id": record_id,
        "record_type": record_type,
        "recorded_at": recorded_at,
        "recovery_score": None,
        "hrv_rmssd": None,
        "resting_hr": None,
        "spo2": None,
        "skin_temp": None,
        "strain": None,
        "sleep_total_ms": None,
        "sleep_efficiency": None,
        "kilojoule": None,
        "avg_hr": None,
        "max_hr": None,
        "score_state": record.get("score_state"),
        "raw_json": record,
    }

    if record_type == "recovery":
        data["recovery_score"] = score.get("recovery_score")
        data["hrv_rmssd"] = score.get("hrv_rmssd_milli")
        data["resting_hr"] = score.get("resting_heart_rate")
        data["spo2"] = score.get("spo2_percentage")
        data["skin_temp"] = score.get("skin_temp_celsius")

        rs = data["recovery_score"]
        hrv = data["hrv_rmssd"]
        rhr = data["resting_hr"]
        spo2 = data["spo2"]
        data["content_text"] = (
            f"[Whoop Recovery] {date_str} — "
            f"Score: {rs}%, HRV: {hrv}ms, RHR: {rhr}bpm, SpO2: {spo2}%"
        )

    elif record_type == "sleep":
        total_ms = score.get("total_in_bed_time_milli")
        eff = score.get("sleep_efficiency_percentage")
        rem_ms = score.get("total_rem_sleep_time_milli")
        deep_ms = score.get("total_slow_wave_sleep_time_milli")

        data["sleep_total_ms"] = total_ms
        data["sleep_efficiency"] = eff

        total_h = _ms_to_hours(total_ms)
        rem_h = _ms_to_hours(rem_ms)
        deep_h = _ms_to_hours(deep_ms)
        data["content_text"] = (
            f"[Whoop Sleep] {date_str} — "
            f"{total_h}h total, Efficiency: {eff}%, REM: {rem_h}h, Deep: {deep_h}h"
        )

    elif record_type == "cycle":
        data["strain"] = score.get("strain")
        data["kilojoule"] = score.get("kilojoule")
        data["avg_hr"] = score.get("average_heart_rate")
        data["max_hr"] = score.get("max_heart_rate")

        strain_val = data["strain"]
        kj = data["kilojoule"]
        kcal = round(float(kj) / 4.184) if kj else 0
        data["content_text"] = (
            f"[Whoop Strain] {date_str} — "
            f"Strain: {strain_val}/21, Cals: {kcal}, "
            f"Avg HR: {data['avg_hr']}bpm, Max HR: {data['max_hr']}bpm"
        )

    elif record_type == "workout":
        data["strain"] = score.get("strain")
        data["kilojoule"] = score.get("kilojoule")
        data["avg_hr"] = score.get("average_heart_rate")
        data["max_hr"] = score.get("max_heart_rate")

        sport_id = record.get("sport_id", "?")
        # Duration from start/end if available
        start_t = record.get("start")
        end_t = record.get("end")
        dur_min = 0
        if start_t and end_t:
            try:
                s = datetime.fromisoformat(start_t.replace("Z", "+00:00"))
                e = datetime.fromisoformat(end_t.replace("Z", "+00:00"))
                dur_min = round((e - s).total_seconds() / 60)
            except (ValueError, TypeError):
                pass

        data["content_text"] = (
            f"[Whoop Workout] {date_str} — "
            f"Sport: {sport_id}, Strain: {data['strain']}/21, Duration: {dur_min}min"
        )

    else:
        data["content_text"] = f"[Whoop {record_type}] {date_str}"

    # Compute content hash for dedup
    data["content_hash"] = _content_hash(data)

    return data


def _embed_to_qdrant(store, record_data: dict):
    """Embed health record content_text into baker-health Qdrant collection."""
    content_text = record_data.get("content_text", "")
    if not content_text:
        return

    metadata = {
        "whoop_id": record_data.get("whoop_id"),
        "record_type": record_data.get("record_type"),
        "recorded_at": record_data.get("recorded_at"),
        "recovery_score": record_data.get("recovery_score"),
        "strain": record_data.get("strain"),
        "sleep_total_ms": record_data.get("sleep_total_ms"),
        "content_type": "health",
        "author": "whoop",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": f"whoop:{record_data.get('record_type', '')}:{record_data.get('whoop_id', '')}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    try:
        store.store_document(content_text, metadata, collection="baker-health")
    except Exception as e:
        logger.warning(f"Failed to embed Whoop record {record_data.get('whoop_id')} to Qdrant: {e}")


def _get_hrv_rolling_avg(store) -> float:
    """Get 7-day rolling average HRV from whoop_records for anomaly detection.

    Returns 0.0 if insufficient data.
    """
    try:
        conn = store._get_conn()
        if not conn:
            return 0.0
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT AVG(hrv_rmssd)
                FROM whoop_records
                WHERE record_type = 'recovery'
                  AND hrv_rmssd IS NOT NULL
                  AND recorded_at >= NOW() - INTERVAL '7 days'
            """)
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                return float(row[0])
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Could not compute HRV rolling avg: {e}")
    return 0.0


def _classify_health_event(record_data: dict, hrv_avg: float = 0.0) -> str:
    """Classify health record for pipeline feed.

    Returns:
        'whoop_recovery_low'      — recovery_score < 34%
        'whoop_recovery_high'     — recovery_score >= 67%
        'whoop_strain_high'       — strain >= 18
        'whoop_sleep_deficit'     — total sleep < 6 hours
        'whoop_hrv_anomaly'       — HRV deviates >30% from 7-day rolling avg
        'whoop_routine'           — normal reading, no pipeline feed needed
    """
    rtype = record_data.get("record_type")

    if rtype == "recovery":
        rs = record_data.get("recovery_score")
        if rs is not None:
            if rs < _RECOVERY_LOW:
                return "whoop_recovery_low"
            if rs >= _RECOVERY_HIGH:
                return "whoop_recovery_high"

        # HRV anomaly check
        hrv = record_data.get("hrv_rmssd")
        if hrv is not None and hrv_avg > 0:
            deviation = abs(hrv - hrv_avg) / hrv_avg
            if deviation > _HRV_DEVIATION_PCT:
                return "whoop_hrv_anomaly"

    elif rtype == "cycle" or rtype == "workout":
        strain = record_data.get("strain")
        if strain is not None and strain >= _STRAIN_HIGH:
            return "whoop_strain_high"

    elif rtype == "sleep":
        total_ms = record_data.get("sleep_total_ms")
        if total_ms is not None and total_ms < _SLEEP_DEFICIT_MS:
            return "whoop_sleep_deficit"

    return "whoop_routine"


def _feed_to_pipeline(record_data: dict, classification: str):
    """Feed significant health event into Sentinel pipeline."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        trigger = TriggerEvent(
            type=classification,
            content=record_data["content_text"],
            source_id=f"whoop:{record_data.get('whoop_id', '?')}",
            contact_name=None,  # Director's own health data
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for Whoop record {record_data.get('whoop_id')}: {e}")


def run_whoop_poll():
    """Main entry point — called by scheduler every 24 hours.

    Algorithm:
    1. Get watermark (last poll) or default to 7 days ago (first run backfill)
    2. Determine date range: start..now in ISO 8601
    3. Fetch recovery, sleep, cycle, workout records
    4. For each record: build data, upsert to PostgreSQL, embed to Qdrant,
       classify, and feed non-routine events to pipeline
    5. Update watermark
    """
    logger.info("Whoop trigger: starting poll...")

    try:
        client = _get_client()
    except Exception as e:
        logger.error(f"Whoop trigger: failed to init client: {e}")
        return

    store = _get_store()

    # Determine date range
    last_poll = trigger_state.get_watermark(_WATERMARK_KEY)
    now_utc = datetime.now(timezone.utc)

    # First run: backfill 7 days
    if last_poll is None or (now_utc - last_poll) > timedelta(days=8):
        start_dt = now_utc - timedelta(days=7)
        logger.info("Whoop: first run or stale watermark — backfilling 7 days")
    else:
        start_dt = last_poll

    # Format as ISO 8601 for Whoop API
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    logger.info(f"Whoop poll range: {start_str} → {end_str}")

    # Counters
    counts = {"recovery": 0, "sleep": 0, "cycle": 0, "workout": 0}
    skipped = 0
    qdrant_writes = 0
    pipeline_feeds = 0

    # Get HRV rolling average for anomaly detection
    hrv_avg = _get_hrv_rolling_avg(store)

    # Fetch all record types
    record_batches = []
    for rtype, fetch_fn in [
        ("recovery", client.get_recovery),
        ("sleep", client.get_sleep),
        ("cycle", client.get_cycle),
        ("workout", client.get_workout),
    ]:
        try:
            records = fetch_fn(start_str, end_str)
            logger.info(f"Whoop: fetched {len(records)} {rtype} records")
            for rec in records:
                record_batches.append((rec, rtype))
        except Exception as e:
            logger.error(f"Whoop: failed to fetch {rtype}: {e}")

    # Process all records
    for record, rtype in record_batches:
        try:
            record_data = _build_record_data(record, rtype)

            # Upsert to PostgreSQL
            result = store.upsert_whoop_record(record_data)
            if result == "skipped":
                skipped += 1
                continue

            counts[rtype] = counts.get(rtype, 0) + 1

            # Embed to Qdrant
            _embed_to_qdrant(store, record_data)
            qdrant_writes += 1

            # Classify and feed pipeline
            classification = _classify_health_event(record_data, hrv_avg)
            if classification != "whoop_routine":
                _feed_to_pipeline(record_data, classification)
                pipeline_feeds += 1

        except Exception as e:
            logger.error(f"Whoop: failed to process {rtype} record {record.get('id')}: {e}")

    # Update watermark
    trigger_state.set_watermark(_WATERMARK_KEY, now_utc)

    logger.info(
        f"Whoop poll complete: "
        f"{counts['recovery']} recovery, {counts['sleep']} sleep, "
        f"{counts['cycle']} cycle, {counts['workout']} workout processed, "
        f"{skipped} skipped (unchanged), {qdrant_writes} Qdrant writes, "
        f"{pipeline_feeds} pipeline feeds"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_whoop_poll()
