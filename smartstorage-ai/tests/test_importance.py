import pytest

from conftest import fi
from smartstorage.importance import ImportanceRule, apply_rules, resolve_importance


def test_default_importance_is_normal():
    assert resolve_importance("/u/x.txt", [], []) == (5, False)


def test_closest_parent_wins_and_protection_dominates(tmp_path):
    a, b = tmp_path / "A", tmp_path / "A" / "B"
    rules = [ImportanceRule(str(a), 9), ImportanceRule(str(b), 1)]
    assert resolve_importance(str(b / "f"), rules, [])[0] == 1
    assert resolve_importance(str(a / "f"), rules, [])[0] == 9
    imp, prot = resolve_importance(str(b / "f"), rules, [str(a)])
    assert prot and imp == 9


def test_invalid_importance_rejected():
    with pytest.raises(ValueError):
        ImportanceRule("/x", 7)


def test_apply_rules_marks_protected_keep_only(tmp_path):
    from dataclasses import replace
    f = replace(fi("a", 10), path=str(tmp_path / "T" / "a.dat"))
    out = apply_rules([f], [], [str(tmp_path / "T")])
    assert out[0].protected and not out[0].eligible and out[0].skip_reason == "PROTECTED"
