"""Create a deterministic, fully synthetic demo folder (no personal data).

Default output: <project>/test_data/demo_kullanici  (the only project folder
the scanner accepts). Refuses to write into a non-empty folder that it did
not create itself.

Usage:  python scripts/make_fixture.py [--out PATH] [--seed 42] [--scale 1.0]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from random import Random

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "test_data" / "demo_kullanici"
MARKER = ".smartstorage_fixture"
MIB = 1024 ** 2

WORDS = ("istek yanıt kullanıcı oturum disk dosya hata uyarı bilgi bağlantı sunucu "
         "istemci önbellek kayıt işlem süre başarılı başarısız tekrar zaman aşımı").split()


def _text_lines(rng: Random, n_lines: int) -> list[str]:
    levels = ["INFO", "INFO", "INFO", "DEBUG", "WARN", "ERROR"]
    return [f"{rng.choice(levels)} modül={rng.randint(1, 40)} " + " ".join(rng.choice(WORDS)
            for _ in range(rng.randint(5, 12))) + f" id={rng.randint(1000, 99999)}"
            for _ in range(n_lines)]


def write_text(path: Path, size: int, rng: Random) -> None:
    pool = _text_lines(rng, 3000)
    t = 1_700_000_000
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        written = 0
        while written < size:
            t += rng.randint(0, 5)
            line = f"2024-{(t // 86400) % 12 + 1:02d}-{(t // 3600) % 28 + 1:02d} {t % 86400:05d} {rng.choice(pool)}\n"
            fh.write(line)
            written += len(line.encode("utf-8"))


def write_csv(path: Path, size: int, rng: Random) -> None:
    cities = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Konya", "Eskişehir"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("tarih,şehir,ürün,adet,tutar\n")
        written = 0
        while written < size:
            line = (f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},{rng.choice(cities)},"
                    f"ürün_{rng.randint(1, 300)},{rng.randint(1, 50)},{rng.randint(10, 9999)}.{rng.randint(0, 99):02d}\n")
            fh.write(line)
            written += len(line.encode("utf-8"))


def write_json(path: Path, size: int, rng: Random) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("[\n")
        written = 2
        while written < size:
            line = (f'  {{"sensor": "s{rng.randint(1, 60)}", "deger": {rng.random():.4f}, '
                    f'"birim": "°C", "durum": "{rng.choice(["normal", "yüksek", "düşük"])}"}},\n')
            fh.write(line)
            written += len(line.encode("utf-8"))
        fh.write('  {"son": true}\n]\n')


def write_random(path: Path, size: int, rng: Random, header: bytes = b"") -> None:
    with open(path, "wb") as fh:
        fh.write(header)
        left = size - len(header)
        while left > 0:
            n = min(left, MIB)
            fh.write(rng.randbytes(n))
            left -= n


def build(out: Path, seed: int = 42, scale: float = 1.0) -> list[Path]:
    rng = Random(seed)
    s = lambda mib: max(1, int(mib * scale * MIB))  # noqa: E731
    plan = [
        ("Belgeler/rapor_2024.txt", "text", 3), ("Belgeler/çalışma_notları_ğüşiöç.txt", "text", 2),
        ("Belgeler/özet.txt", "text", 0.05),
        ("Loglar/uygulama_01.log", "text", 15), ("Loglar/uygulama_02.log", "text", 9),
        ("Loglar/uygulama_03.log", "text", 6), ("Loglar/eski/sunucu_2023.log", "text", 12),
        ("Veriler/satışlar.csv", "csv", 12), ("Veriler/ölçümler.json", "json", 8),
        ("Medya/tatil_videosu.mp4", "random", 25), ("Medya/konser.mkv", "random", 18),
        ("Medya/foto_001.jpg", "random", 3), ("Medya/foto_002.jpg", "random", 4),
        ("Arşiv/yedek_2022.zip", "random", 10),
        ("Önemli/sözleşme.txt", "text", 3), ("Önemli/aile_fotoğrafları/doğum_günü.jpg", "random", 5),
        ("Program/ayarlar.db", "random", 2), ("Program/kurulum.exe", "random", 3),
        ("Boş/bos_dosya.txt", "empty", 0),
    ]
    created = []
    old = time.time() - 30 * 86400  # 30 days old: not "recently modified"
    for rel, kind, mib in plan:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        size = s(mib) if mib else 0
        if kind == "text":
            write_text(p, size, rng)
        elif kind == "csv":
            write_csv(p, size, rng)
        elif kind == "json":
            write_json(p, size, rng)
        elif kind == "random":
            write_random(p, size, rng)
        else:
            p.write_bytes(b"")
        os.utime(p, (old, old))
        created.append(p)
    (out / "Boş" / "alt_klasör").mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("SmartStorage AI sentetik test verisi\n", encoding="utf-8")
    os.utime(out / MARKER, (old, old))
    return created


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SmartStorage AI sentetik demo klasörü oluşturur.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0, help="boyut çarpanı (ör. 0.1 hızlı test)")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not (out / MARKER).exists():
        print(f"HATA: {out} boş değil ve bu betik tarafından oluşturulmamış. Başka bir klasör seçin.")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    files = build(out, args.seed, args.scale)
    total = sum(p.stat().st_size for p in files)
    print(f"Oluşturuldu: {out}")
    print(f"{len(files)} dosya, toplam {total / MIB:.1f} MiB")
    print(f"Korunacak klasör önerisi: {out / 'Önemli'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
