# VIP Tier Cleanup — Director Review Required

**Date:** 2026-03-21
**Action needed:** Confirm which contacts should be downgraded from T1/T2.

Baker auto-classified these contacts as VIP based on message frequency, but some are personal/operational staff, not business VIPs. Suggested downgrades below — Director confirms, then I execute.

## Suggested Downgrades (T1 → T3)

| Name | Current | Suggested | Reason |
|------|---------|-----------|--------|
| Orysia 2 | T1 | T3 | Vienna cleaner — not business VIP |
| Mohammed | T1 | T3 | Personal assistant / household logistics |
| +7 915 077-70-70 Dasha | T1 | T3 | Family/personal contact |
| Ralf Graeser Van Cleef | T1 | T2 or T3 | Personal friend — social, not business-critical? |

## Suggested Downgrades (T2 → T3)

| Name | Current | Suggested | Reason |
|------|---------|-----------|--------|
| MOVIE Concierge Victor Rodriguez | T2 | T3 | Building concierge |
| Christina | T2 | T3 | Administrative/scheduling |
| Philippe Ruh | T2 | T3 | Travel coordinator |

## Keep as-is (confirmed VIP)

These T1s look correct:
- Edita Vallen (wife + business)
- Andrey Oskolkov (principal investor)
- Laurent Kleitman (CEO Mandarin Oriental)
- Alric Ofenheimer (attorney)
- Peter Storer (NVIDIA)
- Sandy Hefftz (Bellboy Robotics)
- Marcus Pisani, JC Balducci, Franck Muller, Tasos (key partners)
- Dennis Egorenkov / Dennis New (Brisen team)
- Volodia Nesteruk, Christophe Buchwalder (close network)
- Christian Merz, Constantinos Pohanis (projects)

## How to execute

Once Director confirms, I run:
```sql
UPDATE vip_contacts SET tier = 3 WHERE id IN (confirmed_ids);
```

No data is deleted — contacts just stop triggering VIP-level alerts.
