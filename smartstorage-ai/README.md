# SmartStorage AI — Yerel Akıllı Depolama Optimizasyon Ajanı

> **Yerel / Önizleme modu — Dosyalar değiştirilmez.** SmartStorage AI yalnızca seçtiğiniz klasörlerin meta verisini okur ve bir **öneri planı** üretir. Taşıma, sıkıştırma veya silme yapmaz. Gösterilen tüm kazançlar **tahminidir**.

Yapay Zekâ dersi projesi · 14 günlük MVP · Python 3.11/3.12 · Windows 11 hedefli (Linux/macOS'ta da çalışır, garanti verilmez).
Teknik şartname: [`docs/SPEC_v2.md`](docs/SPEC_v2.md) (v1'e göre yapılan 18 değişiklik ve gerekçeleri dosyanın başındaki tabloda).

---

## 1. Hangi problemi çözüyoruz?

Disk dolduğunda kullanıcı büyük dosyaları elle arar, hangisinin önemli olduğunu düşünür ve hangisini nereye taşıyacağına tek tek karar verir. Dosyaları boyuta göre sıralamak; **önemi, riski, işlem süresini ve hedef disk kapasitesini aynı anda** hesaba katmaz.

SmartStorage AI bu kararları **kısıtlı bir optimizasyon problemi** olarak ele alır:

> *“C: hacminde **ek** 3 GiB yer açmak istiyorum. `Önemli/` klasörüme dokunma. Sıkıştırmaya ve D:'ye taşımaya izin veriyorum. Silme yok.”*

Ajan, **her dosya için** tek bir eylem seçer:

| Eylem | Kaynakta tahmini kazanç | Hedefte kullanılan alan |
|---|---|---|
| **KEEP** (olduğu yerde bırak) | 0 | 0 |
| **COMPRESS** (kayıpsız sıkıştır) | tahmini sıkıştırma kazancı | 0 |
| **MOVE** (başka hacme taşı) | dosya boyutu | dosya boyutu |
| **DELETE** (yalnızca yeni arayüzde isteğe bağlı öneri) | dosya boyutu | 0 |

Amaç **en çok dosyayı değiştirmek değil**, hedefe **en düşük toplam müdahale maliyetiyle** ulaşmaktır. Uygun plan yoksa sistem bunu dürüstçe söyler (`PROVEN_INFEASIBLE` veya `NO_FEASIBLE_FOUND`).

**Temel sınırlamalar:** Sistem yalnızca öneri üretir; kazançlar tahmindir; sadece seçilen klasörler taranır (varsayılan en fazla 2000 dosya).

## 2. Bu neden bir yapay zekâ projesi? (Model eğitimi yok!)

Yapay zekâ yalnızca model eğitimi değildir. Bu proje dersin **klasik yapay zekâ** konularını uygular: **rasyonel ajan**, **durum uzayı**, **amaç fonksiyonu**, **kısıtlar**, **sezgisel ve yerel arama**. Sinir ağı, LLM, eğitim verisi veya bulut API'si **yoktur**.

### “Ajan nerede?” — PEAS modeli

| | |
|---|---|
| **P**erformans | Kaynak hacimde hedef ek boş alan; minimum toplam müdahale maliyeti; korunan dosyalara ve kapasitelere uyum; açıklanabilir öneriler |
| **E**nvironment (çevre) | Yerel dosya sistemi meta verisi, kaynak/hedef hacimler, kullanıcı tercihleri. Kısmen gözlenebilir: dosyanın gerçek önemi ve gerçek sıkıştırılabilirliği bilinmez |
| **A**ctuators (eyleyiciler) | KEEP / COMPRESS / MOVE / isteğe bağlı DELETE **öneri** planı, CSV/JSON rapor. MVP'de diskte değişiklik yoktur |
| **S**ensors (algılayıcılar) | Klasör tarama, dosya meta verisi, sınırlı içerik örneklemesi, `psutil` hacim bilgisi, kullanıcı girdileri |

Döngü: **algıla** (tara) → **düşün** (aday eylemleri üret, maliyetleri hesapla, ara) → **eyle** (planı öner ve gerekçelendir).

### Problem formülasyonu

- **Durum:** Her dosyaya bir eylem atanmış tam plan (1000 dosya → 1000 karar).
- **Hedef testi:** izinlere uyum + her hedef hacimde kapasite + `kazanç ≥ hedef`.
- **Amaç:** toplam maliyeti en aza indirmek.
- **Neden sezgisel arama?** Problem, **0/1 sırt çantası (knapsack) probleminin genellemesidir** (dosya başına birden çok seçenek, birden çok hedef kapasitesi). Bu yüzden **NP-zordur**. Tam arama yalnızca çok küçük örneklerde (≤ 8 dosya) mümkündür; onu doğrulama için kullanırız.

### Üç algoritma (aynı girdi, aynı maliyet fonksiyonu)

1. **Açgözlü (Greedy)** — temel yöntem. Eylemleri `kazanç / maliyet` oranına göre sıralar ve hedefe ulaşana kadar seçer. Ardından gereksiz eylemleri geri alan bir **budama** adımı uygular. Çok hızlıdır ama “miyop”tur, optimumu garanti etmez.
2. **Tepe Tırmanma (Hill Climbing)** — SA ile aynı komşuluk ve aynı enerji, ama **sıcaklık 0**: yalnızca iyileştiren adımları kabul eder. Yerel optimuma takılabilir. Sıcaklığın katkısını ölçmek için **ablasyon** amaçlı eklendi.
3. **Benzetimli Tavlama (Simulated Annealing)** — Greedy planından başlar; 1–2 dosyanın eylemini değiştiren komşular üretir. Daha kötü bir komşuyu `exp(-Δ/T)` olasılığıyla kabul ederek yerel optimumdan kaçar. Sıcaklık `T ← T · 0,995` ile düşer. Hedefe göre **onarım** hamlesi içerir; en iyi **uygun** planı ayrıca saklar. `seed` ile tekrarlanabilir.

## 3. Kurulum ve çalıştırma (Windows)

Python 3.11 veya 3.12 gerekir: `python --version`

**PowerShell:**
```powershell
cd smartstorage-ai
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\make_fixture.py
streamlit run app.py
```
PowerShell betik izni hatası alırsanız sistem genelinde izinleri gevşetmeyin; **CMD** kullanın.

**CMD:**
```bat
cd smartstorage-ai
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\make_fixture.py
streamlit run app.py
```

Tarayıcıda `http://localhost:8501` açılır. Uygulama `.streamlit/config.toml` ile **yalnızca bu bilgisayara** (`localhost`) bağlanır ve Streamlit telemetrisi kapalıdır. Aynı Wi-Fi'deki biri uygulamanıza erişemez.

Sade dosya tarama ve planlama arayüzünü çalıştırmak için proje kökünde `streamlit run presentation\app.py` komutunu kullanın. Tarama sonrasında klasörler ağaç görünümünde listelenir. Her dosya önem puanını kapsayan klasörden devralır; bir klasör puanını değiştirmek alt öğelere uygulanır, tek bir dosyayı veya alt klasörü ayrıca değiştirebilir ve **Inherit** ile tekrar devralmaya alabilirsiniz. Planlama bu bireysel puanları kullanır. Hedef boş alanı girin, arşivleme/sıkıştırma, taşıma ve silme önerilerine izin verin; **Keep** her zaman kullanılabilir. Test aşamasında taşıma için aynı sürücü dâhil herhangi bir var olan klasör seçilebilir. Aynı sürücü hedefi ayrı bir simüle edilmiş hedef olarak planlanır; gerçek bir taşıma aynı sürücüde fiziksel olarak boş alan açmaz. Hiçbir dosya taşınmaz veya silinmez. Uygulama Greedy, Hill Climbing ve Simulated Annealing planlarını karşılaştırır.

Arşivleme kazancı örneklemeye dayalı tahmindir; gerçek bir arşiv oluşturulmaz. Taşıma ve silme yalnızca planda önerilir; hiçbir dosya değiştirilmez. Eski arayüz `streamlit run app.py` ile değişmeden kullanılabilir.

## 4. Demo senaryosu (sunum için)

`python scripts/make_fixture.py` komutu `test_data/demo_kullanici/` altında yaklaşık 140 MiB **tamamen sentetik** dosya üretir: loglar, CSV/JSON, rastgele “video/foto”, ZIP, `.db`/`.exe`, boş dosya, Türkçe karakterli adlar ve korunacak `Önemli/` klasörü. Kişisel veri içermez.

1. **Gerçek klasör** modu: Yol ve `Önemli` koruması otomatik dolar → **Tara**. Analiz bölümünde `.db`/`.exe` dosyalarının “riskli tür” nedeniyle yalnızca KEEP olduğunu gösterin.
2. Hedef olarak örn. **0,03 GiB (~31 MiB)** girin → **Plan oluştur** → üç algoritmanın karşılaştırması ve Türkçe gerekçeler.
3. **Sıkıştırmaya izin ver** kutusunu kapatın → plan geçersizleşir; yeniden oluşturun → tek diskli makinede `PROVEN_INFEASIBLE` (taşıma hedefi yok).
4. **Sentetik senaryo (demo)** modu → 100 dosya, D: 5 GiB, E: 2 GiB → hedef 3 GiB → MOVE önerileri ve **hedef kapasite** tablosu.
5. D: boş alanını **0,3 GiB** yapın, sıkıştırmayı kapatın → sistem hedef diski aşan bir taşıma **önermez**, imkânsızlığı kanıtla açıklar.
6. **Greedy tuzağı (10 dosya)** senaryosu (seed 6) → Greedy'nin miyopluğu; SA'nın daha düşük maliyetli plan bulması. **Gelişmiş** panelinden seed değiştirerek tekrarlanabilirliği gösterin.
7. Hedefi çok büyük yapın (örn. 500 GiB) → `HEDEF KANITLANABİLİR ŞEKİLDE İMKÂNSIZ` ve neden kodları.
8. CSV/JSON raporu indirin (dosyalar değişmez).

> Tek diskli bir dizüstünde gerçek klasör modunda MOVE önerisi çıkmaması **doğru davranıştır**. Aynı hacim içinde taşıma yer açmaz. Taşımayı göstermek için sentetik modu kullanın.

## 5. “Ek boş alan” ve birimler

- Hedef, **toplam** boş alan değil, şu ankine **ek** olarak açılacak alandır. C:'de 10 GiB boş varsa ve 3 GiB girerseniz, hedef ~13 GiB boş alandır.
- İçeride her şey **bayt** (tam sayı) olarak tutulur. Arayüz ikili birimleri kullanır: **1 KiB = 1024 B**, **1 MiB = 1024² B**, **1 GiB = 1024³ B**. Windows Gezgini “GB” yazar ama aslında GiB gösterir; disk üreticileri ise GB = 10⁹ kullanır.
- Kazanç **mantıksal dosya boyutundan** tahmin edilir. Diskte ayrılan gerçek alan küme (cluster) artığı, NTFS sıkıştırması veya seyrek (sparse) dosyalar nedeniyle farklı olabilir.

## 6. Güvenlik: dry-run, otomatik silme yok

- Kod tabanında yazma/taşıma/silme çağrısı **yoktur**; bunu bir test kontrol eder (`tests/test_app_smoke.py`). Dosyalar yalnızca okunur. Sıkıştırma tahmini için dosya başına en fazla 256 KiB örnek okunur.
- **Taranmayan alanlar:** hacim kökü (`C:\`), Windows, Program Files, ProgramData, AppData, Geri Dönüşüm Kutusu, System Volume Information, sanal ortamlar, `.git`, uygulamanın kendi klasörü. Tek istisna `test_data/` klasörüdür.
- Sembolik bağlantı/junction/reparse point izlenmez. Başka bir hacme bağlanmış klasöre girilmez. Yollar `os.path.commonpath` ile karşılaştırılır (`C:\Data`, `C:\Database`'i kapsamaz).
- **Yalnızca KEEP uygulanan dosyalar:**
  - korunan klasörler;
  - riskli türler (`.db .sqlite .pst .exe .dll .sys .vhdx .lock` …);
  - **sabit bağlantılı** dosyalar (taşımak yer açmaz);
  - **OneDrive gibi bulut yer tutucuları** (içeriği okunmaz, aksi hâlde dosya buluttan indirilirdi);
  - son 10 dakikada değişmiş, boş veya okunamayan dosyalar;
  - tarama ile tahmin arasında değişen dosyalar.
- Tarama ve kazanç değerleri bir **anlık görüntüdür**. Gelecekte bir “uygula” modülü yazılırsa, her işlemden önce yeniden doğrulama gerekir.

## 7. Hacim kimliği ve temkinli MOVE

**Sürücü harfi ≠ fiziksel disk.** Önemli olan **kaynak hacimde** açılan alandır.

- Hacim kimliği `os.stat(yol).st_dev` ile belirlenir. Bu, Windows'ta birim seri numarasıdır. Dosya ve hacim aynı fonksiyonla karşılaştırılır.
- Aynı hacmin birden çok bağlama noktası tek kapasite olarak sayılır. Kimliği belirlenemeyen, salt okunur veya çıkarılabilir hacimler hedef olamaz.
- Aynı hacim içinde taşıma **hiçbir zaman** önerilmez.
- **Kapasite kısıtı (tüm plan için toplam):** her hedef hacim `d` için:
  `Σ taşınan bayt ≤ boş(d) − max(256 MiB, boş(d) × 0,05)`
- Hedefteki boş alan kaynağın kazancına eklenmez. Taşıma toplam veriyi azaltmaz, yalnızca kaynağı boşaltır.

## 8. Formüller ve maliyet modeli

```
toplam_maliyet = w_impact · önem · etki + w_time · dakika + w_risk · risk + w_access · erişim_cezası
```

| Sabit | KEEP | COMPRESS | MOVE |
|---|---|---|---|
| etki | 0 | 0,6 | 0,4 |
| risk | 0 | 0,3 | 0,2 |
| erişim cezası | 0 | 1,0 (kullanmak için açılmalı) | 0,5 (konum değişir) |
| nominal hız | – | 50 MiB/s | 100 MiB/s (+0,05 s/dosya) |

| Öncelik | w_impact | w_time | w_risk | w_access |
|---|---|---|---|---|
| Güvenlik | 1,0 | 0,5 | 4,0 | 1,5 |
| Dengeli | 1,0 | 1,0 | 2,0 | 1,0 |
| Hız | 1,0 | 2,0 | 1,0 | 0,5 |

**Önem değerleri:** 1 (düşük), 5 (normal, varsayılan), 9 (yüksek). Önem **yalnızca kullanıcının klasör kurallarından** gelir. Dosya yaşına veya adına bakılarak tahmin edilmez. Korunan klasör bir maliyet değil, **kesin kısıttır**.

**SA enerjisi:**
```
enerji(P) = maliyet(P) + α · max(0, hedef − kazanç(P)) / hedef
α = 2 · r_max · hedef      (r_max = adaylar içindeki en yüksek maliyet/kazanç oranı)
```
Bu kalibrasyonla, hedefi bozan bir adım hiçbir zaman enerjiyi düşürmez. Kapasiteyi aşan komşular doğrudan reddedilir.

**Üst sınır (imkânsızlık kanıtı):**
- `UB = Σ dosya başına en yüksek kazanç`
- `UB_kap = Σ sıkıştırma kazancı + min(toplam hedef kapasite, Σ taşınabilir (boyut − sıkıştırma kazancı))`

`min(UB, UB_kap) < hedef` ise sonuç **kanıtlanmış imkânsız**dır. Aksi hâlde uygun plan bulunamazsa sonuç yalnızca “arama bulamadı” olarak raporlanır; bu bir kanıt değildir.

> ⚠️ Katsayılar **sezgiseldir**, ölçülmüş olasılıklar değildir. Sıkıştırma tahmini dosyanın başından, ortasından ve sonundan alınan örneklere `zlib` (seviye 6) uygulanarak yapılır ve %2 + 4 KiB pay eklenir. Örnekler tüm dosyayı temsil etmeyebilir. Zaten sıkıştırılmış türler (`.zip .jpg .mp4 .pdf .docx` …) atlanır. 1 MiB'den veya dosyanın %3'ünden küçük kazançlar için COMPRESS önerilmez.

## 9. Testler ve deney

```bash
pytest -q                                 # tüm testler
python scripts/benchmark.py               # tam deney (~20 s): results/ altına CSV + grafik
python scripts/benchmark.py --quick       # hızlı sürüm
```

**Test durumu (bu depoda çalıştırıldı):** `pytest -q` → **72 passed**. Kapsam: tarayıcı (boş kök, iç içe kökler, Türkçe karakterler, izin hatası, symlink, sabit bağlantı, bulut yer tutucu, dosyaların değişmediği), diskler, sıkıştırma tahmini, eylemler, puanlama/kapasite, Greedy, SA/HC, kaba kuvvet doğrulaması, CSV/JSON (formül enjeksiyonu dâhil), uçtan uca akış ve arayüzün içe aktarma testi.
Arayüz, Playwright ile tarayıcıda iki modda (gerçek klasör + sentetik) elle sürülerek de denendi. Otomatik bir UI test paketi **yoktur**.

**Deney tasarımı:** 20/100/500/1000 dosya; 1/2/4 hacim; 0/1/3 GiB hedef. Ayrıca şu senaryolar var: sıkıştırma kapalı, taşıma kapalı, hedef dolu, farklı kapasiteli çoklu hedef, ulaşılamaz hedef, öncelik ön ayarları, 20 “Greedy tuzağı” ve 20 küçük (tam aranabilir) senaryo. Greedy bir kez, HC ve SA her senaryoda 10 farklı seed ile çalışır (toplam 1808 koşum).

**Ölçülen sonuçlar** (`results/benchmark_summary.csv`, 3000 iterasyon):

| Senaryo ailesi | Greedy | Hill Climbing | Simulated Annealing |
|---|---|---|---|
| Greedy tuzakları: optimumdan ortalama sapma | %25,8 | %11,7 | **%1,8** |
| Greedy tuzakları: optimumu bulan koşum | 4/20 | 116/200 | **156/200** |
| Küçük senaryolar: optimumdan ortalama sapma | %17,0 | %4,6 | **%0,6** |
| Küçük senaryolar: optimumu bulan koşum | 5/12 | 106/130 | **127/130** |

**Nasıl okunmalı?**
- **Uygunluk oranı** her zaman paydasıyla birlikte verilir. Ortalama maliyet yalnızca uygun koşumlar üzerinden hesaplanır.
- Küçük senaryolarda bir örnekte Greedy uygun plan **bulamadı**, SA ise buldu. Bu yüzden payda Greedy için 12, diğerleri için 13 senaryo × 10 seed'dir.
- 500–1000 dosyalık rastgele senaryolarda SA ile HC benzer sonuç verir ve ikisi de Greedy'den biraz iyidir. SA'nın her durumda üstün olduğu **iddia edilmez**.
- Çalışma süresi: Greedy < 1 ms, SA/HC 3000 iterasyonda ~10 ms (1000 dosya dâhil).

Grafikler: `results/cost_gap_comparison.png`, `results/runtime_vs_n_files.png`, `results/sa_convergence.png`.

## 10. Bilinen sınırlamalar ve yol haritası

**Sınırlamalar:**
- Gerçek işlem uygulanmaz.
- Sıkıştırma kazancı örneklemeye dayanır.
- Maliyet katsayıları sezgiseldir.
- Windows'ta hacim kimliği `st_dev` ile belirlenir; ağ sürücüleri ve özel bağlama durumları test edilmedi.
- Tarama varsayılan olarak 2000 dosyayla sınırlıdır.
- Streamlit tarayıcıda yerel klasör seçici açamadığı için yol metin olarak girilir.

**Yol haritası (MVP dışı):**
- yalnızca test verisinde, doğrulamalı (checksum) kopyala-sıkıştır demosu;
- yinelenen dosya raporu (asla otomatik silme yok);
- kayıtlı tercih profilleri;
- dosya bazında önem düzenleyici;
- ayrı bir güvenlik incelemesinden sonra geri alınabilir (transactional) gerçek uygulama modu.

## Proje yapısı

```
smartstorage-ai/
  app.py                 Streamlit arayüzü (Türkçe)
  smartstorage/
    models.py            değişmez veri sınıfları, durum/neden kodları
    pathutil.py          commonpath tabanlı yol kontrolleri
    scanner.py           salt okunur tarama, güvenli kapsam
    disks.py             psutil hacim keşfi, kimlik, kapasite
    estimate.py          sınırlı zlib sıkıştırma tahmini
    importance.py        klasör önem kuralları, koruma
    actions.py           aday üretimi, problem kurulumu
    scoring.py           maliyet, değerlendirme, üst sınır, enerji
    greedy.py            Greedy + budama
    annealing.py         Simulated Annealing + Hill Climbing
    exact.py             küçük örnekler için kaba kuvvet
    explain.py           Türkçe açıklamalar (şablon, LLM yok)
    serialize.py         CSV / JSON rapor
    sample_data.py       sentetik senaryolar
    pipeline.py          uçtan uca yardımcılar
  scripts/make_fixture.py, scripts/benchmark.py
  tests/                 pytest
  docs/                  şartname v1/v2 ve proje belgeleri
  results/               deney özeti ve grafikler
```

**Akademik dürüstlük:** Bu proje sinir ağı veya pekiştirmeli öğrenme içermez; klasik, aramaya dayalı bir akıllı ajandır. Risk puanları istatistiksel olarak ölçülmemiştir ve önerilen işlemlerin tam olarak tahmin edilen baytı açacağı garanti edilmez.
