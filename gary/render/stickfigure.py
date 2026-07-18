"""Stick-figure drawing + finance props (for @StickfigureFinance).

Everything is drawn with Pillow primitives (circles + lines) so a figure can be
posed per-frame to create animation. Angles are in degrees, measured clockwise
from straight-down for limbs, so 0 = hanging down, 90 = pointing right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import ImageDraw

WHITE = (245, 245, 245)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
GOLD = (250, 204, 21)


def _tip(x: float, y: float, angle_deg: float, length: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return (x + length * math.sin(rad), y + length * math.cos(rad))


@dataclass
class Pose:
    # Angles are degrees measured clockwise from straight-DOWN (0 = hanging down,
    # 90 = pointing right, 180 = straight up, -90/270 = pointing left).
    left_arm: float = -30.0   # hangs down, angled slightly left
    right_arm: float = 30.0   # hangs down, angled slightly right
    left_leg: float = -12.0
    right_leg: float = 12.0
    lean: float = 0.0  # head/torso tilt in degrees


def draw_stick_figure(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    scale: float = 1.0,
    pose: Pose | None = None,
    color: tuple[int, int, int] = WHITE,
) -> None:
    """Draw a stick figure whose feet sit near (cx, cy)."""
    pose = pose or Pose()
    w = max(2, int(6 * scale))

    head_r = 26 * scale
    torso = 70 * scale
    arm = 46 * scale
    leg = 60 * scale

    hip = (cx, cy - leg)
    shoulder = (hip[0] + torso * math.sin(math.radians(pose.lean)),
                hip[1] - torso * math.cos(math.radians(pose.lean)))
    head_center = (shoulder[0] + head_r * math.sin(math.radians(pose.lean)),
                   shoulder[1] - head_r * math.cos(math.radians(pose.lean)))

    # Arms attach a little below the shoulder so a raised arm clears the head.
    arm_joint = (shoulder[0] + 0.20 * (hip[0] - shoulder[0]),
                 shoulder[1] + 0.20 * (hip[1] - shoulder[1]))

    # Head
    draw.ellipse(
        [head_center[0] - head_r, head_center[1] - head_r,
         head_center[0] + head_r, head_center[1] + head_r],
        outline=color, width=w,
    )
    # Torso
    draw.line([shoulder, hip], fill=color, width=w)
    # Arms
    draw.line([arm_joint, _tip(*arm_joint, pose.left_arm, arm)], fill=color, width=w)
    draw.line([arm_joint, _tip(*arm_joint, pose.right_arm, arm)], fill=color, width=w)
    # Legs
    draw.line([hip, _tip(*hip, pose.left_leg, leg)], fill=color, width=w)
    draw.line([hip, _tip(*hip, pose.right_leg, leg)], fill=color, width=w)


# --- Animated gestures: given phase t in [0, 1] return a Pose ---

def pose_idle(t: float) -> Pose:
    bob = 4 * math.sin(t * 2 * math.pi)
    return Pose(left_arm=-30 - bob, right_arm=30 + bob)


def pose_wave(t: float) -> Pose:
    # Right arm raised overhead, hand waving side to side.
    wave = 20 * math.sin(t * 4 * math.pi)
    return Pose(right_arm=150 + wave, left_arm=-30)


def pose_point_up(t: float) -> Pose:
    jitter = 4 * math.sin(t * 6 * math.pi)
    return Pose(right_arm=165 + jitter, left_arm=-30)


def pose_point_down(t: float) -> Pose:
    jitter = 4 * math.sin(t * 6 * math.pi)
    return Pose(right_arm=35 + jitter, left_arm=-30)


def pose_present(t: float) -> Pose:
    # Right arm extended out to the side toward the on-screen prop.
    sweep = 8 * math.sin(t * 2 * math.pi)
    return Pose(right_arm=90 + sweep, left_arm=-30)


def pose_walk(t: float) -> Pose:
    swing = 22 * math.sin(t * 4 * math.pi)
    return Pose(
        left_leg=-swing, right_leg=swing,
        left_arm=-30 + swing, right_arm=30 + swing,
    )


GESTURES = {
    "idle": pose_idle,
    "wave": pose_wave,
    "point_up": pose_point_up,
    "point_down": pose_point_down,
    "present": pose_present,
    "walk": pose_walk,
}


def draw_arrow(draw: ImageDraw.ImageDraw, x: float, y: float, up: bool, scale: float = 1.0) -> None:
    color = GREEN if up else RED
    h = 90 * scale
    w = 60 * scale
    tip_y = y - h if up else y + h
    draw.line([(x, y), (x, tip_y)], fill=color, width=max(3, int(8 * scale)))
    if up:
        draw.polygon([(x, tip_y - w * 0.5), (x - w * 0.5, tip_y + w * 0.2),
                      (x + w * 0.5, tip_y + w * 0.2)], fill=color)
    else:
        draw.polygon([(x, tip_y + w * 0.5), (x - w * 0.5, tip_y - w * 0.2),
                      (x + w * 0.5, tip_y - w * 0.2)], fill=color)


def draw_coin(draw: ImageDraw.ImageDraw, x: float, y: float, r: float = 34.0) -> None:
    draw.ellipse([x - r, y - r, x + r, y + r], outline=GOLD, width=6, fill=(60, 50, 10))
    draw.text((x - r * 0.35, y - r * 0.7), "$", fill=GOLD)


def draw_chart(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float = 1.0) -> None:
    heights = [30, 55, 45, 80, 65, 100]
    bw = 22 * scale
    for i, hgt in enumerate(heights):
        bx = x + i * (bw + 8 * scale)
        color = GREEN if i % 2 == 0 else GOLD
        draw.rectangle([bx, y - hgt * scale, bx + bw, y], fill=color)
