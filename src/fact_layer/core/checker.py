from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from fact_layer.core.loader import load_all_categories, load_dependencies, load_framework
from fact_layer.core.registry import get_enabled_categories, get_stale_threshold
from fact_layer.models.category import CategoryFile
from fact_layer.models.dependency import DependencyGraph
from fact_layer.models.framework import FrameworkConfig
from fact_layer.models.slot import ACTIVE_STATUSES, is_empty_value


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class CheckIssue(BaseModel):
    category_name: str
    check_type: str
    severity: Severity
    message: str
    slot: str | None = None
    detail: str | None = None


class CheckResult(BaseModel):
    issues: list[CheckIssue] = []

    @property
    def errors(self) -> list[CheckIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[CheckIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


def _check_structural(
    config: FrameworkConfig,
    categories: dict[str, CategoryFile],
    enabled: dict,
    filter_category: str | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    for cat_name, cat_def in enabled.items():
        if filter_category and cat_name != filter_category:
            continue

        if cat_name not in categories:
            issues.append(CheckIssue(
                category_name=cat_name,
                check_type="structural",
                severity=Severity.ERROR,
                message=f"{cat_name} — category enabled but file missing",
            ))
            continue

        cat = categories[cat_name]
        active_slots = {
            k: v for k, v in cat.slots.items()
            if v.meta.status in ACTIVE_STATUSES
            and not is_empty_value(v.value)
        }

        if not active_slots:
            issues.append(CheckIssue(
                category_name=cat_name,
                check_type="structural",
                severity=Severity.ERROR,
                message=f"{cat_name} — category enabled but empty",
            ))
            continue

        for req_slot in cat_def.required_slots:
            if req_slot not in cat.slots:
                issues.append(CheckIssue(
                    category_name=cat_name,
                    check_type="structural",
                    severity=Severity.ERROR,
                    slot=f"{cat_name}.{req_slot}",
                    message=f"{cat_name}.{req_slot} — required slot missing",
                ))
            else:
                sv = cat.slots[req_slot]
                if is_empty_value(sv.value):
                    issues.append(CheckIssue(
                        category_name=cat_name,
                        check_type="structural",
                        severity=Severity.ERROR,
                        slot=f"{cat_name}.{req_slot}",
                        message=f"{cat_name}.{req_slot} — required slot not filled",
                    ))

    return issues


def _check_staleness(
    config: FrameworkConfig,
    categories: dict[str, CategoryFile],
    enabled: dict,
    today: date,
    filter_category: str | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    for cat_name, cat_def in enabled.items():
        if filter_category and cat_name != filter_category:
            continue
        if cat_name not in categories:
            continue

        cat = categories[cat_name]
        threshold_days = get_stale_threshold(config, cat_def.tier)
        if threshold_days is None:
            continue

        for slot_id, sv in cat.slots.items():
            if sv.meta.status not in ACTIVE_STATUSES:
                continue
            if is_empty_value(sv.value):
                continue
            days_since = (today - sv.meta.verified).days
            if days_since > threshold_days:
                issues.append(CheckIssue(
                    category_name=cat_name,
                    check_type="staleness",
                    severity=Severity.WARNING,
                    slot=f"{cat_name}.{slot_id}",
                    message=f"{cat_name}.{slot_id} — last verified {days_since}d ago (threshold: {threshold_days}d)",
                ))

    return issues


def _resolve_slot(
    slot_ref: str,
    categories: dict[str, CategoryFile],
) -> tuple[str | None, date | None]:
    """Return (value, updated_date) for a slot reference like 'tech-stack.database'."""
    parts = slot_ref.split(".", 1)
    if len(parts) != 2:
        return None, None
    cat_name, slot_id = parts
    cat = categories.get(cat_name)
    if not cat or slot_id not in cat.slots:
        return None, None
    sv = cat.slots[slot_id]
    return str(sv.value), sv.meta.updated


def _check_slot_duplicates(
    categories: dict[str, CategoryFile],
    enabled: dict,
    filter_category: str | None,
) -> list[CheckIssue]:
    """B-003: two active slot ids in one category that differ only by case or by
    '-'/'_' are almost certainly the same fact duplicated (the residue of the
    underscore-slot-id bug, where an empty template stub coexists with a filled
    underscore twin). Deterministic, separator/case-only — genuinely distinct ids
    (framework vs cli_framework) are left to the LLM audit."""
    issues: list[CheckIssue] = []

    for cat_name in enabled:
        if filter_category and cat_name != filter_category:
            continue
        cat = categories.get(cat_name)
        if not cat:
            continue

        groups: dict[str, list[str]] = {}
        for slot_id, sv in cat.slots.items():
            if sv.meta.status not in ACTIVE_STATUSES:
                continue
            norm = slot_id.lower().replace("-", "_")
            groups.setdefault(norm, []).append(slot_id)

        for ids in groups.values():
            if len(ids) > 1:
                variants = ", ".join(sorted(ids))
                issues.append(CheckIssue(
                    category_name=cat_name,
                    check_type="slot-duplicate",
                    severity=Severity.WARNING,
                    slot=f"{cat_name}.{sorted(ids)[0]}",
                    message=f"{cat_name}: duplicate slot ids differing only by case or '-'/'_': {variants}",
                    detail="consolidate: migrate the value into one, deprecate the other",
                ))

    return issues


def _slot_exists(slot_ref: str, categories: dict[str, CategoryFile]) -> bool:
    """True if slot_ref ('cat.slot-id') resolves to a slot that actually exists."""
    parts = slot_ref.split(".", 1)
    if len(parts) != 2:
        return False
    cat_name, slot_id = parts
    cat = categories.get(cat_name)
    return bool(cat and slot_id in cat.slots)


def _check_dependency_integrity(
    graph: DependencyGraph,
    categories: dict[str, CategoryFile],
    enabled: dict,
    filter_category: str | None,
) -> list[CheckIssue]:
    """B-001: a dependency edge whose endpoint slot does not exist is a dangling
    edge — a structural defect that must be caught deterministically, not left to
    the LLM audit. Only endpoints in *enabled* categories are checked; edges into
    disabled categories are dormant, not dangling."""
    issues: list[CheckIssue] = []
    enabled_cats = set(enabled.keys())

    for rule in graph.static:
        source_cat = rule.source.split(".")[0]
        if source_cat not in enabled_cats:
            continue
        if filter_category and source_cat != filter_category:
            continue

        if not _slot_exists(rule.source, categories):
            issues.append(CheckIssue(
                category_name=source_cat,
                check_type="dependency-integrity",
                severity=Severity.ERROR,
                slot=rule.source,
                message=f"{rule.source} — dependency edge source slot does not exist (dangling edge)",
                detail="remove the edge with 'fl dep rm', or create the slot",
            ))
            continue  # source missing: the whole rule is dangling, skip its targets

        for target in rule.targets:
            target_cat = target.slot.split(".")[0]
            if target_cat not in enabled_cats:
                continue
            if not _slot_exists(target.slot, categories):
                issues.append(CheckIssue(
                    category_name=source_cat,
                    check_type="dependency-integrity",
                    severity=Severity.ERROR,
                    slot=target.slot,
                    message=(
                        f"{target.slot} — dependency edge target slot does not exist"
                        f" (dangling edge from {rule.source})"
                    ),
                    detail="remove the edge with 'fl dep rm', or create the slot",
                ))

    return issues


def _check_dependencies(
    graph: DependencyGraph,
    categories: dict[str, CategoryFile],
    enabled: dict,
    filter_category: str | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    enabled_cats = set(enabled.keys())

    for rule in graph.static:
        source_cat = rule.source.split(".")[0]
        if source_cat not in enabled_cats:
            continue
        if filter_category and source_cat != filter_category:
            continue

        _, source_updated = _resolve_slot(rule.source, categories)
        if source_updated is None:
            continue

        for target in rule.targets:
            target_cat = target.slot.split(".")[0]
            if target_cat not in enabled_cats:
                continue

            _, target_updated = _resolve_slot(target.slot, categories)
            if target_updated is None:
                continue

            if source_updated > target_updated:
                is_strong = target.type in ("derives-from", "references")
                severity = Severity.ERROR if is_strong else Severity.WARNING
                issues.append(CheckIssue(
                    category_name=source_cat,
                    check_type="dependency",
                    severity=severity,
                    slot=rule.source,
                    message=(
                        f"{rule.source} updated {source_updated}"
                        f" but {target.slot} last updated {target_updated}"
                    ),
                    detail=f"{target.type}: {'downstream must be updated' if is_strong else 'should check'}",
                ))

    return issues


def _check_decisions(
    categories: dict[str, CategoryFile],
    enabled: dict,
    filter_category: str | None,
) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    if "decisions" not in categories or "decisions" not in enabled:
        return issues
    if filter_category and filter_category != "decisions":
        return issues

    dec_cat = categories["decisions"]
    for slot_id, sv in dec_cat.slots.items():
        if sv.meta.status not in ACTIVE_STATUSES:
            continue
        raw = sv.value
        if not isinstance(raw, dict):
            continue
        if raw.get("status") != "active":
            continue

        dec_date_str = raw.get("date")
        if not dec_date_str:
            continue
        try:
            dec_date = date.fromisoformat(str(dec_date_str))
        except ValueError:
            continue

        affected = raw.get("affected-slots", [])
        for affected_slot in affected:
            _, slot_updated = _resolve_slot(affected_slot, categories)
            if slot_updated is None:
                continue
            if slot_updated < dec_date:
                issues.append(CheckIssue(
                    category_name="decisions",
                    check_type="decisions",
                    severity=Severity.WARNING,
                    slot=affected_slot,
                    message=(
                        f"{slot_id.upper()} ({dec_date}) affects {affected_slot}"
                        f" but slot not updated since {slot_updated}"
                    ),
                ))

    return issues


def run_check(
    facts_dir: Path,
    filter_category: str | None = None,
    today: date | None = None,
) -> CheckResult:
    if today is None:
        today = date.today()

    config = load_framework(facts_dir)
    categories = load_all_categories(facts_dir)
    graph = load_dependencies(facts_dir)
    enabled = get_enabled_categories(config)

    issues: list[CheckIssue] = []
    issues.extend(_check_structural(config, categories, enabled, filter_category))
    issues.extend(_check_staleness(config, categories, enabled, today, filter_category))
    issues.extend(_check_slot_duplicates(categories, enabled, filter_category))
    issues.extend(_check_dependency_integrity(graph, categories, enabled, filter_category))
    issues.extend(_check_dependencies(graph, categories, enabled, filter_category))
    issues.extend(_check_decisions(categories, enabled, filter_category))

    return CheckResult(issues=issues)
