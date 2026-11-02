# TargetIdeator data redistribution ledger

- Review date: 2026-11-02
- Reviewer and release owner: Zimiao1025
- Release: `v0.32.0`

## Scope and release rule

This ledger governs external-source data used during TargetIdeator development.
The root `LICENSE` applies only to TargetIdeator's original code and original
project material. It does not relicense upstream data, article text, database
records, or third-party identifiers.

The public Git repository, wheel, and source distribution contain no raw or
derived records from the five source families below. They contain only project
code, release metadata, documentation, and the explicitly synthetic
`crohns_seed.json` demonstration fixture. External data must be acquired by the
operator and mounted with `TARGETIDEATOR_DATA_ROOT`; no public data bundle is
authorized by this release.

| Source family | Versions used | Official source and terms | Local material covered by this decision | Upstream redistribution position | `v0.32.0` release decision | Required notice for any future separate data release |
|---|---|---|---|---|---|---|
| Open Targets Platform | 25.03 (2025-03-19), 25.09 (2025-09-17), 26.09 (2026-09-24) | [downloads](https://platform.opentargets.org/downloads); [licence](https://platform-docs.opentargets.org/licence) | Open Targets association, evidence and drug-dictionary captures; all downstream snapshots and claim-graph artifacts derived from them | Platform data is marked CC0 1.0. Integrated source records may still carry source-specific obligations; ChEMBL and Europe PMC are therefore reviewed separately below. | Excluded from Git, wheel and sdist. Operator-acquired local use only in this release. | Cite Open Targets and the exact release; retain source-level provenance and apply the original source's terms where applicable. |
| ChEMBL | Open Targets 25.03/25.09 ChEMBL evidence; ChEMBL 37 current API metadata | [ChEMBL](https://www.ebi.ac.uk/chembl/); [official licensing FAQ](https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/general-questions) | ChEMBL evidence, molecule dictionaries, drug-target mappings, assertion history and dependent outcome/selection artifacts | CC BY-SA 3.0 permits redistribution and adaptation with attribution and ShareAlike; some commercial compound-property calculations have additional restrictions. | Excluded from Git, wheel and sdist. This Apache-2.0 code release does not redistribute or relicense ChEMBL content. | Cite ChEMBL and the exact release; include CC BY-SA 3.0 notice, mark adaptations, preserve ShareAlike, and exclude commercial calculations unless separately cleared. |
| ClinicalTrials.gov / AACT | AACT 20250301 and 20250901 historical snapshots; current ClinicalTrials.gov API validation captured 2026-11-01/02 | [AACT](https://aact.ctti-clinicaltrials.org/); [ClinicalTrials.gov](https://clinicaltrials.gov/); [NLM data terms](https://www.nlm.nih.gov/databases/download.html) | Trial rows, interventions, outcome and stop-reason records, temporal-outcome datasets and all trial-derived mappings/analyses | AACT describes the database as public/open. NLM requires acknowledgement, no implication of endorsement, and either current data or a conspicuous stale-version notice. Registry records are submitted by third parties, so no blanket relicense is asserted here. | Excluded from Git, wheel and sdist. Public redistribution of the local AACT/ClinicalTrials.gov bundle is not authorized by this release. | Acknowledge AACT, CTTI, ClinicalTrials.gov and NLM; state snapshot dates, non-current status, no endorsement, and applicable accuracy/warranty limitations. |
| Europe PMC | REST API 6.9; 50-document capture with cutoff 2025-09-17 | [Europe PMC](https://europepmc.org/); [copyright and reuse policy](https://europepmc.org/Copyright) | Raw literature response, titles/abstract paragraphs, `literature_benchmark.json`, verbatim spans, review batches, relations and downstream literature-derived artifacts | Rights are publication-specific. Free access or API availability does not itself authorize redistribution; each article's licence must be checked. | All Europe PMC records, paragraph text, verbatim spans and literature-derived fixtures are excluded from Git, wheel and sdist. No blanket redistribution is authorized. | Complete a document-level licence audit; retain article citation, licence URI, copyright holder and required attribution for every redistributed passage. |
| DrugCentral | 2027 release, published 2026-09-25 | [download](https://www.drugcentral.org/download); [licence page](https://www.drugcentral.org/privacy); [CC BY-SA 4.0 legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode) | Drug-target interaction capture, independent assertion pairs, cross-source corroborations and dependent support audits | DrugCentral links to CC BY-SA 4.0, which permits sharing/adaptation with attribution and ShareAlike. Source records may incorporate additional external-source notices. | Excluded from Git, wheel and sdist. This Apache-2.0 code release does not redistribute or relicense DrugCentral content. | Cite DrugCentral and the exact release; include CC BY-SA 4.0 notice, source URI and modification indication; preserve ShareAlike for adapted database material. |

## Package audit mapping

The following patterns are prohibited from the public release artifacts:

- `src/targetideator/fixtures/**`, except `__init__.py` and the synthetic
  `crohns_seed.json`;
- `outputs/**`, `dist/**`, caches and local environments;
- development proposals, expert-review material, test caches, replay staging
  roots and historical build products.

This is a conservative release decision, not legal advice and not a finding
that every excluded file is legally non-redistributable. A future data release
requires a new, versioned ledger and its own licence/notice bundle.
