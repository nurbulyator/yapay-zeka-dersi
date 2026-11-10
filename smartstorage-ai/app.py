"""SmartStorage AI — Streamlit arayüzü (yerel, salt okunur, dry-run).

Çalıştırma:  streamlit run app.py
Bu dosyanın içe aktarılması hiçbir dosya işlemi başlatmaz.
"""
from __future__ import annotations

import hashlib
import json

from smartstorage.actions import build_problem
from smartstorage.annealing import SAConfig
from smartstorage.disks import discover_disks
from smartstorage.explain import (ALGORITHM_NAMES_TR, REASON_TR, SKIP_TR, STATUS_TR,
                                  explain_action, explain_result, fmt_bytes, volume_label)
from smartstorage.importance import ImportanceRule
from smartstorage.models import GIB, ActionKind, Preferences
from smartstorage.pipeline import analyze_folders, run_all
from smartstorage.sample_data import (SOURCE_VID, greedy_trap_problem, simulated_disks,
                                      synthetic_files)
from smartstorage.scanner import TEST_DATA_DIR, ScopeError
from smartstorage.serialize import to_csv, to_json

PRIORITY_TR = {"Güvenlik": "safe", "Dengeli": "balanced", "Hız": "fast"}
DEMO_DIR = TEST_DATA_DIR / "demo_kullanici"


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _lines(text: str) -> list[str]:
    return [ln.strip().strip('"') for ln in (text or "").splitlines() if ln.strip()]


def main() -> None:  # noqa: C901 - linear UI script
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="SmartStorage AI", layout="wide")
    ss = st.session_state

    # 1. Başlık & güvenlik ----------------------------------------------------
    st.title("SmartStorage AI")
    st.caption("Yerel Akıllı Depolama Optimizasyon Ajanı — Greedy, Tepe Tırmanma ve Benzetimli Tavlama")
    st.info("🔒 **Yerel / Önizleme modu — Dosyalar değiştirilmez.** Uygulama yalnızca seçtiğiniz "
            "klasörlerin meta verisini okur ve bir **öneri planı** üretir. Taşıma, sıkıştırma veya "
            "silme yapılmaz; tüm kazançlar **tahminidir**.")

    mode = st.radio("Çalışma modu", ["Gerçek klasör", "Sentetik senaryo (demo)"], horizontal=True,
                    help="Sentetik mod, tek diskli bilgisayarda da taşıma ve hedef kapasite "
                         "kısıtını göstermek için simüle hacimler kullanır.")

    # 2. Tarama / senaryo ayarları --------------------------------------------
    st.header("1 · Tarama ayarları" if mode == "Gerçek klasör" else "1 · Sentetik senaryo")
    if mode == "Gerçek klasör":
        default_root = str(DEMO_DIR) if DEMO_DIR.exists() else ""
        c1, c2 = st.columns(2)
        root1 = c1.text_input("Kaynak klasör (mutlak yol)", value=default_root,
                              placeholder=r"C:\Users\kullanici\Belgeler")
        root2 = c2.text_input("İkinci klasör (isteğe bağlı)", value="")
        if not DEMO_DIR.exists():
            st.caption("Örnek veri için: `python scripts/make_fixture.py` → "
                       f"`{DEMO_DIR}`")
        c3, c4, c5 = st.columns(3)
        prot_text = c3.text_area("Korunan klasörler (her satıra bir yol)",
                                 value=str(DEMO_DIR / "Önemli") if DEMO_DIR.exists() else "",
                                 help="Bu klasörlerdeki dosyalar için yalnızca KEEP önerilir.")
        low_text = c4.text_area("Düşük önemli klasörler (önem 1/9)",
                                value=str(DEMO_DIR / "Loglar") if DEMO_DIR.exists() else "")
        high_text = c5.text_area("Yüksek önemli klasörler (önem 9/9)", value="")
        max_files = st.number_input("En fazla dosya sayısı", 10, 20000, 2000, step=100)
        scan_key = _key("real", root1, root2, prot_text, low_text, high_text, max_files)
        if st.button("🔍 Tara", type="primary"):
            try:
                rules = [ImportanceRule(p, 1) for p in _lines(low_text)] + \
                        [ImportanceRule(p, 9) for p in _lines(high_text)]
                roots = [r for r in (root1.strip(), root2.strip()) if r]
                with st.spinner("Klasör taranıyor (salt okunur)…"):
                    res = analyze_folders(roots, protected_roots=_lines(prot_text),
                                          importance_rules=rules, max_files=int(max_files))
                    disks, dwarn = discover_disks()
                ss["scan"] = {"key": scan_key, "files": res.files, "disks": disks,
                              "source": res.source_volume_id, "warnings": res.warnings + dwarn,
                              "reasons": res.reason_codes, "skipped": res.skipped,
                              "roots": res.roots, "synthetic": False}
            except ScopeError as exc:
                st.error(f"Klasör kabul edilmedi: {exc.message}")
            except Exception as exc:  # user-facing message, details hidden by default
                st.error("Tarama sırasında beklenmeyen bir hata oluştu.")
                with st.expander("Teknik ayrıntı"):
                    st.code(repr(exc))
    else:
        c1, c2, c3 = st.columns(3)
        scen = c1.selectbox("Senaryo", ["Genel kullanıcı klasörü", "Greedy tuzağı (10 dosya)"])
        n_files = c2.selectbox("Dosya sayısı", [20, 100, 500, 1000], index=1,
                               disabled=scen != "Genel kullanıcı klasörü")
        data_seed = c3.number_input("Veri tohumu (seed)", 0, 10_000, 7)
        c4, c5, c6 = st.columns(3)
        d_free = c4.number_input("D: boş alan (GiB)", 0.0, 2000.0, 5.0, step=0.5)
        e_free = c5.number_input("E: boş alan (GiB, 0 = yok)", 0.0, 2000.0, 2.0, step=0.5)
        prot_frac = c6.slider("Korunan dosya oranı", 0.0, 0.9, 0.1, step=0.05)
        scan_key = _key("syn", scen, n_files, data_seed, d_free, e_free, prot_frac)
        if st.button("🧪 Senaryo oluştur", type="primary"):
            if scen.startswith("Greedy"):
                tp = greedy_trap_problem(int(data_seed))
                files, disks = tp.files, tp.disks
            else:
                files = synthetic_files(int(n_files), int(data_seed), prot_frac)
                frees = tuple(x for x in (d_free, e_free) if x > 0)
                disks = simulated_disks(frees)
            ss["scan"] = {"key": scan_key, "files": files, "disks": disks, "source": SOURCE_VID,
                          "warnings": ("Sentetik senaryo: değerler simülasyondur; gerçek disk "
                                       "değişikliği yoktur.",),
                          "reasons": (), "skipped": (), "roots": ("(sentetik)",), "synthetic": True}

    scan = ss.get("scan")
    if not scan:
        st.stop()
    if scan["key"] != scan_key:
        st.warning("Tarama ayarları değişti. Güncel sonuç için yeniden **Tara** / **Senaryo oluştur**.")

    files, disks, source = scan["files"], scan["disks"], scan["source"]

    # 3. Diskler ----------------------------------------------------------------
    st.header("2 · Diskler / hacimler")
    disk_rows = [{
        "Bağlama noktası": d.display_name,
        "Hacim kimliği": d.volume_id,
        "Toplam (GiB)": round(d.total_bytes / GIB, 2), "Boş (GiB)": round(d.free_bytes / GIB, 2),
        "Rol": "KAYNAK" if d.volume_id == source else ("Hedef olabilir" if d.eligible_destination else "Hedef değil"),
        "Kimlik kesin": "evet" if d.identity_confident else "HAYIR",
        "Diğer bağlama noktaları": ", ".join(d.aliases),
    } for d in disks]
    st.dataframe(pd.DataFrame(disk_rows), hide_index=True, use_container_width=True)
    if not any(d.volume_id == source for d in disks):
        st.caption(f"Kaynak hacim kimliği: `{source}` (bağlama noktası listede bulunamadı).")
    if any(not d.identity_confident for d in disks):
        st.warning("Bazı hacimlerin kimliği belirlenemedi; bu hacimlere taşıma önerilmez.")
    st.caption("Sürücü harfi ≠ fiziksel disk. Aynı hacimdeki klasörler arasında taşıma yer açmaz; "
               "bu yüzden yalnızca kaynaktan **farklı** hacimler hedef olabilir.")

    # 4. Analiz -----------------------------------------------------------------
    st.header("3 · Analiz")
    eligible = [f for f in files if f.eligible]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Dosya sayısı", len(files))
    m2.metric("Toplam boyut", fmt_bytes(sum(f.size_bytes for f in files)))
    m3.metric("İşlem yapılabilir", len(eligible))
    m4.metric("Potansiyel sıkıştırma (tahmini)", fmt_bytes(sum(f.estimated_compress_gain_bytes for f in eligible)))
    m5.metric("Uyarı", len(scan["warnings"]) + len(scan["skipped"]))
    for w in scan["warnings"]:
        st.warning(w)
    for code in scan["reasons"]:
        if code in REASON_TR:
            st.warning(f"`{code}` — {REASON_TR[code]}")
    with st.expander("Dosya meta verisi tablosu"):
        st.dataframe(pd.DataFrame([{
            "Dosya": f.name, "Boyut": fmt_bytes(f.size_bytes), "Önem": f"{f.importance}/9",
            "Durum": "uygun" if f.eligible else SKIP_TR.get(f.skip_reason or "", f.skip_reason),
            "Tahmini sıkıştırma kazancı": fmt_bytes(f.estimated_compress_gain_bytes),
            "Yol": f.path,
        } for f in files]), hide_index=True, use_container_width=True)
    if scan["skipped"]:
        with st.expander(f"Atlanan öğeler ({len(scan['skipped'])})"):
            st.dataframe(pd.DataFrame(scan["skipped"], columns=["Yol", "Neden"]), hide_index=True)

    # 5. Tercihler --------------------------------------------------------------
    st.header("4 · Tercihler")
    total_bytes = sum(f.size_bytes for f in files)
    c1, c2 = st.columns([2, 3])
    default_goal = round(min(total_bytes * 0.25, 3 * GIB) / GIB, 2) if total_bytes else 0.0
    goal_gib = c1.number_input("Kaynak hacimde açılacak **ek** boş alan (GiB)", 0.0,
                               max(1.0, round(total_bytes / GIB * 1.5, 2) + 1), default_goal,
                               step=0.01, format="%.2f",
                               help="Hedef, toplam boş alan değil; şu ankine EK olarak açılacak alandır. "
                                    "1 GiB = 1024³ bayt.")
    mib_txt = f"{goal_gib * 1024:,.0f}".replace(",", ".")
    c1.caption(f"= {mib_txt} MiB · taranan toplam {fmt_bytes(total_bytes)}")
    allow_compress = c2.checkbox("Sıkıştırmaya izin ver", True)
    allow_move = c2.checkbox("Başka hacme taşımaya izin ver", True)
    dest_options = {f"{d.display_name} — boş {fmt_bytes(d.free_bytes)}": d.volume_id
                    for d in disks if d.eligible_destination and d.volume_id != source}
    if allow_move and not dest_options:
        c2.warning("Kaynaktan farklı, yazılabilir ve güvenli bir hedef hacim yok; taşıma önerilemez. "
                   "Taşımayı denemek için **Sentetik senaryo** modunu kullanın.")
    chosen = c2.multiselect("Hedef hacimler", list(dest_options), default=list(dest_options),
                            disabled=not allow_move)
    prio_label = c2.selectbox("Öncelik", list(PRIORITY_TR), index=1,
                              help="Güvenlik: risk katsayısı yüksek · Hız: süre katsayısı yüksek")
    with st.expander("Gelişmiş: algoritma parametreleri"):
        a1, a2, a3, a4, a5 = st.columns(5)
        seed = a1.number_input("Tohum (seed)", 0, 1_000_000, 42)
        iterations = a2.number_input("İterasyon", 100, 100_000, 3000, step=500)
        t0 = a3.number_input("Başlangıç sıcaklığı T0", 0.01, 100.0, 5.0)
        cooling = a4.number_input("Soğuma oranı", 0.9, 0.99999, 0.995, format="%.5f")
        min_t = a5.number_input("Minimum sıcaklık", 1e-6, 1.0, 1e-4, format="%.6f")

    prefs = Preferences(
        source_volume_id=source, goal_bytes=int(round(goal_gib * GIB)),
        allow_compress=allow_compress, allow_move=allow_move,
        allowed_destination_volume_ids=tuple(dest_options[c] for c in chosen) if allow_move else (),
        protected_root_paths=(), priority=PRIORITY_TR[prio_label],
    )
    cfg = SAConfig(iterations=int(iterations), t0=float(t0), cooling=float(cooling), min_t=float(min_t))
    plan_key = _key(scan["key"], prefs, cfg, int(seed))

    # 6. Algoritmalar -----------------------------------------------------------
    st.header("5 · Plan oluştur")
    st.caption("Greedy, Tepe Tırmanma ve Benzetimli Tavlama **aynı adaylar ve aynı maliyet "
               "fonksiyonu** ile çalışır.")
    if st.button("🧠 Plan oluştur", type="primary"):
        try:
            with st.spinner("Ajan planları arıyor…"):
                problem = build_problem(files, disks, prefs, warnings=(), reason_codes=scan["reasons"])
                ss["comparison"] = {"key": plan_key, "cmp": run_all(problem, int(seed), cfg)}
        except Exception as exc:
            st.error("Planlama sırasında beklenmeyen bir hata oluştu.")
            with st.expander("Teknik ayrıntı"):
                st.code(repr(exc))

    comp = ss.get("comparison")
    if not comp:
        st.stop()
    if comp["key"] != plan_key:
        st.warning("Ayarlar değişti; gösterilen eski plan geçersiz. Lütfen **Plan oluştur**'a yeniden basın.")
        st.stop()
    problem, results = comp["cmp"].problem, comp["cmp"].results

    # 7. Öneriler ---------------------------------------------------------------
    st.header("6 · Karşılaştırma")
    rows = []
    for r in results:
        ev = r.evaluation
        changed = sum(1 for a in r.plan.values() if not a.endswith(":KEEP:-")) if r.feasible else 0
        rows.append({
            "Algoritma": ALGORITHM_NAMES_TR[r.algorithm],
            "Durum": STATUS_TR[r.status],
            "Tahmini kazanç": fmt_bytes(ev.gain_bytes) if r.feasible else "-",
            "Toplam maliyet": round(ev.total_cost, 3) if r.feasible else None,
            "Değişen dosya": changed,
            "Süre (ms)": round(r.duration_ms, 2),
            "Seed": r.seed if r.seed is not None else "-",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    feas = [r for r in results if r.feasible]
    if feas:
        best_cost = min(r.evaluation.total_cost for r in feas)
        winners = [ALGORITHM_NAMES_TR[r.algorithm] for r in feas
                   if r.evaluation.total_cost <= best_cost + 1e-9]
        st.success(f"En düşük maliyetli uygun plan ({best_cost:.3f}): **{', '.join(winners)}**"
                   + (" — eşit sonuç." if len(winners) > 1 else ".")
                   + " Bu sonuç bu girdi için geçerlidir; her çalıştırmada üstünlük garanti edilmez.")

    st.header("7 · Öneriler")
    tabs = st.tabs([ALGORITHM_NAMES_TR[r.algorithm] for r in results])
    for tab, r in zip(tabs, results):
        with tab:
            for line in explain_result(problem, r):
                st.write(line)
            if r.feasible:
                usage = dict(r.evaluation.destination_usage_bytes)
                if usage:
                    st.subheader("Hedef hacim kapasite etkisi")
                    st.dataframe(pd.DataFrame([{
                        "Hedef": volume_label(problem, d), "Gerekli (tahmini)": fmt_bytes(u),
                        "Kullanılabilir (güvenlik payı sonrası)": fmt_bytes(problem.capacities.get(d, 0)),
                        "Doluluk": f"%{100 * u / max(1, problem.capacities.get(d, 1)):.0f}",
                    } for d, u in sorted(usage.items())]), hide_index=True)
                acts = []
                for f, cands in zip(problem.files, problem.candidates):
                    c = next(x for x in cands if x.id == r.plan[f.file_id])
                    if c.kind != ActionKind.KEEP:
                        acts.append({"Dosya": f.name, "Eylem": c.kind.value,
                                     "Hedef": volume_label(problem, c.destination_volume_id),
                                     "Tahmini kazanç": fmt_bytes(c.source_gain_bytes),
                                     "Önem": f"{f.importance}/9", "Maliyet": round(c.total_cost, 3),
                                     "Gerekçe": explain_action(problem, f, c)})
                st.subheader(f"Önerilen işlemler ({len(acts)})")
                st.dataframe(pd.DataFrame(acts), hide_index=True, use_container_width=True)
                kept_prot = sum(1 for f in problem.files if f.protected)
                if kept_prot:
                    st.caption(f"{kept_prot} korunan dosya olduğu yerde bırakıldı (koruma kuralı).")
            hist = r.diagnostics.get("history") or []
            if hist:
                with st.expander("Arama geçmişi (yakınsama)"):
                    st.line_chart(pd.DataFrame([{
                        "iterasyon": h["iteration"], "mevcut enerji": h["current_energy"],
                        "en iyi uygun maliyet": h["best_feasible_cost"]} for h in hist]
                    ).set_index("iterasyon"))
                    d = r.diagnostics
                    st.caption(f"Kabul edilen geçiş: {d['accepted']} · kötüleşmeyi kabul: "
                               f"{d['uphill_accepted']} · kapasite nedeniyle reddedilen: "
                               f"{d['rejected_capacity']}")
            # 8. Dışa aktar
            c1, c2 = st.columns(2)
            c1.download_button("⬇️ CSV indir", to_csv(problem, r).encode("utf-8-sig"),
                               file_name=f"plan_{r.algorithm}.csv", mime="text/csv",
                               key=f"csv_{r.algorithm}")
            c2.download_button("⬇️ JSON rapor indir", to_json(problem, r).encode("utf-8"),
                               file_name=f"report_{r.algorithm}.json", mime="application/json",
                               key=f"json_{r.algorithm}")
            st.caption("⚠️ Raporlar dosya yollarını içerir ve kişisel bilgi barındırabilir; "
                       "paylaşmadan önce kontrol edin. Hiçbir veri dışarı gönderilmez.")

    with st.expander("Maliyet modeli (şeffaflık)"):
        st.json(problem.cost_model)
        st.caption("Katsayılar sezgiseldir; ölçülmüş olasılıklar değildir.")


if __name__ == "__main__":  # Streamlit runs the script as __main__
    main()
