#!/usr/bin/env bash
# Generated agent identity data. Do not edit by hand.
# Source: /Users/dimitry/baker-vault/_ops/registries/agent_registry.yml
# SHA256: 851feca2101e2324f4bfdddd0db0bc5f3be0ec1163195e52de922f2c0f1a732d
# Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write

AGENT_IDENTITY_SYSTEM_RECIPIENT_SLUGS=(director daemon)
AGENT_IDENTITY_BUS_AGENT_SLUGS=(lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku hag-desk origination-desk CM-1 CM-2 CM-3 CM-4 hag-filer)
AGENT_IDENTITY_VALID_SLUGS=(director daemon lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku hag-desk origination-desk CM-1 CM-2 CM-3 CM-4 hag-filer)
AGENT_IDENTITY_SNAPSHOT_TERMINALS=(lead:/Users/dimitry/bm-aihead1 cowork-ah1:/Users/dimitry/bm-aihead1 deputy:/Users/dimitry/bm-aihead2 deputy-codex:/Users/dimitry/bm-aihead2 aid:/Users/dimitry/baker-vault b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab researcher:/Users/dimitry/baker-vault codex:/Users/dimitry/baker-vault codex-arch:/Users/dimitry/baker-vault clerk:/Users/dimitry/bm-clerk clerk-haiku:/Users/dimitry/bm-clerk hag-desk:/Users/dimitry/baker-vault origination-desk:/Users/dimitry/baker-vault CM-1:/Users/dimitry/baker-vault CM-2:/Users/dimitry/baker-vault CM-3:/Users/dimitry/baker-vault CM-4:/Users/dimitry/baker-vault hag-filer:/Users/dimitry/baker-vault)

agent_identity_is_valid_slug() {
  case "${1:-}" in
    director|daemon|lead|cowork-ah1|deputy|deputy-codex|cortex|aid|b1|b2|b3|b4|researcher|codex|codex-arch|clerk|clerk-haiku|hag-desk|origination-desk|CM-1|CM-2|CM-3|CM-4|hag-filer) return 0 ;;
    *) return 1 ;;
  esac
}

agent_identity_resolve_role() {
  case "${1:-}" in
    lead|LEAD|AH1|aihead1|AIHEAD1) printf '%s\n' lead ;;
    cowork-ah1|COWORK-AH1|cowork_ah1|COWORK_AH1|AH1-APP) printf '%s\n' cowork-ah1 ;;
    deputy|DEPUTY|AH2|aihead2|AIHEAD2) printf '%s\n' deputy ;;
    deputy-codex|DEPUTY-CODEX|deputy_codex|DEPUTY_CODEX) printf '%s\n' deputy-codex ;;
    cortex|CORTEX) printf '%s\n' cortex ;;
    aid|AID|ai-dennis|AI-DENNIS) printf '%s\n' aid ;;
    b1|B1) printf '%s\n' b1 ;;
    b2|B2) printf '%s\n' b2 ;;
    b3|B3) printf '%s\n' b3 ;;
    b4|B4) printf '%s\n' b4 ;;
    researcher|RESEARCHER|research-agent|RESEARCH-AGENT) printf '%s\n' researcher ;;
    codex|CODEX) printf '%s\n' codex ;;
    codex-arch|CODEX-ARCH|codex_arch|CODEX_ARCH) printf '%s\n' codex-arch ;;
    clerk|CLERK) printf '%s\n' clerk ;;
    clerk-haiku|CLERK-HAIKU|clerk_haiku|CLERK_HAIKU) printf '%s\n' clerk-haiku ;;
    hag-desk|HAG-DESK|hag_desk|HAG_DESK|hagenauer-desk|HAGENAUER-DESK) printf '%s\n' hag-desk ;;
    origination-desk|ORIGINATION-DESK|origination_desk|ORIGINATION_DESK) printf '%s\n' origination-desk ;;
    CM-1|CM_1|cm-1) printf '%s\n' CM-1 ;;
    CM-2|CM_2|cm-2) printf '%s\n' CM-2 ;;
    CM-3|CM_3|cm-3) printf '%s\n' CM-3 ;;
    CM-4|CM_4|cm-4) printf '%s\n' CM-4 ;;
    hag-filer|HAG-FILER|hag_filer|HAG_FILER) printf '%s\n' hag-filer ;;
    *) return 1 ;;
  esac
}
