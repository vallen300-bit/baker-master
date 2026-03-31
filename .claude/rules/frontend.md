---
paths:
  - "outputs/static/**/*.js"
  - "outputs/static/**/*.css"
  - "outputs/templates/**/*.html"
---

# Frontend Rules

- iOS PWA cache bust: append `?v=N` on CSS/JS references (increment on change)
- Vanilla JS only — no frameworks, no build tools
- Test on mobile viewport (375px) — dashboard is primarily used as PWA on iPhone
