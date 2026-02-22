"""
Quick script: build fireflies_transcripts.json from MCP-extracted data.
Run once, then use bulk_ingest.py to index into Qdrant.
"""
import json, sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent.parent / "03_data" / "fireflies" / "fireflies_transcripts.json"

transcripts = [
    {
        "id": "01KHP9CYD6DM03GVN4E0BWGR8V",
        "title": "Feb 17, 05:12 PM",
        "date": "2026-02-17",
        "duration": "68",
        "participants": "vallen300@gmail.com",
        "summary": "The discussion centered around integrating various communication and project management tools, including ClickUp, Twitter, and Fireflies, to create a unified platform for better project visibility and faster decision-making. The team highlighted the importance of using AI, such as Voyager AI and JSON, to automate workflows and improve data accuracy. Subcontractor management was another key topic, with a focus on developing a claim management application for transparency and collaboration. Additionally, the integration of AI connectors for finance and compliance projects was emphasized to assist in data handling and legal checks. The team also prioritized real-time updates through automatic meeting summaries and informal social gatherings to enhance team cohesion and communication.",
        "action_items": "Consolidate memory and connect social platforms including Twitter and WhatsApp through ClickUp for project management\nReview application for claim management involving subcontractors and coworkers, categorized under tier four, implying escalation or priority classification\nArrange or confirm informal dinner meeting with a backend team member to discuss hotel-related issues",
    },
    {
        "id": "01KHP6QRHNJF75HSZWS20HJ6MA",
        "title": "Feb 17, 04:25 PM",
        "date": "2026-02-17",
        "duration": "28",
        "participants": "vallen300@gmail.com",
        "summary": "The team discussed strategies to manage contract liabilities associated with subcontractor failures, emphasizing the importance of limiting financial risk and clarifying responsibilities. They highlighted the need for a framework allowing reciprocal guarantees, readying for potential subcontractor insolvencies, and integrating subcontractor staff to retain talent. Significant budget deviations, including overruns related to subcontractor issues, were identified, prompting a need for rigorous cost validation and strategic damage claims management. The baseline budget was set at 7.4 million, with additional costs classified as damages to protect against inflated claims. The team also agreed on a transparent cost calculation framework for ongoing negotiations.",
        "action_items": "Thomas: Review and provide detailed breakdown of costs such as site installation, concrete works, and others flagged as unjustified to identify damage vs. contractual costs\nEric: Assist in analyzing subcontractor damage claims and confirm accuracy of damage lists; support logical structuring of claims and accounts\nKristina: Coordinate integration of subcontractor personnel into the team, preparing workspace and facilitating their onboarding\nPrepare and present aggressive damage list identifying disputed cost items to counter subcontractor claims if their damage list is not forthcoming\nLegal/Finance team: Review implications of personal liability risks for company directors in case of delayed bankruptcy declarations and prepare appropriate legal guidance\nProject management: Confirm contract budget baselines and validate all invoices up to 125 million, limiting unnecessary review beyond this threshold",
    },
    {
        "id": "01KHP0GNQYQK1PH59GX02TVQQD",
        "title": "Feb 17, 02:36 PM",
        "date": "2026-02-17",
        "duration": "108",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting established a real-time SharePoint list for tracking project issues related to defects, documentation, and financial disputes. Notable updates included that pre-handover Mandarin tickets are 99.3% closed, while warranty tickets are at 87% closure. A total of 24,000 project documents exist, with around 50 missing and 200 needing updates, affecting the handover process. Financial discussions highlighted disputes with the client over invoices exceeding a 125 million guarantee, necessitating legal interpretation for resolution. Workflow plans include regular updates to the issue list and targeted meetings with legal and technical teams to address outstanding concerns efficiently and expedite project completion.",
        "action_items": "Christine: Share the finalized issue list and grant SharePoint access to all relevant parties by the next morning\nBrison's team: Prepare and share a critical open issues list for integration into the master issue list\nAll parties: Populate and agree upon the comprehensive issue list by the end of the week to facilitate structured parallel discussions\nLegal teams: Begin parallel discussions on disputed items such as maximum price guarantees, documentation obligations, and subcontractor additional costs\nThomas, Vladimir, and Dimitri: Meet on Monday afternoon for focused review of the issue list and decision-making on open points\nThomas, Vladimir, Christine: Prepare a detailed list of missing or inaccurate documentation for integration into the issue list\nContractor team: Prepare and submit final invoices and proof of actual costs on additional orders to support payment reconciliation\nInsurance teams and project managers: Pursue coordinated review and agreement on damage and insurance claims\nVladimir, Dimitri, Christine: Arrange a separate dedicated meeting for detailed resolution of issues related to Kupials apartment snagging defects and escrow disputes",
    },
    {
        "id": "01KHNM1RF4T1CREG6A5218DF2Q",
        "title": "Feb 17, 10:58 AM",
        "date": "2026-02-17",
        "duration": "216",
        "participants": "vallen300@gmail.com",
        "summary": "Participants discussed ongoing disputes regarding payment for subcontractor failures and the implications of budget overruns. The team is particularly concerned about an additional 772,000 in painting costs and the overall budget, initially set at about 121 million but now exceeding the maximum price of 125 million due to unforeseen costs linked to subcontractor insolvencies. Legal interpretations suggest only justified costs should be included under the open book contract, excluding those due to subcontractor mismanagement. The contractor, Martin Hagenauer, has threatened to halt work without payment, but the team plans to negotiate while ensuring they maintain legal clarity and control over any payments. Documentation handover and arguments about retention sums further complicate the situation.",
        "action_items": "Eric: Prepare a detailed summary and searchable tool on the 2.5 million documents related to the project for review within 7-10 days\nDimitri and Edita: Assist in compiling and aligning financial tables and data regarding budget, retention, and subcontractor costs for internal agreement prior to negotiation\nLegal team: Review contractual obligations and maximum price guarantee clauses to clarify liabilities related to subcontractor bankruptcies and additional costs\nThomas Bauer: Continue to provide technical verification of completed works and collaborate on adjusting invoice approvals as necessary\nTeam: Develop a comprehensive joint issue list combining client and contractor claims/issues, to be used for structured negotiation and final contract amendment\nMeeting organizers: Arrange a follow-up meeting with Hagenauer representatives to discuss payment review, documentation delivery, and project completion plans\nProject management: Monitor Hagenauer financial status closely and prepare contingencies for potential project takeover if Hagenauer fails to complete the work",
    },
    {
        "id": "01KH8FZV42D27TP8WXYQ2NQYB0",
        "title": "Feb 12, 09:37 AM",
        "date": "2026-02-12",
        "duration": "13",
        "participants": "vallen300@gmail.com",
        "summary": "The team decided to keep the villa off the public market to maintain its exclusivity and avoid potential depreciation in value. The villa will not be publicly advertised, and rental agents will discreetly inform select clients about its sale. Legal issues concerning a neighbor's attempt to build a road through the property pose challenges, including ongoing litigation that has lasted three to four years and is expected to conclude in about a year. This legal uncertainty may deter buyers, but insiders understand the situation. The viewing process will be managed by Leila, who will arrange viewings only for qualified prospects following a video review. Communication regarding the villa will occur via WhatsApp for efficiency and privacy, ensuring a secure and direct line for interested buyers.",
        "action_items": "Send contact details of Leila, the villa caretaker, to arrange visits to the villa\nShare minimum villa information including size for initial evaluation\nSend email and WhatsApp contact information to facilitate further communication\nOrganize villa viewing appointment with Leila, coordinate convenient time\nPrepare a confidential newsletter for select contacts to discreetly inform about the villa once authorized",
    },
    {
        "id": "01KGW36ZZAXH9SZB1ZGPCFJK1D",
        "title": "Feb 07, 02:03 PM",
        "date": "2026-02-07",
        "duration": "98",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting focused on creating a negotiation framework that emphasizes compiling a complete joint issue list to facilitate balanced and transparent discussions. Both parties agreed to submit their outstanding issues by Tuesday, addressing various concerns including subcontractor costs and defect management. The client insists on a fixed maximum price guarantee of approximately 117 million, while the contractor disputes this with an additional request of 4.8 million. They also highlighted the need for urgent attention to the 200 open defects and the importance of clarifying missing documentation. Furthermore, financial disputes regarding subcontractor payments, which total around 140 million with only 20 million paid so far, were discussed, emphasizing the necessity for transparency and rapid resolution to avoid project delays and work stoppages. Timelines and milestones were prioritized for project closure and final invoice agreement.",
        "action_items": "Dimitri: Compile and deliver a comprehensive full issue list by Tuesday, including all problem areas and claims\nChristina: Prepare and provide her team's issue list by Tuesday to facilitate combination for negotiation\nChristina: Ensure defect lists and snagging protocols are collected and reviewed; associate costs with each defect for clearer resolution\nBoth parties: Agree on negotiation principles: no cherry-picking issues, negotiate full list with timing and sequence prioritized by pain points\nLegal teams: Exclusively handle complex contract interpretation issues such as maximum price guarantees and invoice formula disputes\nTeams: Escalate presence and involvement of senior decision-makers to ensure authority on agreed principles\nBoth parties: Schedule regular follow-ups after initial issue list consolidation to monitor progress\nThomas Leitner: Clarify and reconcile invoice discrepancies with the other party by Monday\nEvita: Provide a definitive, detailed list of missing and provided documentation necessary for hotel operational handover\nDimitri and Christina: Coordinate on subcontractor invoice review to mitigate payment disputes",
    },
    {
        "id": "01KGQ02SJ2H12DP6QT4H9KWB1F",
        "title": "Feb 05, 02:32 PM",
        "date": "2026-02-05",
        "duration": "unknown",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting addressed key aspects of the project, notably the significant investment by major shareholder Frank Wagner, who has contributed over 10 million since 2020, emphasizing a focus on control and structured data management. The total estimated project cost is 280 million, with outstanding liabilities totaling approximately 60 million, including debts to Lindner and Fair Fund. Sales projections indicate a gross development value of 340 million, but delays in hotel construction are affecting buyer confidence and cash flow. The hotel brand, Six Senses, is under review due to financial stability concerns, which impacts the project viability. Permits for construction are valid for two more years, and local support is essential for extensions, while 12 units have been sold, albeit with some payment delays due to financing uncertainties.",
        "action_items": "Frank Wagner: Provide follow-up emails with project updates and due diligence documents to team\nFrank Wagner: Coordinate communication and maintain contact channels post-meeting\nArrange project site visit including meeting with Mr. Hoover from Lindner to assess construction conditions and management\nConduct detailed due diligence review on financials, permits, contracts, and hotel management agreement\nInitiate negotiation strategy with Lindner for settlement of claims and continuation of construction\nDevelop financial model with adjusted hotel cost estimates and sales projections to evaluate funding scenarios\nExplore updated financing options with banking partners considering new project valuation and permit status\nEric: Monitor contractual obligations regarding shareholders, Fair Fund claims, and permits\nEric: Review call options, exclusivity agreements and shareholder resolutions for corporate governance alignment",
    },
    {
        "id": "01KGMW7QJH530CT89AGFHYGTEE",
        "title": "Feb 04, 06:47 PM",
        "date": "2026-02-04",
        "duration": "45",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting highlighted significant flaws in the Data Vision system, which is outdated and costly, charging over 3,000 monthly without effective data processing or integration capabilities. Dimitri proposed a new user-friendly database platform to integrate data from top SPA and PMS providers, aiming to reduce manual reconciliation and improve operational efficiency while meeting complex regulatory requirements like GDPR and PCI compliance. The discussion also emphasised the potential of vertical AI models tailored for hospitality and real estate, which require quality structured data for effectiveness. Current industry trends reveal slow AI adoption, with only 17% penetration in the US, and the meeting outlined necessary resources, including a database architect and programmer, to develop the new data platform and enhance AI integration efforts.",
        "action_items": "Dimitri: Investigate Data Vision system capabilities and potential AI-powered replacements; report back with findings for next discussion\nDimitri: Follow up with Mandarin Oriental CEO and AI team in Hong Kong regarding current AI initiatives and licensing constraints; explore collaboration opportunities\nDimitri: Schedule follow-up meeting to discuss progress and outcomes related to new data consolidation and AI application project\nMeeting organiser: Send document share links and signing agreements via Dropbox and GoToSign; coordinate communication with Benjamin and other stakeholders",
    },
    {
        "id": "01KGMPPQ00CK1C3Z2J5FKC7K5D",
        "title": "Feb 04, 05:10 PM",
        "date": "2026-02-04",
        "duration": "41",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting addressed critical financial aspects of the project, confirming a maximum price guarantee of 125.4 million and discussing the budget structure, which includes a base amount of 120 million and a reserve of 4.8 million. Thomas clarified the necessity of tracking special requests and their impact on the approved forecast of 123 million. The team emphasized the importance of accurately verifying subcontractor work to avoid overpayments and ensure compliance with contract standards, as final invoices may differ from forecasts. Risk management was discussed, particularly regarding subcontractor payment demands and potential disruptions. Clear communication with subcontractors is planned to maintain project momentum and clarify payment positions, underscoring the commitment to financial discipline and project integrity.",
        "action_items": "Thomas: Finalize checking subcontractor invoices, focusing on claims and quantities to determine if deductions or credits apply against approved forecasts\nThomas: Provide detailed explanation of additional orders that legitimately increase maximum price guarantee, including documentation\nProject management team: Continue withholding 1 million euros retention until incomplete works and documentation are submitted\nLegal/Contract team: Prepare communication letter to contractor Hagenauer by Friday to address payment dispute and clarify consequences of potential work stoppage\nFinance team: Monitor impact of potential contractor departure on project cash flow, and assess costs of retaining subcontractors\nDecision makers: Review final detailed subcontractor claims and forecasts within next 2-3 weeks to decide whether project costs exceed maximum price guarantee",
    },
    {
        "id": "01KGMPHJFVTMSTQ2T16P8P73AN",
        "title": "Feb 04, 05:07 PM",
        "date": "2026-02-04",
        "duration": "3",
        "participants": "vallen300@gmail.com",
        "summary": "The meeting addressed contractual cost management related to painting works, confirming that painting costs are fixed per square metre under the subcontract with Hagenauer. This pricing model ensures that the subcontractor invoices monthly based on the actual square metres painted, eliminating any unexpected cost increases. The approach provides clear tracking of work progress through monthly reports, aligning payments with delivered work, thus maintaining budget stability and cost predictability. It was also discussed that no extra budget adjustments are necessary due to this unit-rate contract, which automatically adjusts costs with the work done, reducing administrative efforts and invoice disputes.",
        "action_items": "Review and clarify the reason why no extra contract or additional charges are applied to painting work despite potential budget increases mentioned\nConfirm the payment and invoicing process aligning the subcontractor square metre pricing with the overall project budget",
    },
]

def build():
    texts = []
    for t in transcripts:
        parts = [
            f"Meeting: {t['title']}",
            f"Date: {t['date']}",
            f"Participants: {t['participants']}",
            f"Duration: {t['duration']}min",
            "",
            f"Summary: {t['summary']}",
            "",
            f"Action Items:\n{t['action_items']}",
        ]
        text_block = "\n".join(parts)
        texts.append({
            "text": text_block,
            "metadata": {
                "meeting_title": t["title"],
                "date": t["date"],
                "participants": t["participants"],
                "organizer": "vallen300@gmail.com",
                "duration": t["duration"] + "min",
                "fireflies_id": t["id"],
                "source": "fireflies",
            },
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"texts": texts}, f, indent=2, ensure_ascii=False)

    total_chars = sum(len(item["text"]) for item in texts)
    print(f"Wrote {len(texts)} transcripts to {OUTPUT}")
    print(f"Total text: {total_chars:,} chars (~{total_chars // 4:,} tokens)")

if __name__ == "__main__":
    build()
