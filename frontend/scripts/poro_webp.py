"""Converte as camadas extraídas do PSD (poro-layers/) em webp reduzido (0.4x)
para public/assets/poro/. Roda: uv run --with pillow python scripts/poro_webp.py"""

import json
from pathlib import Path

from PIL import Image

src = Path("scripts/poro-layers")
dst = Path("public/assets/poro")
dst.mkdir(parents=True, exist_ok=True)
m = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
total = 0.0
for layer in m["layers"]:
    if layer["slug"] == "plano-de-fundo":  # vazio (alpha 0) — não embarca
        continue
    im = Image.open(src / layer["file"]).convert("RGBA")
    w, h = im.size
    im = im.resize((max(1, round(w * 0.4)), max(1, round(h * 0.4))), Image.LANCZOS)
    out = dst / (layer["slug"] + ".webp")
    im.save(out, "WEBP", quality=86, method=6)
    kb = out.stat().st_size / 1024
    total += kb
    print(f"{layer['slug']:20s} {im.size} {kb:6.1f} KB")
print(f"TOTAL: {total:.0f} KB")
