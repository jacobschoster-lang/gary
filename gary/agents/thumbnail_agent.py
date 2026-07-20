"""Thumbnail agent (issue #5).

Designs a YouTube thumbnail spec from a topic and renders it as an SVG (no image
libraries required, so it runs anywhere). Colors are derived deterministically
from the topic so results are stable. Swap ``render_svg`` for a real image
generator (PIL/AI) when ready.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_PALETTES = [
    ("#0b1e3f", "#ffcc00"),
    ("#1a0b3f", "#ff5c8a"),
    ("#052e2b", "#22e0a1"),
    ("#3f1d0b", "#ff8a3d"),
    ("#2b0b3f", "#8a5cff"),
]


@dataclass
class ThumbnailSpec:
    topic: str
    headline: str
    bg_color: str
    accent_color: str
    badge: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThumbnailAgent:
    max_words: int = 5

    def design(self, topic: str) -> ThumbnailSpec:
        topic = (topic or "").strip()
        if not topic:
            raise ValueError("topic must not be empty")

        digest = hashlib.sha256(topic.encode("utf-8")).digest()
        bg, accent = _PALETTES[digest[0] % len(_PALETTES)]
        headline = " ".join(topic.upper().split()[: self.max_words])
        badge = "SHOCKING" if digest[1] % 2 else "BREAKING"

        return ThumbnailSpec(
            topic=topic,
            headline=headline,
            bg_color=bg,
            accent_color=accent,
            badge=badge,
        )

    def render_svg(self, spec: ThumbnailSpec, width: int = 1280, height: int = 720) -> str:
        font = 'font-family="Arial, sans-serif"'
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{spec.bg_color}"/>',
            f'<rect x="0" y="0" width="18" height="{height}" fill="{spec.accent_color}"/>',
            f'<rect x="60" y="80" rx="10" width="260" height="70" fill="{spec.accent_color}"/>',
            f'<text x="190" y="130" {font} font-size="42" font-weight="bold" '
            f'fill="{spec.bg_color}" text-anchor="middle">{spec.badge}</text>',
            f'<text x="60" y="330" {font} font-size="90" font-weight="bold" '
            f'fill="#ffffff">{_wrap(spec.headline)}</text>',
            f'<text x="60" y="{height - 60}" {font} font-size="34" '
            f'fill="{spec.accent_color}">Stickfigure Finance</text>',
            "</svg>",
        ]
        return "\n".join(parts)

    def render_png(self, spec: ThumbnailSpec, width: int = 1280, height: int = 720) -> Image.Image:
        img = Image.new("RGB", (width, height), spec.bg_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 18, height), fill=spec.accent_color)
        draw.rounded_rectangle((60, 80, 320, 150), radius=10, fill=spec.accent_color)
        font = ImageFont.load_default()
        draw.text((190, 105), spec.badge, fill=spec.bg_color, anchor="mm", font=font)
        y = 250
        for line in spec.headline.split():
            draw.text((60, y), line, fill="#ffffff", font=font)
            y += 70
        draw.text((60, height - 60), "Stickfigure Finance", fill=spec.accent_color, font=font)
        return img

    def save_png(self, spec: ThumbnailSpec, path: str | Path) -> str:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.render_png(spec).save(out, format="PNG")
        return str(out)


def _wrap(text: str, per_line: int = 14) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > per_line and current:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    return "".join(
        f'<tspan x="60" dy="{0 if i == 0 else 100}">{line}</tspan>'
        for i, line in enumerate(lines)
    )
