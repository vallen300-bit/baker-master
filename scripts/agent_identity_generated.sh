#!/usr/bin/env bash
# Generated agent identity data. Do not edit by hand.
# Source: /Users/dimitry/baker-vault/_ops/registries/agent_registry.yml
# SHA256: 4d93d53a4dc72621e63ef2456a6c84700929fad8003fd8af92a35f212be676d9
# Regenerate with: python3 scripts/generate_agent_identity_artifacts.py --write

AGENT_IDENTITY_SYSTEM_RECIPIENT_SLUGS=(director daemon dispatcher)
AGENT_IDENTITY_BUS_AGENT_SLUGS=(lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku russo-ai ben librarian arm publisher designer hag-desk origination-desk ao-desk movie-desk baden-baden-desk brisen-desk cowork-bb-desk cowork-ao-desk cowork-movie-desk cowork-hag-desk cowork-origination-desk cowork-researcher cowork-arm cowork-russo-ai cowork-librarian cowork-aid CM-1 CM-2 CM-3 CM-4 hag-filer the-fund)
AGENT_IDENTITY_VALID_SLUGS=(director daemon dispatcher lead cowork-ah1 deputy deputy-codex cortex aid b1 b2 b3 b4 researcher codex codex-arch clerk clerk-haiku russo-ai ben librarian arm publisher designer hag-desk origination-desk ao-desk movie-desk baden-baden-desk brisen-desk cowork-bb-desk cowork-ao-desk cowork-movie-desk cowork-hag-desk cowork-origination-desk cowork-researcher cowork-arm cowork-russo-ai cowork-librarian cowork-aid CM-1 CM-2 CM-3 CM-4 hag-filer the-fund)
AGENT_IDENTITY_SNAPSHOT_TERMINALS=(lead:/Users/dimitry/bm-aihead1 cowork-ah1:/Users/dimitry/bm-aihead1 deputy:/Users/dimitry/bm-aihead2 deputy-codex:/Users/dimitry/bm-aihead2 aid:/Users/dimitry/baker-vault b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab researcher:/Users/dimitry/baker-vault codex:/Users/dimitry/baker-vault codex-arch:/Users/dimitry/baker-vault clerk:/Users/dimitry/bm-clerk clerk-haiku:/Users/dimitry/bm-clerk russo-ai:/Users/dimitry/baker-vault ben:/Users/dimitry/baker-vault librarian:/Users/dimitry/baker-vault arm:/Users/dimitry/bm-arm publisher:/Users/dimitry/bm-publisher designer:/Users/dimitry/bm-designer hag-desk:/Users/dimitry/baker-vault origination-desk:/Users/dimitry/baker-vault ao-desk:/Users/dimitry/baker-vault movie-desk:/Users/dimitry/baker-vault baden-baden-desk:/Users/dimitry/baker-vault brisen-desk:/Users/dimitry/baker-vault cowork-bb-desk:/Users/dimitry/BB cowork-ao-desk:/Users/dimitry/AO cowork-movie-desk:/Users/dimitry/MOVIE cowork-hag-desk:/Users/dimitry/Hagenauer cowork-origination-desk:/Users/dimitry/Origination cowork-researcher:/Users/dimitry/Researcher cowork-arm:/Users/dimitry/ARM cowork-russo-ai:/Users/dimitry/Russo cowork-librarian:/Users/dimitry/Librarian cowork-aid:/Users/dimitry/AID CM-1:/Users/dimitry/baker-vault CM-2:/Users/dimitry/baker-vault CM-3:/Users/dimitry/baker-vault CM-4:/Users/dimitry/baker-vault hag-filer:/Users/dimitry/baker-vault the-fund:/Users/dimitry/baker-vault)

agent_identity_is_valid_slug() {
  case "${1:-}" in
    director|daemon|dispatcher|lead|cowork-ah1|deputy|deputy-codex|cortex|aid|b1|b2|b3|b4|researcher|codex|codex-arch|clerk|clerk-haiku|russo-ai|ben|librarian|arm|publisher|designer|hag-desk|origination-desk|ao-desk|movie-desk|baden-baden-desk|brisen-desk|cowork-bb-desk|cowork-ao-desk|cowork-movie-desk|cowork-hag-desk|cowork-origination-desk|cowork-researcher|cowork-arm|cowork-russo-ai|cowork-librarian|cowork-aid|CM-1|CM-2|CM-3|CM-4|hag-filer|the-fund) return 0 ;;
    *) return 1 ;;
  esac
}

agent_identity_resolve_role() {
  case "${1:-}" in
    AG-001|ag-001|lead|LEAD|AH1|aihead1|AIHEAD1) printf '%s\n' lead ;;
    AG-002|ag-002|cowork-ah1|COWORK-AH1|cowork_ah1|COWORK_AH1|AH1-APP|cowork|COWORK) printf '%s\n' cowork-ah1 ;;
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
    AG-208|ag-208|ben|BEN) printf '%s\n' ben ;;
    AG-209|ag-209|librarian|LIBRARIAN) printf '%s\n' librarian ;;
    AG-210|ag-210|arm|ARM) printf '%s\n' arm ;;
    AG-211|ag-211|publisher|PUBLISHER) printf '%s\n' publisher ;;
    AG-212|ag-212|designer|DESIGNER|ui-designer|UI-DESIGNER) printf '%s\n' designer ;;
    AG-301|ag-301|hag-desk|HAG-DESK|hag_desk|HAG_DESK|hagenauer-desk|HAGENAUER-DESK) printf '%s\n' hag-desk ;;
    AG-302|ag-302|origination-desk|ORIGINATION-DESK|origination_desk|ORIGINATION_DESK|origination|ORIGINATION) printf '%s\n' origination-desk ;;
    AG-303|ag-303|ao-desk|AO-DESK|ao_desk|AO_DESK|ao|AO) printf '%s\n' ao-desk ;;
    AG-304|ag-304|movie-desk|MOVIE-DESK|movie_desk|MOVIE_DESK|moviedesk|MOVIEDESK|movie|MOVIE) printf '%s\n' movie-desk ;;
    AG-305|ag-305|baden-baden-desk|BADEN-BADEN-DESK|baden_baden_desk|BADEN_BADEN_DESK|bb|BB|bb-desk|BB-DESK|baden-baden|BADEN-BADEN) printf '%s\n' baden-baden-desk ;;
    AG-306|ag-306|brisen-desk|BRISEN-DESK|brisen_desk|BRISEN_DESK) printf '%s\n' brisen-desk ;;
    AG-308|ag-308|cowork-bb-desk|COWORK-BB-DESK|cowork_bb_desk|COWORK_BB_DESK|BB-APP|cowork-bb|COWORK-BB) printf '%s\n' cowork-bb-desk ;;
    AG-309|ag-309|cowork-ao-desk|COWORK-AO-DESK|cowork_ao_desk|COWORK_AO_DESK|AO-APP|cowork-ao|COWORK-AO) printf '%s\n' cowork-ao-desk ;;
    AG-310|ag-310|cowork-movie-desk|COWORK-MOVIE-DESK|cowork_movie_desk|COWORK_MOVIE_DESK|MOVIE-APP|cowork-movie|COWORK-MOVIE) printf '%s\n' cowork-movie-desk ;;
    AG-311|ag-311|cowork-hag-desk|COWORK-HAG-DESK|cowork_hag_desk|COWORK_HAG_DESK|HAG-APP|cowork-hag|COWORK-HAG|cowork-hagenauer-desk|COWORK-HAGENAUER-DESK) printf '%s\n' cowork-hag-desk ;;
    AG-312|ag-312|cowork-origination-desk|COWORK-ORIGINATION-DESK|cowork_origination_desk|COWORK_ORIGINATION_DESK|ORIG-APP|cowork-orig|COWORK-ORIG|cowork-origination|COWORK-ORIGINATION) printf '%s\n' cowork-origination-desk ;;
    AG-313|ag-313|cowork-researcher|COWORK-RESEARCHER|cowork_researcher|COWORK_RESEARCHER|RESEARCHER-APP|cowork-research|COWORK-RESEARCH) printf '%s\n' cowork-researcher ;;
    AG-314|ag-314|cowork-arm|COWORK-ARM|cowork_arm|COWORK_ARM|ARM-APP) printf '%s\n' cowork-arm ;;
    AG-315|ag-315|cowork-russo-ai|COWORK-RUSSO-AI|cowork_russo_ai|COWORK_RUSSO_AI|RUSSO-APP|cowork-russo|COWORK-RUSSO) printf '%s\n' cowork-russo-ai ;;
    AG-316|ag-316|cowork-librarian|COWORK-LIBRARIAN|cowork_librarian|COWORK_LIBRARIAN|LIBRARIAN-APP|cowork-lib|COWORK-LIB) printf '%s\n' cowork-librarian ;;
    AG-317|ag-317|cowork-aid|COWORK-AID|cowork_aid|COWORK_AID|AID-APP|cowork-dennis|COWORK-DENNIS) printf '%s\n' cowork-aid ;;
    AG-401|ag-401|CM-1|CM_1|cm-1) printf '%s\n' CM-1 ;;
    AG-402|ag-402|CM-2|CM_2|cm-2) printf '%s\n' CM-2 ;;
    AG-403|ag-403|CM-3|CM_3|cm-3) printf '%s\n' CM-3 ;;
    AG-404|ag-404|CM-4|CM_4|cm-4) printf '%s\n' CM-4 ;;
    AG-405|ag-405|hag-filer|HAG-FILER|hag_filer|HAG_FILER) printf '%s\n' hag-filer ;;
    AG-406|ag-406|the-fund|THE-FUND|the_fund|THE_FUND|fund|FUND|fund-agent|FUND-AGENT) printf '%s\n' the-fund ;;
    daemon|DAEMON) printf '%s\n' daemon ;;
    dispatcher|DISPATCHER) printf '%s\n' dispatcher ;;
    *) return 1 ;;
  esac
}
