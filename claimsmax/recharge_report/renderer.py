"""Render RechargeReport into the canonical Pichler/HEAD-4 markdown scaffold."""
from pathlib import Path

from .schema import RechargeReport, SECTION_ORDER


CANONICAL_TEMPLATE_PATH = Path(
    "/Users/dimitry/baker-vault/wiki/_templates/pichler-head4-template.md"
)


def render_to_markdown(
    report: RechargeReport,
    template_path: Path = CANONICAL_TEMPLATE_PATH,
) -> str:
    """Substitute report fields into scaffold template. Returns rendered markdown."""
    if not template_path.exists():
        raise FileNotFoundError(f"Canonical template missing at {template_path}")
    template = template_path.read_text(encoding="utf-8")
    data = report.model_dump()
    rendered = template
    for _heading, field in SECTION_ORDER:
        slot = "{{" + field + "}}"
        if slot not in rendered:
            raise ValueError(
                f"Template missing slot for field {field!r} (expected {slot!r})"
            )
        rendered = rendered.replace(slot, data[field])
    if "{{" in rendered:
        unfilled = [line.strip() for line in rendered.splitlines() if "{{" in line]
        raise ValueError(f"Template has unfilled slots after render: {unfilled}")
    return rendered
