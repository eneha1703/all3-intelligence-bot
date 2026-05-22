"""Weekly digest corpus loading helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from all3_radar.editorial_memory.prompt_context import build_digest_memory_context
from all3_radar.summarization.fallback_summary import generate_fallback_summary

WEEK_KEY_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[2]
WEEKLY_STYLE_GUIDE_PATH = MODULE_DIR / "weekly_style_guide.md"
WEEKLY_WRITER_EXAMPLES_PATH = MODULE_DIR / "weekly_writer_examples.json"
URL_RE = re.compile(r"https?://\S+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class DigestCandidate:
    canonical_event_id: str
    normalized_item_id: str
    source_id: str
    title: str
    canonical_url: str
    published_ts: datetime | None
    score: int
    summary_text: str | None
    event_flags: dict[str, bool]
    digest_grounding: str | None = None
    full_text_excerpt: str | None = None
    full_text_status: str | None = None
    story_type: str = "general_relevant"
    angle_guard: tuple[str, ...] = ()


@dataclass(frozen=True)
class DigestWindow:
    week_key: str
    previous_thursday: date
    start_date: date
    current_thursday: date
    iso_week_number: int
    title: str


def _normalize_current_thursday(week_key: str, today: date | None = None) -> date:
    normalized = week_key.strip()
    if normalized == "latest":
        resolved_today = today or datetime.now(timezone.utc).date()
        offset = (resolved_today.weekday() - 3) % 7
        return resolved_today - timedelta(days=offset)

    match = WEEK_KEY_RE.match(normalized)
    if not match:
        raise ValueError(f"Invalid week key: {week_key!r}")
    iso_year = int(match.group("year"))
    iso_week = int(match.group("week"))
    return date.fromisocalendar(iso_year, iso_week, 4)


def _format_digest_range(previous_thursday: date, current_thursday: date) -> str:
    if previous_thursday.year == current_thursday.year and previous_thursday.month == current_thursday.month:
        return f"{previous_thursday.day}-{current_thursday.day} {current_thursday.strftime('%B %Y')}"
    if previous_thursday.year == current_thursday.year:
        return (
            f"{previous_thursday.day} {previous_thursday.strftime('%B')}-"
            f"{current_thursday.day} {current_thursday.strftime('%B %Y')}"
        )
    return (
        f"{previous_thursday.day} {previous_thursday.strftime('%B %Y')}-"
        f"{current_thursday.day} {current_thursday.strftime('%B %Y')}"
    )


def resolve_digest_window(week_key: str, today: date | None = None) -> DigestWindow:
    current_thursday = _normalize_current_thursday(week_key, today=today)
    previous_thursday = current_thursday - timedelta(days=7)
    start_date = previous_thursday + timedelta(days=1)
    iso_year, iso_week, _ = current_thursday.isocalendar()
    normalized_week_key = f"{iso_year}-W{iso_week:02d}"
    title = (
        f"Top 5 News Highlights | "
        f"{_format_digest_range(start_date, current_thursday)} | "
        f"Week {iso_week}"
    )
    return DigestWindow(
        week_key=normalized_week_key,
        previous_thursday=previous_thursday,
        start_date=start_date,
        current_thursday=current_thursday,
        iso_week_number=iso_week,
        title=title,
    )


def parse_week_key(week_key: str) -> tuple[date, date]:
    window = resolve_digest_window(week_key)
    return window.start_date, window.current_thursday


def build_default_output_path(repo_root: Path, week_key: str) -> Path:
    safe_week = week_key.replace("/", "_")
    return repo_root / "data" / f"weekly_digest_{safe_week}.md"


def build_report_output_path(repo_root: Path, week_key: str) -> Path:
    safe_week = week_key.replace("/", "_")
    return repo_root / "data" / f"weekly_digest_{safe_week}.report.md"


def _normalize_story_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _has_any_story_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _classify_story_type(title: str, summary_text: str | None, event_flags: dict[str, bool]) -> str:
    combined = f"{_normalize_story_text(title)} {_normalize_story_text(summary_text)}".strip()

    if (
        bool(event_flags.get("timber_strategic_signal"))
        or bool(event_flags.get("timber_policy_signal"))
        or bool(event_flags.get("timber_economics_signal"))
        or bool(event_flags.get("timber_performance_signal"))
        or _has_any_story_phrase(combined, ("timber", "mass timber", "clt", "glulam", "lvl"))
    ):
        return "timber_adoption"

    if bool(event_flags.get("construction_statistics_signal")) or _has_any_story_phrase(
        combined,
        (
            "permits",
            "approvals",
            "completions",
            "housing gap",
            "prices rose",
            "rents up",
            "project starts",
            "planning approvals",
            "pipeline",
        ),
    ):
        return "housing_market_signal"

    if bool(event_flags.get("funding_event")) and (
        bool(event_flags.get("construction_innovation_signal"))
        or _has_any_story_phrase(
            combined,
            (
                "construction robotics",
                "construction sites",
                "jobsite",
                "retrofit",
                "automation as a service",
                "off site robotic fabrication",
                "on site assembly",
                "task specific",
            ),
        )
    ):
        return "construction_robotics_funding"

    if _has_any_story_phrase(
        combined,
        (
            "simulation",
            "sim to real",
            "digital twins",
            "factory robots that behave identically",
            "trained in simulation",
            "physical robot behaviour",
            "nvidia",
            "fanuc",
        ),
    ):
        return "robotics_tooling"

    if (
        bool(event_flags.get("industrial_robotics_signal"))
        or bool(event_flags.get("deployment_event"))
    ) and _has_any_story_phrase(
        combined,
        (
            "deploy",
            "deployment",
            "operating",
            "factory",
            "plants",
            "warehouse",
            "zero failures",
            "24 hours",
            "full shift",
            "without intervention",
            "humanoid",
            "robots are already",
        ),
    ):
        return "industrial_deployment"

    if bool(event_flags.get("funding_event")) and _has_any_story_phrase(
        combined,
        (
            "valuation",
            "total funding",
            "advanced manufacturing",
            "physical industries",
            "platform opportunity",
        ),
    ):
        return "strategic_capital"

    return "general_relevant"


def _build_angle_guard(story_type: str, title: str, summary_text: str | None, event_flags: dict[str, bool]) -> tuple[str, ...]:
    combined = f"{_normalize_story_text(title)} {_normalize_story_text(summary_text)}".strip()
    notes: list[str] = []

    if story_type == "timber_adoption":
        notes.append(
            "Surface the adoption barrier, delivery-system mismatch, or share shift. Do not default to generic timber momentum or sustainability language."
        )
        if _has_any_story_phrase(
            combined,
            (
                "consumption fell",
                "imports rose",
                "losing share",
                "light gauge steel",
                "prefabricated dwelling",
                "mid rise approvals",
                "mid rise has overtaken detached",
            ),
        ):
            notes.append(
                "Center the contradiction between rising mid-rise demand and timber losing practical share; do not drift into a generic 'timber is becoming normal' angle."
            )
    elif story_type == "construction_robotics_funding":
        notes.append(
            "Investor roll call is secondary unless the investor itself is the signal. Focus on the workflow wedge, retrofit model, task packaging, or measurable labour/time gain."
        )
    elif story_type == "industrial_deployment":
        notes.append(
            "Treat this as an operational proof or deployment-threshold story. Focus on what the run or rollout shows and what it still does not prove."
        )
        if _has_any_story_phrase(combined, ("viewers", "viral", "livestream", "bob frank and gary", "x as it sorted")):
            notes.append(
                "Ignore audience, virality, or character-name details unless they change the operating claim."
            )
        if _has_any_story_phrase(combined, ("atlas", "hyundai", "own factories", "us plants")):
            notes.append(
                "Frame this as an internal factory test-bed and scale commitment, not as generic humanoid hype."
            )
    elif story_type == "robotics_tooling":
        notes.append(
            "Frame this as a deployment-cost, deployment-speed, or sim-to-real reliability story, not as a generic partnership recap."
        )
    elif story_type == "housing_market_signal":
        notes.append(
            "Name the actual pipeline constraint directly: permits, approvals, completions, delivery time, or rebuild speed."
        )
    elif story_type == "strategic_capital":
        notes.append(
            "Explain what investors are actually betting on operationally, not just that capital is flowing."
        )

    if not notes:
        notes.append("Stay close to the strongest fact and one observed implication.")
    return tuple(notes)


def _clean_grounding_source_text(title: str, summary_text: str | None) -> str:
    base = summary_text or generate_fallback_summary(title, summary_text) or title
    base = URL_RE.sub("", base)
    base = re.sub(r"^\s*insider brief[:\s-]*", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+", " ", base).strip(" .")
    return base


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = [part.strip(" .") for part in SENTENCE_SPLIT_RE.split(text) if part.strip(" .")]
    return parts


def _should_drop_grounding_sentence(story_type: str, sentence: str) -> bool:
    normalized = _normalize_story_text(sentence)
    if not normalized:
        return True

    if story_type == "timber_adoption":
        if _has_any_story_phrase(
            normalized,
            ("tim woods", "national conference", "at the crossroads", "according to", "afwi precinct"),
        ):
            return True

    if story_type == "construction_robotics_funding":
        if _has_any_story_phrase(
            normalized,
            (
                "led by",
                "existing investors",
                "joined the round",
                "with participation from",
                "backers",
                "future family office",
                "skip capital",
                "blackbird",
                "tanarra",
                "big pi ventures",
            ),
        ):
            return True

    if story_type == "industrial_deployment":
        if _has_any_story_phrase(
            normalized,
            (
                "viewers gave",
                "million views",
                "viral livestream",
                "binge watch",
                "bob frank and gary",
                "brett adcock",
            ),
        ):
            return True

    return False


def _coalesce_grounding_sentences(
    story_type: str,
    sentences: list[str],
    cleaned_source: str,
    normalized_source: str,
) -> str | None:
    if story_type == "timber_adoption":
        if _has_any_story_phrase(
            normalized_source,
            ("mid rise has overtaken detached", "mid rise approvals", "mid rise surge"),
        ) and _has_any_story_phrase(
            normalized_source,
            ("ceding ground", "historically dominated", "losing share", "consumption fell"),
        ):
            return (
                "Mid-rise has overtaken detached housing as the growth typology, but timber frame and truss systems "
                "built for low-rise volume are ceding ground in that segment."
            )
        if _has_any_story_phrase(normalized_source, ("consumption fell", "imports rose", "light gauge steel")):
            return (
                "Mid-rise demand is rising, but structural timber appears to be losing share to rival delivery systems "
                "rather than capturing the shift."
            )

    if story_type == "construction_robotics_funding":
        match = re.search(r"looks to\s+([^.]+)", cleaned_source, flags=re.IGNORECASE)
        if not match:
            match = re.search(
                r"to\s+(expand production, increase deployments and develop additional automation systems[^.]*)",
                cleaned_source,
                flags=re.IGNORECASE,
            )
        if match:
            clause = match.group(1).strip(" .")
            return f"The new funding is being used to {clause}."

    if story_type == "industrial_deployment":
        if _has_any_story_phrase(normalized_source, ("24 hours", "zero failures")):
            return (
                "The robots ran autonomously for 24 hours with zero reported failures, which is a cleaner operating "
                "proof than a staged demo but still short of full industrial reliability."
            )
        if _has_any_story_phrase(normalized_source, ("25 000", "25000", "atlas", "hyundai", "own factories", "us plants")):
            return (
                "Deploying more than 25,000 Atlas robots in its own factories turns Hyundai's plants into the main "
                "test bed for humanoid scale-up."
            )

    if story_type == "robotics_tooling":
        if _has_any_story_phrase(normalized_source, ("simulation", "sim to real", "identically", "digital twins", "reality")):
            return (
                "The goal is to make robot behaviour match between simulation and the factory floor, reducing "
                "sim-to-real friction in deployment."
            )

    if story_type == "housing_market_signal":
        if _has_any_story_phrase(normalized_source, ("permits", "approvals", "completions", "pipeline")):
            return sentences[0] if sentences else None

    return None


def _build_digest_grounding(
    story_type: str,
    title: str,
    summary_text: str | None,
    event_flags: dict[str, bool],
) -> str | None:
    del event_flags  # reserved for future source-specific grounding rules
    cleaned_source = _clean_grounding_source_text(title, summary_text)
    if not cleaned_source:
        return None

    sentences = [sentence for sentence in _split_sentences(cleaned_source) if not _should_drop_grounding_sentence(story_type, sentence)]
    normalized_source = _normalize_story_text(cleaned_source)
    custom = _coalesce_grounding_sentences(story_type, sentences, cleaned_source, normalized_source)
    if custom:
        return custom

    if not sentences:
        return cleaned_source
    if len(sentences) == 1:
        return f"{sentences[0]}."
    return f"{sentences[0]}. {sentences[1]}."


def hydrate_digest_candidates(rows: list[dict[str, Any]]) -> list[DigestCandidate]:
    candidates: list[DigestCandidate] = []
    for row in rows:
        signals = json.loads(row["signals_json"] or "{}")
        event_flags = signals.get("event_flags", {}) if isinstance(signals, dict) else {}
        story_type = _classify_story_type(str(row["title"]), row.get("summary_text"), event_flags)
        angle_guard = _build_angle_guard(story_type, str(row["title"]), row.get("summary_text"), event_flags)
        digest_grounding = _build_digest_grounding(
            story_type,
            str(row["title"]),
            row.get("summary_text"),
            {key: bool(value) for key, value in event_flags.items()},
        )
        candidates.append(
            DigestCandidate(
                canonical_event_id=str(row["canonical_event_id"]),
                normalized_item_id=str(row["normalized_item_id"]),
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                canonical_url=str(row["canonical_url"]),
                published_ts=datetime.fromisoformat(row["published_ts"]) if row.get("published_ts") else None,
                score=int(row["score"]),
                summary_text=row.get("summary_text"),
                digest_grounding=digest_grounding,
                event_flags={key: bool(value) for key, value in event_flags.items()},
                story_type=story_type,
                angle_guard=angle_guard,
            )
        )
    return candidates


@lru_cache(maxsize=1)
def _load_weekly_style_guide() -> str:
    return WEEKLY_STYLE_GUIDE_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _load_weekly_writer_examples() -> list[dict[str, Any]]:
    payload = json.loads(WEEKLY_WRITER_EXAMPLES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Weekly writer examples payload must be a list.")
    examples: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        examples.append(entry)
    return examples


def build_claude_corpus_prompt(week_key: str, candidates: list[DigestCandidate], max_items: int) -> str:
    selected = candidates[:max_items]
    lines = [
        f"You are drafting a weekly markdown synthesis for Bot 1 for week {week_key}.",
        "Use only the provided items.",
        "Return markdown that starts with '## Claude Synthesis'.",
        "Include 3 to 5 short bullets covering the most important cross-story themes.",
        "Then add one short paragraph explaining why the week's signals matter operationally.",
        "Do not invent facts, companies, funding amounts, or outcomes not present in the input.",
        "Do not repeat every headline one by one.",
        "",
        "Input items:",
    ]
    for index, candidate in enumerate(selected, start=1):
        published_label = candidate.published_ts.date().isoformat() if candidate.published_ts else "unknown-date"
        summary = candidate.summary_text or "(no summary stored)"
        lines.extend(
            [
                f"{index}. Title: {candidate.title}",
                f"   Source: {candidate.source_id}",
                f"   Published: {published_label}",
                f"   Score: {candidate.score}",
                f"   URL: {candidate.canonical_url}",
                f"   Summary: {candidate.digest_grounding or summary}",
            ]
        )
    return "\n".join(lines)


def build_claude_selection_prompt(
    window: DigestWindow,
    candidates: list[DigestCandidate],
    max_items: int,
    mandatory_ids: tuple[str, ...] = (),
) -> str:
    selected = candidates[:max_items]
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "normalized_item_id": candidate.normalized_item_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "digest_grounding": candidate.digest_grounding,
            "full_text_excerpt": candidate.full_text_excerpt,
            "full_text_status": candidate.full_text_status,
            "summary": candidate.digest_grounding or candidate.summary_text,
            "raw_summary": candidate.summary_text,
            "signals": candidate.event_flags,
            "story_type": candidate.story_type,
            "angle_guard": list(candidate.angle_guard),
        }
        for candidate in selected
    ]
    lines = [
            "You are selecting the Top 5 weekly digest stories for Bot 2.",
            f"Digest title: {window.title}",
            f"Digest window: {window.start_date.isoformat()} through {window.current_thursday.isoformat()}",
            "Select exactly 5 distinct stories from the provided candidates.",
            "Prioritize All3 relevance, physical AI, industrial robotics, construction automation, housing industrialization, timber adoption/scaling/economics/policy, infrastructure automation, strategic signal strength, novelty, and hard operational evidence.",
            "Prefer stories with a sharp operational takeaway, not just category relevance.",
            "Treat `summary` as the cleaned editorial grounding. Use `raw_summary` only when it adds a concrete fact the cleaned grounding omits.",
            "When `full_text_excerpt` is available, treat it as the strongest grounding source for selection because it comes from a reread of the article URL.",
            "Do not elevate timber logistics, marine terminal redevelopment, distribution hubs, or generic supply-chain positioning unless the story clearly changes adoption economics, building delivery, code acceptance, or project execution.",
            "Do not include Ukraine reconstruction or non-core geography timber showcase stories unless they carry direct adoption-economics, code, permitting, or scalable delivery relevance to the core market thesis.",
            "Reject duplicate coverage of the same event and weak generic commentary.",
            "Consumer AI, consumer robotics marketing, founder documentaries, launch-video publicity, restaurant/menu personalization AI, generic automotive capex, generic trade-policy stories, and generic executive/profile stories should not make the Top 5 unless robotics/automation is central.",
    ]
    if mandatory_ids:
        lines.extend(
            [
                "The following canonical_event_id values are mandatory and must be included in selected_ids:",
                json.dumps(list(mandatory_ids), ensure_ascii=False, sort_keys=True),
            ]
        )
    lines.extend(
        [
            "Return only compact JSON with this exact schema:",
            '{"selected_ids":["canonical_event_id_1","canonical_event_id_2","canonical_event_id_3","canonical_event_id_4","canonical_event_id_5"]}',
            "",
            "Candidates JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )
    return "\n".join(lines)




def build_claude_writer_prompt(window: DigestWindow, candidates: list[DigestCandidate]) -> str:
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "digest_grounding": candidate.digest_grounding,
            "full_text_excerpt": candidate.full_text_excerpt,
            "full_text_status": candidate.full_text_status,
            "summary": candidate.digest_grounding or candidate.summary_text,
            "raw_summary": candidate.summary_text,
            "signals": candidate.event_flags,
            "story_type": candidate.story_type,
            "angle_guard": list(candidate.angle_guard),
        }
        for candidate in candidates
    ]
    style_guide = _load_weekly_style_guide()
    examples = _load_weekly_writer_examples()
    memory_context = build_digest_memory_context(REPO_ROOT)
    return "\n".join(
        [
            "Write the final Weekly Digest Bot 2 message in Telegram HTML.",
            "English only, even when a source is non-English.",
            "Write like a smart human editor producing a short weekly note.",
            "Be concise, clear, natural, and non-hyped.",
            "Sound like a sharp human editor, not a consultant memo and not an AI summary engine.",
            "Do not sound like an AI assistant, a press release, or a database recap.",
            "Use exactly 5 items and keep each item to one compact paragraph.",
            "Write one item per selected story only.",
            "Do not create synthetic wrap-up items or combine multiple selected stories into one extra item.",
            "Aim for roughly 45 to 75 words per item.",
            "Prefer 2 short sentences per item. Use 3 only when the third adds a clearly different fact or caveat.",
            "Push toward a laconic editorial voice: compact, dry, and slightly hard-edged rather than rounded or explanatory.",
            "The first line must be the digest title exactly as provided.",
            "For each item use this structure:",
            "1. <b>Headline</b>",
            'Paragraph ending with <a href="SOURCE_URL">Link</a>',
            "Do not show raw URLs in visible text.",
            "Do not invent facts beyond the provided input.",
            "Treat `summary` as the cleaned editorial grounding. Use `raw_summary` only if it contributes one extra concrete fact.",
            "When `full_text_excerpt` is available, use it to correct weak or incomplete summaries, but do not quote long passages.",
            "Treat each item as a compact editorial note with fixed sentence roles.",
            "Headline = thesis. First sentence = core evidence. Final sentence = narrow implication.",
            "Lead each paragraph with the strongest fact, then add one concise implication.",
            "Make the implication specific and observed from the facts, not broad and generic.",
            "Be willing to stop earlier. A shorter, cleaner paragraph is better than a fully explained one.",
            "Vary the framing across items instead of repeating the same conclusion formula.",
            "Use currency formatting like USD 120B, USD 25M, and EUR 100M.",
            "Do not use first-person company framing such as 'we', 'our', 'our need', 'our goals', or 'our strategy'.",
            "The implication can be about All3, the sector, physical AI, robotics, timber adoption, industrial systems, infrastructure, or construction more broadly.",
            "Do not force every item to explain why it matters specifically to All3.",
            "Do not simply restate the source headline in either the bold headline or the first sentence.",
            "Do not repeat the same core fact or idea in the headline and the first sentence with only minor wording changes.",
            "If the headline already carries the funding, deployment, or policy fact, the first sentence should add the most useful extra detail or move to a sharper angle.",
            "Do not repeat a number, percentage, funding amount, valuation, unit count, or timeline in both the headline and the first sentence unless the second mention adds a different analytical function.",
            "Do not default to starting every paragraph with the company name.",
            "Often it is better to start with the strongest fact, metric, market shift, deployment scale, or construction detail.",
            "Do not write bland summaries like 'Company X raised money for Y' unless the deeper point is made clear.",
            "Use plain English. If a sentence can be simpler, make it simpler.",
            "If a paragraph still works after cutting 20% of the words, cut them.",
            "Prefer short words over memo words and finance words.",
            "Avoid words like 'thesis', 'lineage', 'durable', 'utilisation', 'trajectory', 'structural', 'meaningful', 'vehicle', and 'logic' when a simpler word works.",
            "Avoid phrases like 'the real thesis', 'what matters more', 'stress test', 'production-grade', 'at meaningful scale', 'finding traction', or 'different logic'.",
            "Avoid glue phrases like 'which makes', 'that means', 'this gives', 'the capital goes toward', or 'the result is' when a more direct line will do.",
            "Prefer the most natural thesis already visible in the facts over a more theatrical, stylized, or clever angle.",
            "Write like an industry editor, not a columnist, feature writer, or culture critic.",
            "If a story is modest, write a modest item. Do not manufacture weight through rhetoric.",
            "Avoid vague abstractions such as 'recognition', 'direction', 'logic', 'meaningful bet', or 'important signal' unless you immediately tie them to a concrete mechanism.",
            "Do not use padded strategy-speak like 'this reflects broader recognition' when a sharper factual angle is available.",
            "Do not overstate with speculative lines like 'this could compress the gap' unless the provided facts directly support that claim.",
            "If a better sharp angle is not available, stay concrete and restrained rather than sounding clever.",
            "Do not round off a sharp point with a soft qualifier just to sound balanced.",
            "Do not explain the implication twice in slightly different ways.",
            "If a selected item has thin grounding, stay close to the provided title and summary instead of filling gaps creatively.",
            "Do not infer geography, market comparisons, buyer motivations, policy context, financing dynamics, or adoption drivers unless they are explicitly present in the provided input.",
            "Do not sound like a market memo, strategy deck, or founder essay.",
            "Avoid stacked clauses. Keep syntax simple and direct.",
            "Do not end every item with generic phrases like 'the signal is', 'this highlights', or 'this underscores'.",
            "Mix the editorial voice across items so the digest reads like it was written by a person, not a template.",
            "Do not drift into elegantly generic wording that could fit almost any adjacent story.",
            "If an item does not support a strong interpretive angle from the provided facts, stay concrete and restrained rather than inventing significance.",
            "",
            "Story-type guidance:",
            "- housing_market_signal: name the pipeline bottleneck directly and do not end on a vague housing-pressure line.",
            "- timber_adoption: focus on adoption barriers, share shifts, competing delivery systems, code/economics, or where timber is winning or losing practical ground. Do not drift into generic timber momentum or sustainability language.",
            "- construction_robotics_funding: the funding is not the point by itself. Focus on the commercial wedge, workflow, retrofit logic, packaging model, or measurable site gain.",
            "- industrial_deployment: focus on the operating claim, deployment threshold, or what the proof does and does not show. Do not spend the implication on audience, virality, or publicity.",
            "- robotics_tooling: frame the item around deployment speed, deployment cost, sim-to-real transfer, or training friction, not just the partnership announcement.",
            "- strategic_capital: explain what the capital is betting on operationally, not just that the round was large.",
            f"Title: {window.title}",
            "",
            "House style guide:",
            style_guide,
            "",
            memory_context,
            "",
            "Reference examples:",
            json.dumps(examples, ensure_ascii=False, sort_keys=True),
            "",
            "Selected items JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )


def build_claude_revision_prompt(window: DigestWindow, candidates: list[DigestCandidate], draft_markdown: str) -> str:
    payload = [
        {
            "canonical_event_id": candidate.canonical_event_id,
            "source": candidate.source_id,
            "title": candidate.title,
            "url": candidate.canonical_url,
            "published_ts": candidate.published_ts.isoformat() if candidate.published_ts else None,
            "score": candidate.score,
            "digest_grounding": candidate.digest_grounding,
            "full_text_excerpt": candidate.full_text_excerpt,
            "full_text_status": candidate.full_text_status,
            "summary": candidate.digest_grounding or candidate.summary_text,
            "raw_summary": candidate.summary_text,
            "signals": candidate.event_flags,
            "story_type": candidate.story_type,
            "angle_guard": list(candidate.angle_guard),
        }
        for candidate in candidates
    ]
    return "\n".join(
        [
            "Review the drafted Weekly Digest Bot 2 message item by item and return a corrected final version in Telegram HTML.",
            f"Digest title: {window.title}",
            "Keep exactly 5 items, keep the same stories, and preserve the visible Link anchors.",
            "Return the full final digest only. Do not add notes, bullets, JSON, or commentary.",
            "Use the selected-item data as the ground truth.",
            "Treat `summary` as the cleaned editorial grounding. Prefer it over `raw_summary` when the raw text contains investor lists, conference attribution, names, or publicity noise.",
            "When `full_text_excerpt` is available, use it to check whether the draft missed the article's main contradiction, metric, or operating point.",
            "Fix only what is needed, but fix it decisively when a paragraph drifts away from the source facts or the intended angle.",
            "Revise with a ruthless editor's hand: cut padding, cut repeated explanation, and cut one sentence entirely if the item becomes stronger.",
            "Priority checks:",
            "1. Remove unsupported inference, invented context, or added market logic not present in the provided item data.",
            "2. Correct angle drift if the paragraph ignores the story_type or angle_guard.",
            "3. Remove investor laundry lists unless the investor identity itself is the signal.",
            "4. Remove audience, virality, character-name, or publicity details unless they change the operating claim.",
            "5. Keep implications narrow, factual, and operational.",
            "6. Prefer the sharper contradiction or bottleneck when the item data clearly contains one.",
            "7. Prefer 2 short sentences over 3 when nothing important is lost.",
            "8. Replace rounded, generic phrasing with a blunter observed line whenever the facts support it.",
            "For timber_adoption stories, prefer adoption barrier, share-loss, economics, delivery-system mismatch, or code angle over generic timber momentum.",
            "For construction_robotics_funding stories, the workflow wedge matters more than the cap table.",
            "For industrial_deployment stories, the operating threshold matters more than the social reaction.",
            "For robotics_tooling stories, frame the implication around deployment speed, cost, or sim-to-real reliability.",
            "If the draft is already strong, return it with minimal or no changes.",
            "",
            "Selected items JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "",
            "Draft digest to revise:",
            draft_markdown,
        ]
    )
