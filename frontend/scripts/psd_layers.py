"""Extrai camadas nomeadas de um PSD para PNGs + manifest.json (rig do Poro).

Uso (da raiz do repo; usa env efêmero do uv, nada é instalado no projeto):

    uv run --with psd-tools --with pillow python frontend/scripts/psd_layers.py \
        "C:/Users/Clesio/Downloads/poro.psd" frontend/scripts/poro-layers

Saída em <outdir>:
    manifest.json  — canvas {w,h} + por camada: name, slug, arquivo, bounds
                     (left/top/right/bottom no espaço do canvas), size, opacity,
                     visible, blend_mode, group (caminho de grupos "a/b")
    <slug>.png     — recorte RGBA da camada (posição real preservada no manifest)

Camadas ocultas também saem (visible=false) — decisão de uso fica pro rig.
Grupos são percorridos recursivamente; camadas vazias (bbox nulo) são puladas.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

from psd_tools import PSDImage


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "layer"


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    psd_path, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)

    psd = PSDImage.open(psd_path)
    layers: list[dict] = []
    seen: dict[str, int] = {}

    def walk(node, group_path: str) -> None:
        for layer in node:
            if layer.is_group():
                walk(layer, f"{group_path}{layer.name}/")
                continue
            bbox = layer.bbox  # (left, top, right, bottom) no espaço do canvas
            if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                print(f"  [pulada: vazia] {group_path}{layer.name}")
                continue
            slug = slugify(f"{group_path}{layer.name}")
            # nomes duplicados ganham sufixo -2, -3...
            seen[slug] = seen.get(slug, 0) + 1
            if seen[slug] > 1:
                slug = f"{slug}-{seen[slug]}"
            img = layer.composite()  # PIL RGBA já com máscaras/efeitos aplicados
            img.save(outdir / f"{slug}.png")
            layers.append(
                {
                    "name": layer.name,
                    "slug": slug,
                    "file": f"{slug}.png",
                    "group": group_path.rstrip("/"),
                    "bounds": {
                        "left": bbox[0],
                        "top": bbox[1],
                        "right": bbox[2],
                        "bottom": bbox[3],
                    },
                    "size": {"w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]},
                    "opacity": layer.opacity,
                    "visible": layer.visible,
                    "blend_mode": str(layer.blend_mode),
                }
            )
            print(f"  [ok] {slug}  {bbox}")

    walk(psd, "")

    manifest = {
        "source": psd_path.name,
        "canvas": {"w": psd.width, "h": psd.height},
        "layers": layers,  # ordem = ordem de pintura do PSD (fundo → topo)
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(layers)} camadas -> {outdir / 'manifest.json'}")


if __name__ == "__main__":
    main()
