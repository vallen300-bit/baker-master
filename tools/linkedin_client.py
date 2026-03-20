"""
LinkedIn Enrichment Client — Provider-Agnostic

Wraps LinkedIn profile/company enrichment APIs behind a common interface.
Currently supports Netrows. Designed to swap to People Data Labs or
LinkdAPI with zero changes to calling code.

Config: LINKEDIN_API_KEY env var (Netrows API key).
        LINKEDIN_PROVIDER env var (default: "netrows").

Usage:
    from tools.linkedin_client import LinkedInEnricher
    enricher = LinkedInEnricher()
    profile = enricher.enrich_person(name="Peter Storer", company="NVIDIA")
    company = enricher.enrich_company(name="NVIDIA")
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("baker.linkedin_client")

# ─────────────────────────────────────────────────
# Data Models (provider-agnostic)
# ─────────────────────────────────────────────────

@dataclass
class PersonProfile:
    """Enriched person profile — stores only what Baker needs."""
    name: str = ""
    headline: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    photo_url: str = ""
    linkedin_url: str = ""
    summary: str = ""
    work_history: list = field(default_factory=list)   # [{title, company, start, end}]
    education: list = field(default_factory=list)       # [{school, degree, field, start, end}]
    skills: list = field(default_factory=list)          # [str]
    languages: list = field(default_factory=list)       # [str]
    connection_count: int = 0
    enriched_at: str = ""
    provider: str = ""
    raw_url: str = ""  # LinkedIn profile URL if found

    def to_text(self) -> str:
        """Format as readable text for agent tool responses."""
        parts = [f"**{self.name}**"]
        if self.headline:
            parts.append(f"_{self.headline}_")
        if self.title and self.company:
            parts.append(f"Current: {self.title} at {self.company}")
        elif self.title:
            parts.append(f"Current: {self.title}")
        if self.location:
            parts.append(f"Location: {self.location}")
        if self.linkedin_url:
            parts.append(f"LinkedIn: {self.linkedin_url}")
        if self.summary:
            parts.append(f"\n{self.summary[:500]}")
        if self.work_history:
            parts.append("\n**Work History:**")
            for job in self.work_history[:5]:
                dates = ""
                if job.get("start"):
                    dates = f" ({job['start']}"
                    dates += f" – {job.get('end', 'Present')})"
                parts.append(f"- {job.get('title', '?')} at {job.get('company', '?')}{dates}")
        if self.education:
            parts.append("\n**Education:**")
            for edu in self.education[:3]:
                school = edu.get("school", "?")
                degree = edu.get("degree", "")
                fld = edu.get("field", "")
                parts.append(f"- {school}" + (f" — {degree} {fld}" if degree else ""))
        if self.skills:
            parts.append(f"\nSkills: {', '.join(self.skills[:10])}")
        return "\n".join(parts)


@dataclass
class CompanyProfile:
    """Enriched company profile."""
    name: str = ""
    description: str = ""
    industry: str = ""
    website: str = ""
    linkedin_url: str = ""
    employee_count: int = 0
    headquarters: str = ""
    founded: str = ""
    specialties: list = field(default_factory=list)
    enriched_at: str = ""
    provider: str = ""

    def to_text(self) -> str:
        parts = [f"**{self.name}**"]
        if self.industry:
            parts.append(f"Industry: {self.industry}")
        if self.headquarters:
            parts.append(f"HQ: {self.headquarters}")
        if self.employee_count:
            parts.append(f"Employees: {self.employee_count:,}")
        if self.founded:
            parts.append(f"Founded: {self.founded}")
        if self.website:
            parts.append(f"Web: {self.website}")
        if self.description:
            parts.append(f"\n{self.description[:500]}")
        if self.specialties:
            parts.append(f"\nSpecialties: {', '.join(self.specialties[:10])}")
        return "\n".join(parts)


# ─────────────────────────────────────────────────
# Netrows Provider
# ─────────────────────────────────────────────────

_NETROWS_BASE = "https://api.netrows.com/api/v1/linkedin"


def _netrows_enrich_person(
    api_key: str,
    name: str = "",
    linkedin_url: str = "",
    company: str = "",
    email: str = "",
) -> Optional[PersonProfile]:
    """Call Netrows People Profile endpoint."""
    headers = {"x-api-key": api_key, "Accept": "application/json"}

    # Netrows supports lookup by LinkedIn URL or by search
    if linkedin_url:
        url = f"{_NETROWS_BASE}/people/profile"
        params = {"url": linkedin_url}
    else:
        # Search by name + company
        url = f"{_NETROWS_BASE}/people/search"
        query = name
        if company:
            query += f" {company}"
        params = {"query": query, "limit": 1}

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        # Handle search results (returns list)
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        # Handle nested data structure
        if "data" in data:
            data = data["data"]

        # Map Netrows response to PersonProfile
        profile = PersonProfile(
            name=data.get("full_name", data.get("name", name)),
            headline=data.get("headline", ""),
            title=data.get("current_title", data.get("title", "")),
            company=data.get("current_company", data.get("company", "")),
            location=data.get("location", ""),
            photo_url=data.get("profile_picture", data.get("photo_url", "")),
            linkedin_url=data.get("linkedin_url", data.get("url", linkedin_url)),
            summary=data.get("summary", data.get("about", "")),
            connection_count=data.get("connections", 0),
            enriched_at=datetime.now(timezone.utc).isoformat(),
            provider="netrows",
        )

        # Parse work history
        for exp in data.get("experiences", data.get("positions", [])):
            profile.work_history.append({
                "title": exp.get("title", ""),
                "company": exp.get("company", exp.get("company_name", "")),
                "start": exp.get("start_date", exp.get("from", "")),
                "end": exp.get("end_date", exp.get("to", "")),
            })

        # Parse education
        for edu in data.get("education", []):
            profile.education.append({
                "school": edu.get("school", edu.get("institution", "")),
                "degree": edu.get("degree", ""),
                "field": edu.get("field_of_study", edu.get("field", "")),
                "start": edu.get("start_date", ""),
                "end": edu.get("end_date", ""),
            })

        # Parse skills
        profile.skills = data.get("skills", [])
        if isinstance(profile.skills, list) and profile.skills and isinstance(profile.skills[0], dict):
            profile.skills = [s.get("name", str(s)) for s in profile.skills]

        # Parse languages
        profile.languages = data.get("languages", [])
        if isinstance(profile.languages, list) and profile.languages and isinstance(profile.languages[0], dict):
            profile.languages = [l.get("name", str(l)) for l in profile.languages]

        return profile

    except httpx.HTTPStatusError as e:
        logger.error(f"Netrows person lookup failed (HTTP {e.response.status_code}): {e}")
        return None
    except Exception as e:
        logger.error(f"Netrows person lookup failed: {e}")
        return None


def _netrows_enrich_company(
    api_key: str,
    name: str = "",
    linkedin_url: str = "",
) -> Optional[CompanyProfile]:
    """Call Netrows Company Profile endpoint."""
    headers = {"x-api-key": api_key, "Accept": "application/json"}

    if linkedin_url:
        url = f"{_NETROWS_BASE}/companies/profile"
        params = {"url": linkedin_url}
    else:
        url = f"{_NETROWS_BASE}/companies/search"
        params = {"query": name, "limit": 1}

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if "data" in data:
            data = data["data"]

        return CompanyProfile(
            name=data.get("name", name),
            description=data.get("description", data.get("about", "")),
            industry=data.get("industry", ""),
            website=data.get("website", ""),
            linkedin_url=data.get("linkedin_url", data.get("url", linkedin_url)),
            employee_count=data.get("employee_count", data.get("employees", 0)),
            headquarters=data.get("headquarters", data.get("location", "")),
            founded=str(data.get("founded", data.get("founded_year", ""))),
            specialties=data.get("specialties", []),
            enriched_at=datetime.now(timezone.utc).isoformat(),
            provider="netrows",
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"Netrows company lookup failed (HTTP {e.response.status_code}): {e}")
        return None
    except Exception as e:
        logger.error(f"Netrows company lookup failed: {e}")
        return None


# ─────────────────────────────────────────────────
# Main Enricher (provider-agnostic facade)
# ─────────────────────────────────────────────────

class LinkedInEnricher:
    """Provider-agnostic LinkedIn enrichment client."""

    def __init__(self):
        self.api_key = os.getenv("LINKEDIN_API_KEY", "")
        self.provider = os.getenv("LINKEDIN_PROVIDER", "netrows").lower()
        if not self.api_key:
            logger.warning("LINKEDIN_API_KEY not set — enrichment will be unavailable")

    def is_available(self) -> bool:
        """Check if enrichment is configured."""
        return bool(self.api_key)

    def enrich_person(
        self,
        name: str = "",
        linkedin_url: str = "",
        company: str = "",
        email: str = "",
    ) -> Optional[PersonProfile]:
        """Look up a person's professional profile."""
        if not self.api_key:
            return None

        if self.provider == "netrows":
            return _netrows_enrich_person(
                self.api_key, name=name, linkedin_url=linkedin_url,
                company=company, email=email,
            )
        else:
            logger.error(f"Unknown LinkedIn provider: {self.provider}")
            return None

    def enrich_company(
        self,
        name: str = "",
        linkedin_url: str = "",
    ) -> Optional[CompanyProfile]:
        """Look up a company profile."""
        if not self.api_key:
            return None

        if self.provider == "netrows":
            return _netrows_enrich_company(
                self.api_key, name=name, linkedin_url=linkedin_url,
            )
        else:
            logger.error(f"Unknown LinkedIn provider: {self.provider}")
            return None


# Singleton
_enricher: Optional[LinkedInEnricher] = None


def get_enricher() -> LinkedInEnricher:
    """Get or create singleton enricher."""
    global _enricher
    if _enricher is None:
        _enricher = LinkedInEnricher()
    return _enricher
