"""
AO Signal Detector — DEPRECATED wrapper.
All signal detection now handled by pm_signal_detector.py (PM_REGISTRY-driven).
This file kept for backward compatibility only.
"""
from orchestrator.pm_signal_detector import (
    detect_relevant_pms_text,
    detect_relevant_pms_whatsapp,
    flag_pm_signal,
)


def is_ao_relevant_text(sender: str, text: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_text()."""
    return "ao_pm" in detect_relevant_pms_text(sender, text)


def is_ao_relevant_meeting(title: str, participants: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_meeting()."""
    from orchestrator.pm_signal_detector import detect_relevant_pms_meeting
    return "ao_pm" in detect_relevant_pms_meeting(title, participants)


def is_ao_whatsapp_message(sender_name: str, text: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_whatsapp()."""
    return "ao_pm" in detect_relevant_pms_whatsapp(sender_name, text)


def flag_ao_signal(channel: str, source: str, summary: str, timestamp=None):
    """DEPRECATED: Use pm_signal_detector.flag_pm_signal('ao_pm', ...)."""
    flag_pm_signal("ao_pm", channel, source, summary, timestamp)
