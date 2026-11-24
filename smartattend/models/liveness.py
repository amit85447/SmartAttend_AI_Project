"""Face liveness (anti-spoofing) checks.

IMPORTANT, honest scope: these are lightweight, explainable heuristics. They raise the bar against
casual attacks (a printed photo or a phone/monitor replay held up to the camera) but they are NOT a
certified presentation-attack-detection (PAD) product. For high-security use, add an IR/depth camera
or a trained PAD model. Every check below is real computation on the pixels, nothing is faked.

1. Passive texture score (single frame): sharpness, screen-moire peaks in the FFT, glare/saturation.
2. Active head-turn challenge (two frames): the person must turn their head toward a randomly chosen
   side; we measure the movement of the nose relative to the eyes using MTCNN landmarks, and require
   both frames to match the same identity. A flat photo cannot change its 3D pose between frames.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
import cv2
import numpy as np
import config

CHALLENGES = ("left", "right")


def new_challenge() -> str:
    """Server-side random challenge so an attacker cannot pre-record the correct answer."""
    return random.SystemRandom().choice(CHALLENGES)


@dataclass
class LivenessResult:
    passed: bool
    score: float
    details: dict = field(default_factory=dict)
    reason: str = ""


def _face_crop(rgb, box, pad=0.1):
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1, x2 = int(max(0, x1 - pad * bw)), int(min(w, x2 + pad * bw))
    y1, y2 = int(max(0, y1 - pad * bh)), int(min(h, y2 + pad * bh))
    return rgb[y1:y2, x1:x2]


def passive_features(rgb: np.ndarray, box) -> dict:
    crop = cv2.resize(_face_crop(rgb, box), (128, 128), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # 1. sharpness: variance of Laplacian (blurry re-captures score low)
    sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    # 2. moire: strong isolated peaks in the mid/high-frequency band of the spectrum
    f = np.fft.fftshift(np.abs(np.fft.fft2(gray - gray.mean())))
    yy, xx = np.indices(f.shape)
    r = np.hypot(yy - 64, xx - 64)
    band = f[(r > 18) & (r < 60)]
    peak_ratio = float(band.max() / (np.median(band) + 1e-6))
    # 3. glare / flatness: share of near-saturated pixels and colour spread
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    glare = float(np.mean((hsv[..., 2] > 245) & (hsv[..., 1] < 40)))
    contrast = float(gray.std())
    return {"sharpness": sharp, "moire_peak_ratio": peak_ratio, "glare_fraction": glare, "contrast": contrast}


def passive_score(rgb: np.ndarray, box) -> LivenessResult:
    d = passive_features(rgb, box)
    s_sharp = float(np.clip((d["sharpness"] - 15) / 85, 0, 1))        # >100 fully sharp
    s_moire = float(np.clip(1 - (d["moire_peak_ratio"] - 25) / 60, 0, 1))  # peaks >85x median = screen
    s_glare = float(np.clip(1 - d["glare_fraction"] / 0.08, 0, 1))
    s_contrast = float(np.clip((d["contrast"] - 12) / 28, 0, 1))
    score = 0.35 * s_sharp + 0.30 * s_moire + 0.15 * s_glare + 0.20 * s_contrast
    d.update(s_sharp=s_sharp, s_moire=s_moire, s_glare=s_glare, s_contrast=s_contrast)
    ok = score >= config.LIVENESS_THRESHOLD
    return LivenessResult(ok, round(score, 4), d, "" if ok else "Photo looks like a screen or print (low texture quality)")


def head_yaw_index(landmarks: np.ndarray) -> float:
    """Normalised horizontal nose offset: 0 = frontal, negative = nose toward image-left."""
    le, re_, nose = landmarks[0], landmarks[1], landmarks[2]
    eye_mid_x = (le[0] + re_[0]) / 2.0
    iod = abs(re_[0] - le[0]) + 1e-6
    return float((nose[0] - eye_mid_x) / iod)


def head_turn_check(lm_a: np.ndarray, lm_b: np.ndarray, challenge: str) -> LivenessResult:
    """Frame B must show the head turned toward `challenge` side of the image relative to frame A."""
    shift = head_yaw_index(lm_b) - head_yaw_index(lm_a)
    want = -1 if challenge == "left" else 1
    moved = shift * want
    ok = moved >= config.HEAD_TURN_MIN_SHIFT
    return LivenessResult(ok, round(float(moved), 4), {"yaw_a": head_yaw_index(lm_a), "yaw_b": head_yaw_index(lm_b),
                          "shift": shift, "challenge": challenge},
                          "" if ok else f"Head turn toward the {challenge} not detected")
