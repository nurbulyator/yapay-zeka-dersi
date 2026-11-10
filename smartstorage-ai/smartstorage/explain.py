"""Deterministic Turkish explanations (SPEC_v2 §14). No language model."""
from __future__ import annotations

from .models import (GIB, KIB, MIB, ActionKind, CandidateAction, FileInfo,
                     OptimizationResult, Problem, ReasonCode, ResultStatus, SkipReason)

ALGORITHM_NAMES_TR = {
    "greedy": "Açgözlü (Greedy)",
    "hill_climbing": "Tepe Tırmanma (Hill Climbing)",
    "simulated_annealing": "Benzetimli Tavlama (Simulated Annealing)",
    "exhaustive": "Kaba kuvvet (tam arama)",
}

STATUS_TR = {
    ResultStatus.FEASIBLE.value: "UYGUN PLAN BULUNDU",
    ResultStatus.PROVEN_INFEASIBLE.value: "HEDEF KANITLANABİLİR ŞEKİLDE İMKÂNSIZ",
    ResultStatus.NO_FEASIBLE_FOUND.value: "ARAMA UYGUN PLAN BULAMADI (imkânsızlık kanıtı değil)",
    ResultStatus.INVALID_CONFIG.value: "GEÇERSİZ YAPILANDIRMA",
}

REASON_TR = {
    ReasonCode.EMPTY_SCOPE.value: "Kapsamda uygun dosya yok.",
    ReasonCode.NO_ALLOWED_ACTIONS.value: "Hiçbir dosya için KEEP dışında izinli işlem yok (ayarlar veya koruma kuralları).",
    ReasonCode.NO_DESTINATION.value: "Taşımaya izin verildi ancak kaynak hacimden farklı, güvenli bir hedef hacim yok.",
    ReasonCode.PROTECTED_ONLY.value: "Kapsamdaki tüm dosyalar korunuyor.",
    ReasonCode.INSUFFICIENT_THEORETICAL_GAIN.value: "Tüm dosyalar için mümkün olan en yüksek tahmini kazanç bile hedefin altında (üst sınır kanıtı).",
    ReasonCode.DESTINATION_CAPACITY.value: "Hedef hacimlerin güvenlik payı sonrası boş alanı yetersiz.",
    ReasonCode.SCAN_INCOMPLETE.value: "Tarama eksik (dosya sınırı veya okunamayan yollar); sonuç yalnızca taranan dosyalar içindir.",
    ReasonCode.UNSTABLE_FILE.value: "Bazı dosyalar tarama sırasında değişti; yalnızca KEEP önerildi.",
    ReasonCode.NO_FEASIBLE_FOUND.value: "Arama uygun plan bulamadı; bu, uygun planın olmadığının kanıtı değildir.",
    ReasonCode.INVALID_CONFIG.value: "Yapılandırma geçersiz (klasör, hedef veya kaynak hacim).",
    ReasonCode.GOAL_NOT_MET.value: "Plan hedef alan kazancına ulaşmıyor.",
    ReasonCode.INVALID_ASSIGNMENT.value: "Plan geçersiz atama içeriyor.",
}

SKIP_TR = {
    SkipReason.PROTECTED.value: "Koruma kuralı nedeniyle olduğu yerde bırakıldı.",
    SkipReason.RISKY_SUFFIX.value: "Riskli dosya türü (program/veritabanı vb.); yalnızca KEEP.",
    SkipReason.HARDLINK.value: "Sabit bağlantılı dosya; taşımak veya sıkıştırmak yer açmaz.",
    SkipReason.CLOUD_PLACEHOLDER.value: "Bulut/yer tutucu dosya (ör. OneDrive); içeriği okunmadı, yalnızca KEEP.",
    SkipReason.RECENTLY_MODIFIED.value: "Son 10 dakikada değiştirilmiş; kararsız olabilir, yalnızca KEEP.",
    SkipReason.UNREADABLE.value: "Okunamadı; yalnızca KEEP.",
    SkipReason.ZERO_SIZE.value: "Boş dosya; işlem yer açmaz.",
    SkipReason.OTHER_VOLUME.value: "Kaynak hacimde değil; yalnızca KEEP.",
    SkipReason.UNSTABLE_FILE.value: "Tarama ile tahmin arasında değişti; yalnızca KEEP.",
}


def _num(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def fmt_bytes(n: int) -> str:
    """Binary units with Turkish decimal comma: 1,8 GiB."""
    n = int(n)
    if abs(n) >= GIB:
        return f"{_num(n / GIB, 2)} GiB"
    if abs(n) >= MIB:
        return f"{_num(n / MIB, 1)} MiB"
    if abs(n) >= KIB:
        return f"{_num(n / KIB, 1)} KiB"
    return f"{n} B"


def volume_label(problem: Problem, vid: str | None) -> str:
    if vid is None:
        return "-"
    for d in problem.disks:
        if d.volume_id == vid:
            return d.mountpoint.rstrip("\\/") or d.mountpoint
    return vid


def explain_action(problem: Problem, f: FileInfo, c: CandidateAction) -> str:
    name = f.name
    if c.kind == ActionKind.COMPRESS:
        return (f"{name}: Kayıpsız sıkıştırma önerildi. Tahmini kaynak alan kazancı "
                f"{fmt_bytes(c.source_gain_bytes)}; önem {f.importance}/9; işlem maliyeti "
                f"{_num(c.total_cost, 2)}. Kazanç tahminidir; dosya henüz değiştirilmedi.")
    if c.kind == ActionKind.MOVE:
        src = volume_label(problem, problem.preferences.source_volume_id)
        dst = volume_label(problem, c.destination_volume_id)
        return (f"{name}: {src} kaynak hacminden {dst} hedef hacmine taşıma önerildi. "
                f"Kaynakta tahmini {fmt_bytes(c.source_gain_bytes)} yer açılır; {dst} üzerinde "
                f"{fmt_bytes(c.destination_use_bytes)} kapasite gerekir. Önem {f.importance}/9; "
                f"maliyet {_num(c.total_cost, 2)}.")
    if f.skip_reason:
        return f"{name}: {SKIP_TR.get(f.skip_reason, 'Yalnızca KEEP uygun.')}"
    return f"{name}: Olduğu yerde bırakıldı (hedef için değiştirilmesi gerekmedi)."


def explain_result(problem: Problem, result: OptimizationResult) -> list[str]:
    """Summary lines for a result, in Turkish."""
    algo = ALGORITHM_NAMES_TR.get(result.algorithm, result.algorithm)
    goal = problem.preferences.goal_bytes
    lines = [f"{algo}: {STATUS_TR.get(result.status, result.status)}."]
    if result.feasible and result.evaluation:
        ev = result.evaluation
        n_changed = sum(1 for a in result.plan.values() if not a.endswith(":KEEP:-"))
        lines.append(f"Tahmini kaynak kazancı {fmt_bytes(ev.gain_bytes)} (hedef {fmt_bytes(goal)}); "
                     f"toplam müdahale maliyeti {_num(ev.total_cost, 2)}; değişen dosya sayısı {n_changed}.")
        if goal == 0:
            lines.append("Hedef 0 olduğu için en iyi plan tüm dosyaları olduğu yerde bırakmaktır.")
    else:
        lines.append(f"İzinli işlemler ve mevcut hedef hacim kapasiteleriyle {fmt_bytes(goal)} "
                     f"hedefe ulaşılabilecek plan bulunamadı.")
        for code in result.reason_codes:
            if code in REASON_TR:
                lines.append(f"• {REASON_TR[code]}")
    lines.append("Tüm değerler tahminidir; kuru çalıştırma (dry-run) modunda hiçbir dosya değiştirilmez.")
    return lines
