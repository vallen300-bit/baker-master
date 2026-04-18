"""Prompt templates for KBL step evaluators.

Templates are plain ``.txt`` files read once per process per Inv 10 —
prompts are code, not data, and MUST NOT self-modify based on feedback.
Feedback steers model decisions via rendered context blocks rather than
template mutation.
"""
