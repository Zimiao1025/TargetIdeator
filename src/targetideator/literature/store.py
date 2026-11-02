"""P2.2 literature normalization, provisional annotation, extraction, and evaluation."""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.claims.models import ClaimPolarity, ClaimRelationType
from targetideator.evidence.models import CanonicalEntity
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.literature.ingestion import (
    PARAGRAPH_NORMALIZATION_VERSION,
    TARGET_ALIASES,
    normalize_abstract,
    sentence_spans,
)
from targetideator.literature.models import (
    ClaimDirection,
    DoubleReviewTask,
    ExtractionMetrics,
    LiteratureBenchmark,
    LiteratureClaim,
    LiteratureClaimRelation,
    LiteratureClaimTheme,
    LiteratureDocumentVersion,
    LiteratureManifest,
    LiteratureParagraph,
    LiteratureQueryRoute,
    SpanContext,
)

LITERATURE_BENCHMARK_ID = "ti:literature-benchmark:crohns-four-targets-provisional-v1"
EXTRACTOR_VERSION = "span-rule-baseline-v1"
PROVISIONAL_ANNOTATOR = "targetideator-provisional-curation-v1"
TARGETS = {
    "IL23A": CanonicalEntity(
        entity_type="gene", namespace="Ensembl", identifier="ENSG00000110944", label="IL23A"
    ),
    "JAK1": CanonicalEntity(
        entity_type="gene", namespace="Ensembl", identifier="ENSG00000162434", label="JAK1"
    ),
    "TNFSF15": CanonicalEntity(
        entity_type="gene", namespace="Ensembl", identifier="ENSG00000181634", label="TNFSF15"
    ),
    "NOD2": CanonicalEntity(
        entity_type="gene", namespace="Ensembl", identifier="ENSG00000167207", label="NOD2"
    ),
}
DISEASE = CanonicalEntity(
    entity_type="disease",
    namespace="MONDO",
    identifier="MONDO:0005011",
    label="Crohn disease",
)

THEME_PREDICATES = {
    LiteratureClaimTheme.GENETIC_ASSOCIATION: "has reported genetic association with",
    LiteratureClaimTheme.DISEASE_ASSOCIATION: "has reported association with",
    LiteratureClaimTheme.MECHANISM: "has a reported mechanistic role in",
    LiteratureClaimTheme.THERAPEUTIC_EFFECT: "has reported therapeutic-modulation evidence in",
    LiteratureClaimTheme.BIOMARKER: "has reported biomarker evidence in",
    LiteratureClaimTheme.SAFETY_LIMITATION: "has a reported limitation or safety constraint in",
}
RESULT_CUES = (
    "associated",
    "association",
    "increased",
    "decreased",
    "promote",
    "drive",
    "protect",
    "required",
    "essential",
    "inhibit",
    "block",
    "attenuate",
    "response",
    "risk",
    "susceptibility",
    "showed",
    "demonstrated",
    "confirm",
    "confirmed",
    "identified",
    "found",
)
NON_CLAIM_CUES = (
    "abbreviations",
    "the aim of",
    "we aimed",
    "the purpose of",
    "we investigated",
    "we hypothesized",
    "this review aims",
    "methods we ",
    "background and aims",
)
RELATION_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "were",
    "was", "are", "has", "have", "had", "into", "through", "between", "during", "after",
    "before", "our", "their", "its", "but", "not", "also", "may", "might", "can", "could",
    "show", "showed", "demonstrate", "demonstrated", "identify", "identified", "found", "result",
    "results", "study", "studies", "disease", "crohn", "crohns", "inflammatory", "bowel", "ibd",
    "group", "groups",
}


def default_literature_raw_path() -> Path:
    return fixture_path("europepmc_literature_raw.json")


def default_literature_snapshot_path() -> Path:
    return fixture_path("literature_benchmark.json")


def default_literature_manifest_path() -> Path:
    return fixture_path("literature_manifest.json")


def _source_date(record: dict[str, Any], key: str, fallback: date | None = None) -> date:
    value = record.get(key)
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    if fallback is not None:
        return fallback
    raise ValueError(f"Europe PMC record {record.get('id')} has no usable {key}")


def _publication_date(record: dict[str, Any]) -> date:
    for key in ("firstPublicationDate", "electronicPublicationDate", "dateOfCreation"):
        try:
            return _source_date(record, key)
        except ValueError:
            continue
    raise ValueError(f"Europe PMC record {record.get('id')} has no publication date")


def _publication_types(record: dict[str, Any]) -> list[str]:
    value = (record.get("pubTypeList") or {}).get("pubType") or []
    return sorted({str(item) for item in value})


def _document_and_paragraph(
    item: dict[str, Any],
    *,
    captured_at: str,
    api_version: str,
    route_by_target: dict[str, dict[str, Any]],
) -> tuple[LiteratureDocumentVersion, LiteratureParagraph]:
    record = item["record"]
    target_label = item["assigned_target"]
    source = str(record.get("source") or "MED")
    source_identifier = str(record["id"])
    abstract_raw = str(record["abstractText"])
    abstract = normalize_abstract(abstract_raw)
    publication_date = _publication_date(record)
    first_index = _source_date(record, "firstIndexDate", publication_date)
    revision = _source_date(record, "dateOfRevision", first_index)
    available_on = max(first_index, revision)
    version_payload = {
        "source": source,
        "id": source_identifier,
        "title": record["title"],
        "abstract": abstract,
        "revision": revision.isoformat(),
    }
    version_sha = hashlib.sha256(canonical_json_bytes(version_payload)).hexdigest()
    document_id = stable_id(
        "literature-document", f"{source}-{source_identifier}-{version_sha[:16]}"
    )
    paragraph_sha = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
    paragraph_id = stable_id("literature-paragraph", f"{document_id}-abstract-0")
    route = route_by_target[target_label]
    document = LiteratureDocumentVersion(
        id=document_id,
        source_id=f"{source}:{source_identifier}",
        pmid=record.get("pmid"),
        pmcid=record.get("pmcid"),
        doi=record.get("doi"),
        title=record["title"],
        abstract_raw_sha256=hashlib.sha256(abstract_raw.encode("utf-8")).hexdigest(),
        publication_date=publication_date,
        first_index_date=first_index,
        source_revision_date=revision,
        version_available_on=available_on,
        captured_at=captured_at,
        source_api_version=api_version,
        source_api_url=route["api_url"],
        version_sha256=version_sha,
        assigned_target=TARGETS[target_label],
        selection_route=route["query"],
        publication_types=_publication_types(record),
        is_open_access=str(record.get("isOpenAccess") or "N").upper() == "Y",
    )
    paragraph = LiteratureParagraph(
        id=paragraph_id,
        document_version_id=document_id,
        paragraph_index=0,
        text=abstract,
        text_sha256=paragraph_sha,
        available_on=available_on,
        normalization_version=PARAGRAPH_NORMALIZATION_VERSION,
    )
    return document, paragraph


def _theme(text: str, *, curator: bool) -> LiteratureClaimTheme:
    lower = text.casefold()
    if any(token in lower for token in ("variant", "locus", "loci", "allele", "genetic", "genotype", "polymorphism", "gwas")):
        return LiteratureClaimTheme.GENETIC_ASSOCIATION
    if any(token in lower for token in ("adverse", "toxicity", "safety", "failed", "limitation", "resistance")):
        return LiteratureClaimTheme.SAFETY_LIMITATION
    if any(token in lower for token in ("biomarker", "predict", "stratif", "response marker")):
        return LiteratureClaimTheme.BIOMARKER
    therapeutic = ("inhibit", "block", "antibody", "treatment", "therapy", "therapeutic", "drug")
    if any(token in lower for token in therapeutic):
        return LiteratureClaimTheme.THERAPEUTIC_EFFECT
    mechanism = ("signal", "pathway", "cytokine", "expression", "cell", "inflammation", "microbiota")
    if any(token in lower for token in mechanism):
        return LiteratureClaimTheme.MECHANISM
    return LiteratureClaimTheme.DISEASE_ASSOCIATION


def _polarity(text: str, *, curator: bool) -> ClaimPolarity:
    lower = text.casefold()
    negative = re.search(
        r"\b(?:no|not)\s+(?:statistically\s+|significantly\s+|significant\s+)?"
        r"(?:association|associated|effect|response|difference|protection|reduction|improvement)\b"
        r"|\b(?:failed|fails|did not|lack|lacked)\b.{0,35}"
        r"(?:associate|effect|respond|protect|reduce|improve|significant)",
        lower,
    )
    if negative:
        return ClaimPolarity.REFUTES
    if curator and any(
        token in lower
        for token in ("however", "although", "may ", "might ", "subset", "whereas", "context-dependent", "heterogeneity")
    ):
        return ClaimPolarity.QUALIFIES
    if any(token in lower for token in RESULT_CUES):
        return ClaimPolarity.SUPPORTS
    return ClaimPolarity.NEUTRAL


def _direction(text: str, *, curator: bool) -> ClaimDirection:
    lower = text.casefold()
    if curator and any(token in lower for token in ("context-dependent", "whereas", "however", "dual role")):
        return ClaimDirection.CONTEXT_DEPENDENT
    if any(token in lower for token in ("reduce", "decrease", "inhibit", "block", "attenuat", "suppress", "protect")):
        return ClaimDirection.DECREASES
    if any(token in lower for token in ("increase", "elevated", "promote", "drive", "enhanc", "activate")):
        return ClaimDirection.INCREASES
    return ClaimDirection.UNKNOWN


def _span_context(text: str) -> SpanContext:
    lower = text.casefold()
    if "mouse" in lower or "mice" in lower or "murine" in lower:
        species, model = "mouse", "in vivo mouse study"
    elif "rat" in lower:
        species, model = "rat", "in vivo rat study"
    elif any(token in lower for token in ("patient", "human", "subjects", "cohort")):
        species, model = "human", "human study"
    elif any(token in lower for token in ("cell line", "in vitro", "cultured")):
        species, model = "unknown", "in vitro study"
    else:
        species, model = "unknown", "not resolved from selected abstract sentence"
    population = "Crohn/IBD population" if any(token in lower for token in ("crohn", "ibd", "inflammatory bowel")) else "not specified in selected span"
    anatomy = "intestine/colon" if any(token in lower for token in ("intestinal", "intestine", "colon", "ileum", "mucosa")) else "not specified in selected span"
    cell = "immune or intestinal cell context" if "cell" in lower else "not specified in selected span"
    return SpanContext(
        species=species,
        model_system=model,
        population=population,
        anatomical_region=anatomy,
        cell_type=cell,
    )


def _claim_id(document: LiteratureDocumentVersion, target: CanonicalEntity, start: int, end: int) -> str:
    source_key = (document.pmid or document.pmcid or document.source_id).replace(":", "-")
    return stable_id("literature-claim", f"{target.label}-{source_key}-{start}-{end}")


def _make_claim(
    document: LiteratureDocumentVersion,
    paragraph: LiteratureParagraph,
    span: tuple[int, int, str],
    *,
    origin: str,
    curator: bool,
) -> LiteratureClaim:
    start, end, text = span
    theme = _theme(text, curator=curator)
    return LiteratureClaim(
        id=_claim_id(document, document.assigned_target, start, end),
        document_version_id=document.id,
        paragraph_id=paragraph.id,
        target=document.assigned_target,
        disease=DISEASE,
        theme=theme,
        predicate=THEME_PREDICATES[theme],
        object_text=text,
        polarity=_polarity(text, curator=curator),
        direction=_direction(text, curator=curator),
        context=_span_context(text),
        verbatim_span=text,
        span_start=start,
        span_end=end,
        paragraph_sha256=paragraph.text_sha256,
        available_on=paragraph.available_on,
        annotation_origin=origin,
        annotator_or_extractor_id=(PROVISIONAL_ANNOTATOR if curator else EXTRACTOR_VERSION),
        review_status=("single_annotator_provisional" if curator else "automated_unreviewed"),
        eligible_for_p3=False,
        uncertainty=(
            "Provisional single-annotator label; requires independent review and adjudication."
            if curator
            else "Deterministic baseline extraction; not expert reviewed."
        ),
    )


def _gold_sentence_score(text: str, target_label: str) -> tuple[int, int]:
    lower = text.casefold()
    alias_score = sum(alias in lower for alias in TARGET_ALIASES[target_label])
    disease_score = sum(token in lower for token in ("crohn", "inflammatory bowel", "ibd", "colitis"))
    result_score = sum(token in lower for token in RESULT_CUES)
    non_claim_penalty = 60 if any(token in lower for token in NON_CLAIM_CUES) else 0
    return (
        alias_score * 20 + disease_score * 6 + min(result_score, 4) * 3 - non_claim_penalty,
        -len(text),
    )


def _provisional_gold_claims(
    documents: list[LiteratureDocumentVersion],
    paragraphs: list[LiteratureParagraph],
) -> list[LiteratureClaim]:
    paragraph_by_document = {item.document_version_id: item for item in paragraphs}
    claims: list[LiteratureClaim] = []
    for document in documents:
        paragraph = paragraph_by_document[document.id]
        spans = sentence_spans(paragraph.text)
        selected = sorted(
            spans,
            key=lambda item: _gold_sentence_score(item[2], document.assigned_target.label),
            reverse=True,
        )[:3]
        selected.sort(key=lambda item: item[0])
        claims.extend(
            _make_claim(document, paragraph, span, origin="provisional_gold", curator=True)
            for span in selected
        )
    if len(claims) != len(documents) * 3:
        raise ValueError("provisional gold construction requires exactly three spans per document")
    review_ids = {claims[index].id for index in range(0, len(claims), 5)}
    return [
        item.model_copy(update={"review_status": "pending_double_review"})
        if item.id in review_ids
        else item
        for item in claims
    ]


def _extracted_claims(
    documents: list[LiteratureDocumentVersion],
    paragraphs: list[LiteratureParagraph],
) -> list[LiteratureClaim]:
    paragraph_by_document = {item.document_version_id: item for item in paragraphs}
    claims: list[LiteratureClaim] = []
    for document in documents:
        paragraph = paragraph_by_document[document.id]
        aliases = TARGET_ALIASES[document.assigned_target.label]
        candidates = [
            span
            for span in sentence_spans(paragraph.text)
            if any(alias in span[2].casefold() for alias in aliases)
            and any(cue in span[2].casefold() for cue in RESULT_CUES)
        ][:4]
        claims.extend(
            _make_claim(
                document,
                paragraph,
                span,
                origin="deterministic_extractor",
                curator=False,
            )
            for span in candidates
        )
    return claims


def _relation_id(source: str, target: str, relation_type: ClaimRelationType, origin: str) -> str:
    return stable_id(
        "literature-relation", f"{origin}-{source}-{relation_type.value}-{target}"
    )


def _relation_theme(theme: LiteratureClaimTheme) -> str:
    if theme in {
        LiteratureClaimTheme.GENETIC_ASSOCIATION,
        LiteratureClaimTheme.DISEASE_ASSOCIATION,
    }:
        return "disease_or_genetic_association"
    return theme.value


def _relation_terms(claim: LiteratureClaim) -> set[str]:
    text = claim.verbatim_span.casefold()
    for alias in TARGET_ALIASES[claim.target.label]:
        text = text.replace(alias.casefold(), claim.target.label.casefold())
    text = re.sub(r"\b(?:crohn(?:'s)?(?: disease)?|inflammatory bowel disease|ibd)\b", " disease ", text)
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", text)
        if token not in RELATION_STOPWORDS
    }


def _semantic_overlap(source: LiteratureClaim, target: LiteratureClaim) -> tuple[float, list[str]]:
    source_terms = _relation_terms(source)
    target_terms = _relation_terms(target)
    shared = sorted(source_terms & target_terms)
    denominator = min(len(source_terms), len(target_terms))
    return (len(shared) / denominator if denominator else 0.0, shared)


def _replication_cue(claim: LiteratureClaim) -> str | None:
    text = claim.verbatim_span
    lower = text.casefold()
    cues = list(
        re.finditer(
            r"(?<!un)\b(?:confirm(?:ed|s|ing)?|replicat(?:ed|es|ion|ing)|validat(?:ed|es|ion|ing))\b",
            lower,
        )
    )
    alias_positions = [
        lower.find(alias.casefold())
        for alias in TARGET_ALIASES[claim.target.label]
        if alias.casefold() in lower
    ]
    if not cues or not alias_positions:
        return None
    cue = min(cues, key=lambda item: min(abs(item.start() - position) for position in alias_positions))
    if min(abs(cue.start() - position) for position in alias_positions) > 120:
        return None
    return text[cue.start() : cue.end()]


def _directions_compatible(source: LiteratureClaim, target: LiteratureClaim) -> bool:
    return (
        source.direction == target.direction
        or ClaimDirection.UNKNOWN in {source.direction, target.direction}
        or ClaimDirection.CONTEXT_DEPENDENT in {source.direction, target.direction}
    )


def _relations(
    claims: list[LiteratureClaim], *, origin: str
) -> list[LiteratureClaimRelation]:
    groups: dict[tuple[str, str], list[LiteratureClaim]] = {}
    for claim in claims:
        groups.setdefault(
            (claim.target.identifier, _relation_theme(claim.theme)), []
        ).append(claim)
    relations: list[LiteratureClaimRelation] = []
    for (target_identifier, proposition_family), grouped in groups.items():
        grouped.sort(key=lambda item: (item.available_on, item.document_version_id, item.span_start))
        for source_index, claim in enumerate(grouped):
            cue = _replication_cue(claim)
            candidates: list[tuple[float, int, LiteratureClaim, list[str]]] = []
            candidate_pool = grouped if cue or claim.polarity == ClaimPolarity.REFUTES else grouped[:source_index]
            for target in candidate_pool:
                if claim.id == target.id:
                    continue
                if claim.document_version_id == target.document_version_id:
                    continue
                if not _directions_compatible(claim, target):
                    continue
                overlap, shared = _semantic_overlap(claim, target)
                informative = [
                    term
                    for term in shared
                    if term not in {claim.target.label.casefold(), "disease"}
                ]
                is_replication_pair = (
                    cue is not None
                    and claim.polarity == ClaimPolarity.SUPPORTS
                    and target.polarity == ClaimPolarity.SUPPORTS
                    and claim.target.label.casefold() in shared
                )
                required_informative_terms = 2 if claim.polarity == ClaimPolarity.REFUTES else 1
                is_semantic_pair = (
                    len(shared) >= 2
                    and len(informative) >= required_informative_terms
                    and overlap >= 0.12
                )
                if is_replication_pair or is_semantic_pair:
                    candidates.append((overlap, len(shared), target, shared))
            if not candidates:
                continue
            overlap, _, anchor, shared = max(
                candidates,
                key=lambda item: (item[0], item[1], item[2].available_on, item[2].id),
            )
            if claim.polarity == ClaimPolarity.REFUTES and anchor.polarity == ClaimPolarity.SUPPORTS:
                relation_type = ClaimRelationType.REFUTES
                decision_rule = "opposite_polarity_v1"
                rationale = "Opposite-polarity, direction-compatible claims share a target and proposition family across documents."
            elif (
                claim.polarity == ClaimPolarity.SUPPORTS
                and anchor.polarity == ClaimPolarity.SUPPORTS
                and cue is not None
            ):
                relation_type = ClaimRelationType.REPLICATES
                decision_rule = "explicit_cross_document_replication_v1"
                rationale = "A target-local replication/confirmation cue links direction-compatible propositions across documents."
            elif claim.polarity == ClaimPolarity.SUPPORTS and anchor.polarity == ClaimPolarity.SUPPORTS:
                relation_type = ClaimRelationType.SUPPORTS
                decision_rule = "concordant_proposition_v1"
                rationale = "Concordant, direction-compatible claims share semantic terms, target, and proposition family across documents."
            else:
                continue
            relations.append(
                LiteratureClaimRelation(
                    id=_relation_id(claim.id, anchor.id, relation_type, origin),
                    source_claim_id=claim.id,
                    target_claim_id=anchor.id,
                    relation_type=relation_type,
                    available_on=max(claim.available_on, anchor.available_on),
                    proposition_key=f"{target_identifier}|{proposition_family}",
                    semantic_overlap=overlap,
                    shared_terms=shared,
                    relation_cue=cue if relation_type == ClaimRelationType.REPLICATES else None,
                    decision_rule=decision_rule,
                    rationale=rationale,
                    origin=origin,
                    review_status=(
                        "single_annotator_provisional"
                        if origin == "provisional_gold"
                        else "automated_unreviewed"
                    ),
                    eligible_for_p3=False,
                )
            )
    return sorted(relations, key=lambda item: (item.available_on, item.id))


def _metrics(
    gold: list[LiteratureClaim],
    extracted: list[LiteratureClaim],
    gold_relations: list[LiteratureClaimRelation],
    extracted_relations: list[LiteratureClaimRelation],
) -> ExtractionMetrics:
    def key(item: LiteratureClaim) -> tuple[str, int, int]:
        return (item.document_version_id, item.span_start, item.span_end)

    gold_by_key = {key(item): item for item in gold}
    extracted_by_key = {key(item): item for item in extracted}
    matched_keys = gold_by_key.keys() & extracted_by_key.keys()
    true_positive = len(matched_keys)
    precision = true_positive / len(extracted) if extracted else 0.0
    recall = true_positive / len(gold) if gold else 0.0
    span_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    def accuracy(field: str) -> float:
        if not matched_keys:
            return 0.0
        return sum(
            getattr(gold_by_key[item], field) == getattr(extracted_by_key[item], field)
            for item in matched_keys
        ) / len(matched_keys)

    def relation_key(item: LiteratureClaimRelation) -> tuple[str, str, str]:
        return (item.source_claim_id, item.target_claim_id, item.relation_type.value)

    gold_relation_keys = {relation_key(item) for item in gold_relations}
    extracted_relation_keys = {relation_key(item) for item in extracted_relations}
    relation_tp = len(gold_relation_keys & extracted_relation_keys)
    relation_precision = relation_tp / len(extracted_relation_keys) if extracted_relation_keys else 0.0
    relation_recall = relation_tp / len(gold_relation_keys) if gold_relation_keys else 0.0
    relation_f1 = (
        2 * relation_precision * relation_recall / (relation_precision + relation_recall)
        if relation_precision + relation_recall
        else 0.0
    )
    return ExtractionMetrics(
        gold_claim_count=len(gold),
        extracted_claim_count=len(extracted),
        exact_span_true_positive=true_positive,
        exact_span_precision=precision,
        exact_span_recall=recall,
        exact_span_f1=span_f1,
        target_accuracy_on_matched=accuracy("target"),
        theme_accuracy_on_matched=accuracy("theme"),
        polarity_accuracy_on_matched=accuracy("polarity"),
        direction_accuracy_on_matched=accuracy("direction"),
        gold_relation_count=len(gold_relations),
        extracted_relation_count=len(extracted_relations),
        relation_precision=relation_precision,
        relation_recall=relation_recall,
        relation_f1=relation_f1,
        p3_gate_passed=False,
        p3_gate_reason=(
            "Blocked: annotations are provisional single-annotator labels; 20% double review and "
            "adjudication are pending, regardless of baseline metric values."
        ),
    )


def _normalize_capture(payload: dict[str, Any]) -> LiteratureBenchmark:
    routes = [LiteratureQueryRoute.model_validate(item) for item in payload["query_routes"]]
    route_by_target = {item.target_label: item.model_dump(mode="json") for item in routes}
    documents: list[LiteratureDocumentVersion] = []
    paragraphs: list[LiteratureParagraph] = []
    for item in payload["documents"]:
        document, paragraph = _document_and_paragraph(
            item,
            captured_at=payload["captured_at"],
            api_version=payload["source_api_version"],
            route_by_target=route_by_target,
        )
        documents.append(document)
        paragraphs.append(paragraph)
    documents.sort(key=lambda item: (item.assigned_target.label, item.source_id))
    paragraphs.sort(key=lambda item: item.document_version_id)
    gold = _provisional_gold_claims(documents, paragraphs)
    extracted = _extracted_claims(documents, paragraphs)
    gold_relations = _relations(gold, origin="provisional_gold")
    extracted_relations = _relations(extracted, origin="deterministic_extractor")
    tasks = [
        DoubleReviewTask(
            id=stable_id("review-task", f"double-review-{item.id}"),
            claim_id=item.id,
        )
        for item in gold
        if item.review_status == "pending_double_review"
    ]
    return LiteratureBenchmark(
        id=LITERATURE_BENCHMARK_ID,
        captured_at=payload["captured_at"],
        source_api_version=payload["source_api_version"],
        capture_cutoff=payload["capture_cutoff"],
        query_routes=routes,
        documents=documents,
        paragraphs=paragraphs,
        provisional_gold_claims=gold,
        provisional_gold_relations=gold_relations,
        double_review_tasks=tasks,
        extracted_claims=extracted,
        extracted_relations=extracted_relations,
        extraction_metrics=_metrics(gold, extracted, gold_relations, extracted_relations),
    )


def build_literature_benchmark(
    raw_path: Path,
    snapshot_path: Path,
    manifest_path: Path,
) -> tuple[LiteratureBenchmark, LiteratureManifest]:
    payload = _load_json(raw_path)
    snapshot = _normalize_capture(payload)
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = LiteratureManifest(
        snapshot_id=snapshot.id,
        raw_path=raw_path.name,
        raw_sha256=file_sha256(raw_path),
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        document_count=len(snapshot.documents),
        paragraph_count=len(snapshot.paragraphs),
        provisional_gold_claim_count=len(snapshot.provisional_gold_claims),
        extracted_claim_count=len(snapshot.extracted_claims),
        extractor_version=EXTRACTOR_VERSION,
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    return snapshot, manifest


class LiteratureStore:
    def __init__(
        self,
        snapshot: LiteratureBenchmark,
        raw_payload: dict[str, Any],
        manifest: LiteratureManifest | None = None,
        raw_path: Path | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.raw_payload = raw_payload
        self.manifest = manifest
        self.raw_path = raw_path
        self.snapshot_path = snapshot_path
        self._documents = {item.id: item for item in snapshot.documents}
        self._paragraphs = {item.id: item for item in snapshot.paragraphs}
        self._gold = {item.id: item for item in snapshot.provisional_gold_claims}

    @classmethod
    def load(
        cls,
        snapshot_path: Path,
        raw_path: Path,
        manifest_path: Path | None = None,
    ) -> "LiteratureStore":
        try:
            snapshot = LiteratureBenchmark.model_validate(_load_json(snapshot_path))
            raw = _load_json(raw_path)
            manifest = (
                LiteratureManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid literature artifact: {exc}") from exc
        return cls(snapshot, raw, manifest, raw_path, snapshot_path)

    def query(self, target_id: str, as_of_date: date) -> dict[str, Any]:
        target = next(
            (item for item in TARGETS.values() if target_id in {item.identifier, item.label}),
            None,
        )
        if target is None:
            return {
                "target_id": target_id,
                "as_of_date": as_of_date.isoformat(),
                "documents": [],
                "paragraphs": [],
                "provisional_gold_claims": [],
                "extracted_claims": [],
                "relations": [],
                "warning": "Unknown target for the frozen four-target literature corpus.",
            }
        documents = [
            item
            for item in self.snapshot.documents
            if item.assigned_target.identifier == target.identifier
            and item.version_available_on <= as_of_date
        ]
        document_ids = {item.id for item in documents}
        paragraphs = [
            item for item in self.snapshot.paragraphs if item.document_version_id in document_ids
        ]
        gold = [
            item
            for item in self.snapshot.provisional_gold_claims
            if item.document_version_id in document_ids and item.available_on <= as_of_date
        ]
        extracted = [
            item
            for item in self.snapshot.extracted_claims
            if item.document_version_id in document_ids and item.available_on <= as_of_date
        ]
        claim_ids = {item.id for item in gold}
        relations = [
            item
            for item in self.snapshot.provisional_gold_relations
            if item.source_claim_id in claim_ids
            and item.target_claim_id in claim_ids
            and item.available_on <= as_of_date
        ]
        return {
            "target_id": target.identifier,
            "target_label": target.label,
            "as_of_date": as_of_date.isoformat(),
            "documents": [item.model_dump(mode="json") for item in documents],
            "paragraphs": [item.model_dump(mode="json") for item in paragraphs],
            "provisional_gold_claims": [item.model_dump(mode="json") for item in gold],
            "extracted_claims": [item.model_dump(mode="json") for item in extracted],
            "relations": [item.model_dump(mode="json") for item in relations],
            "warning": (
                "Provisional single-annotator benchmark only. Claims and relations are blocked from P3 "
                "until double review and adjudication."
            ),
        }

    def claim_lineage(self, claim_id: str) -> dict[str, Any] | None:
        claim = self._gold.get(claim_id)
        layer = "provisional_gold"
        if claim is None:
            claim = next((item for item in self.snapshot.extracted_claims if item.id == claim_id), None)
            layer = "deterministic_extractor"
        if claim is None:
            return None
        paragraph = self._paragraphs[claim.paragraph_id]
        document = self._documents[claim.document_version_id]
        raw = next(
            item["record"]
            for item in self.raw_payload["documents"]
            if f"{item['record'].get('source') or 'MED'}:{item['record']['id']}"
            == document.source_id
        )
        return {
            "layer": layer,
            "claim": claim.model_dump(mode="json"),
            "paragraph": paragraph.model_dump(mode="json"),
            "document": document.model_dump(mode="json"),
            "raw_source_record_sha256": hashlib.sha256(canonical_json_bytes(raw)).hexdigest(),
        }

    def quality_report(self) -> dict[str, Any]:
        exact_spans = sum(
            self._paragraphs[item.paragraph_id].text[item.span_start : item.span_end]
            == item.verbatim_span
            for item in [*self.snapshot.provisional_gold_claims, *self.snapshot.extracted_claims]
        )
        total_spans = len(self.snapshot.provisional_gold_claims) + len(self.snapshot.extracted_claims)
        raw_checksum = bool(
            self.manifest and self.raw_path and file_sha256(self.raw_path) == self.manifest.raw_sha256
        )
        normalized_checksum = bool(
            self.manifest
            and self.snapshot_path
            and file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
        )
        deterministic = False
        if self.raw_path:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rebuilt, _ = build_literature_benchmark(
                    self.raw_path, root / "snapshot.json", root / "manifest.json"
                )
                deterministic = canonical_json_bytes(rebuilt.model_dump(mode="json")) == canonical_json_bytes(
                    self.snapshot.model_dump(mode="json")
                )
        relation_counts = Counter(
            item.relation_type.value for item in self.snapshot.provisional_gold_relations
        )
        current_versions_after_cutoff = sum(
            item.version_available_on > self.snapshot.capture_cutoff
            for item in self.snapshot.documents
        )
        return {
            "snapshot_id": self.snapshot.id,
            "document_version_count": len(self.snapshot.documents),
            "paragraph_count": len(self.snapshot.paragraphs),
            "target_document_counts": dict(
                sorted(Counter(item.assigned_target.label for item in self.snapshot.documents).items())
            ),
            "provisional_gold_claim_count": len(self.snapshot.provisional_gold_claims),
            "negative_claim_count": sum(
                item.polarity == ClaimPolarity.REFUTES
                for item in self.snapshot.provisional_gold_claims
            ),
            "double_review_task_count": len(self.snapshot.double_review_tasks),
            "double_review_fraction": (
                len(self.snapshot.double_review_tasks) / len(self.snapshot.provisional_gold_claims)
            ),
            "adjudicated_claim_count": sum(
                item.review_status == "adjudicated" for item in self.snapshot.provisional_gold_claims
            ),
            "p3_eligible_claim_count": sum(
                item.eligible_for_p3 for item in self.snapshot.provisional_gold_claims
            ),
            "verbatim_span_coverage": exact_spans / total_spans if total_spans else 1.0,
            "provisional_relation_counts": {
                kind: relation_counts.get(kind, 0)
                for kind in ("supports", "refutes", "replicates")
            },
            "current_text_versions_after_selection_cutoff": current_versions_after_cutoff,
            "historical_backfill_allowed": False,
            "extraction_metrics": self.snapshot.extraction_metrics.model_dump(mode="json"),
            "raw_checksum_matches": raw_checksum,
            "normalized_checksum_matches": normalized_checksum,
            "deterministic_rebuild_matches": deterministic,
        }


def load_default_literature_store() -> LiteratureStore:
    return LiteratureStore.load(
        default_literature_snapshot_path(),
        default_literature_raw_path(),
        default_literature_manifest_path(),
    )
