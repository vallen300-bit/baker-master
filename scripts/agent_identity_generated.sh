#!/usr/bin/env bash
# Generated agent identity data. Do not edit by hand.
# Source: /Users/dimitry/baker-vault/_ops/registries/agent_registry.yml
# SHA256: 8ae61aac1c7d8d581371325b4f386d3cf7705a0b03c885e16d7884b7c54201e7
# Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write

AGENT_IDENTITY_SYSTEM_RECIPIENT_SLUGS=(director daemon)
AGENT_IDENTITY_BUS_AGENT_SLUGS=(lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku russo-ai deep55 hag-desk origination-desk ao-desk baden-baden-desk CM-1 CM-2 CM-3 CM-4 hag-filer)
AGENT_IDENTITY_VALID_SLUGS=(director daemon lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku russo-ai deep55 hag-desk origination-desk ao-desk baden-baden-desk CM-1 CM-2 CM-3 CM-4 hag-filer)
AGENT_IDENTITY_SNAPSHOT_TERMINALS=(lead:/Users/dimitry/bm-aihead1 cowork-ah1:/Users/dimitry/bm-aihead1 deputy:/Users/dimitry/bm-aihead2 deputy-codex:/Users/dimitry/bm-aihead2 aid:/Users/dimitry/baker-vault b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab researcher:/Users/dimitry/baker-vault codex:/Users/dimitry/baker-vault codex-arch:/Users/dimitry/baker-vault clerk:/Users/dimitry/bm-clerk clerk-haiku:/Users/dimitry/bm-clerk russo-ai:/Users/dimitry/baker-vault deep55:/Users/dimitry/baker-vault hag-desk:/Users/dimitry/baker-vault origination-desk:/Users/dimitry/baker-vault ao-desk:/Users/dimitry/baker-vault baden-baden-desk:/Users/dimitry/baker-vault CM-1:/Users/dimitry/baker-vault CM-2:/Users/dimitry/baker-vault CM-3:/Users/dimitry/baker-vault CM-4:/Users/dimitry/baker-vault hag-filer:/Users/dimitry/baker-vault)

agent_identity_is_valid_slug() {
  case "${1:-}" in
    director|daemon|lead|cowork-ah1|deputy|deputy-codex|cortex|aid|b1|b2|b3|b4|researcher|codex|codex-arch|clerk|clerk-haiku|russo-ai|deep55|hag-desk|origination-desk|ao-desk|baden-baden-desk|CM-1|CM-2|CM-3|CM-4|hag-filer) return 0 ;;
    *) return 1 ;;
  esac
}

agent_identity_resolve_role() {
  case "${1:-}" in
    AG-001|ag-001|lead|LEAD|AH1|aihead1|AIHEAD1) printf '%s\n' lead ;;
    AG-002|ag-002|cowork-ah1|COWORK-AH1|cowork_ah1|COWORK_AH1|AH1-APP) printf '%s\n' cowork-ah1 ;;
    AG-003|ag-003|deputy|DEPUTY|AH2|aihead2|AIHEAD2) printf '%s\n' deputy ;;
    AG-004|ag-004|deputy-codex|DEPUTY-CODEX|deputy_codex|DEPUTY_CODEX) printf '%s\n' deputy-codex ;;
    AG-005|ag-005|cortex|CORTEX) printf '%s\n' cortex ;;
    AG-006|ag-006|aid|AID|ai-dennis|AI-DENNIS) printf '%s\n' aid ;;
    AG-101|ag-101|b1|B1) printf '%s\n' b1 ;;
    AG-102|ag-102|b2|B2) printf '%s\n' b2 ;;
    AG-103|ag-103|b3|B3) printf '%s\n' b3 ;;
    AG-104|ag-104|b4|B4) printf '%s\n' b4 ;;
    AG-201|ag-201|researcher|RESEARCHER|research-agent|RESEARCH-AGENT) printf '%s\n' researcher ;;
    AG-202|ag-202|codex|CODEX) printf '%s\n' codex ;;
    AG-203|ag-203|codex-arch|CODEX-ARCH|codex_arch|CODEX_ARCH) printf '%s\n' codex-arch ;;
    AG-204|ag-204|clerk|CLERK) printf '%s\n' clerk ;;
    AG-205|ag-205|clerk-haiku|CLERK-HAIKU|clerk_haiku|CLERK_HAIKU) printf '%s\n' clerk-haiku ;;
    AG-206|ag-206|russo-ai|RUSSO-AI|russo_ai|RUSSO_AI) printf '%s\n' russo-ai ;;
    AG-207|ag-207|deep55|DEEP55|deep-55|DEEP-55|gpt-5.5-raw|GPT-5.5-RAW) printf '%s\n' deep55 ;;
    AG-301|ag-301|hag-desk|HAG-DESK|hag_desk|HAG_DESK|hagenauer-desk|HAGENAUER-DESK) printf '%s\n' hag-desk ;;
    AG-302|ag-302|origination-desk|ORIGINATION-DESK|origination_desk|ORIGINATION_DESK) printf '%s\n' origination-desk ;;
    AG-303|ag-303|ao-desk|AO-DESK|ao_desk|AO_DESK) printf '%s\n' ao-desk ;;
    AG-305|ag-305|baden-baden-desk|BADEN-BADEN-DESK|baden_baden_desk|BADEN_BADEN_DESK) printf '%s\n' baden-baden-desk ;;
    AG-401|ag-401|CM-1|CM_1|cm-1) printf '%s\n' CM-1 ;;
    AG-402|ag-402|CM-2|CM_2|cm-2) printf '%s\n' CM-2 ;;
    AG-403|ag-403|CM-3|CM_3|cm-3) printf '%s\n' CM-3 ;;
    AG-404|ag-404|CM-4|CM_4|cm-4) printf '%s\n' CM-4 ;;
    AG-405|ag-405|hag-filer|HAG-FILER|hag_filer|HAG_FILER) printf '%s\n' hag-filer ;;
    daemon|DAEMON) printf '%s\n' daemon ;;
    *) return 1 ;;
  esac
}
