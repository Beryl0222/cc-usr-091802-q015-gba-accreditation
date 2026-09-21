"""赛区材料规则的发布与适用推导。"""

from __future__ import annotations

from .models import Event, MaterialRule, Person
from .store import Store


def publish_rule(store: Store, rule: MaterialRule) -> MaterialRule:
    """赛区发布带生效期的材料规则。"""
    store.rules[rule.rule_id] = rule
    return rule


def applicable_rules(store: Store, event: Event, person: Person) -> list:
    """挑出比赛日生效且适用于该人员身份与职责的规则。

    同一材料若有多版规则同时生效,取生效最晚、版本最高的一版。
    """
    day = event.competition_date
    chosen: dict = {}
    for rule in store.rules.values():
        if rule.region != event.host_region:
            continue
        if not rule.effective_on(day):
            continue
        if person.role not in rule.roles:
            continue
        if rule.minors_only and not person.is_minor_on(day):
            continue
        current = chosen.get(rule.material)
        if current is None or (rule.effective_from, rule.version) > (
            current.effective_from,
            current.version,
        ):
            chosen[rule.material] = rule
    return [chosen[material] for material in sorted(chosen, key=lambda m: m.value)]
