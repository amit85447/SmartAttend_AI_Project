"""Face enrolment and verification (Module 2).

Enrolment needs recorded biometric consent. Embeddings are stored Fernet-encrypted.
Verification is 1:1 against the logged-in employee, plus a 1:N safety check so a face that matches
another employee better is rejected. Unknown faces are always rejected.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from sqlalchemy import select, insert
import config
from database.db import engine
from database.tables import face_profiles, employees
from models.face_model import FaceEngine, FaceError, cosine
from models import liveness
from services import crypto, audit, employees as emp_svc
from utils.images import rgb_to_jpeg_bytes, save_encrypted


class EnrollmentError(Exception):
    pass


@dataclass
class VerifyResult:
    ok: bool
    confidence: float = 0.0
    liveness_score: float | None = None
    reason: str = ""
    details: dict = field(default_factory=dict)


def _emb_to_blob(v: np.ndarray) -> bytes:
    return crypto.encrypt(v.astype(np.float32).tobytes())


def _blob_to_emb(b: bytes) -> np.ndarray:
    return np.frombuffer(crypto.decrypt(bytes(b)), dtype=np.float32)


def load_embeddings(eng=None, employee_id: int | None = None) -> dict[int, np.ndarray]:
    """{employee_id: array (n, 512)} for active employees."""
    q = (select(face_profiles.c.employee_id, face_profiles.c.embedding_enc)
         .join(employees, employees.c.employee_id == face_profiles.c.employee_id)
         .where(employees.c.status == "active"))
    if employee_id is not None:
        q = q.where(face_profiles.c.employee_id == employee_id)
    out: dict[int, list] = {}
    with (eng or engine()).connect() as c:
        for emp, blob in c.execute(q):
            out.setdefault(emp, []).append(_blob_to_emb(blob))
    return {k: np.vstack(v) for k, v in out.items()}


def enroll(employee_id: int, images: list[np.ndarray], actor="system", eng=None, engine_=None) -> int:
    """Enrol several face images (RGB arrays). Returns number of profiles stored."""
    eng = eng or engine()
    fe = engine_ or FaceEngine.get()
    if not emp_svc.has_consent(employee_id, eng):
        raise EnrollmentError("Biometric consent has not been recorded for this employee")
    if len(images) < config.MIN_ENROLL_IMAGES:
        raise EnrollmentError(f"Provide at least {config.MIN_ENROLL_IMAGES} face images (different angles/lighting)")
    embs, accepted = [], []
    for i, img in enumerate(images, 1):
        try:
            det = fe.single_face(img)
        except FaceError as e:
            raise EnrollmentError(f"Image {i}: {e}")
        embs.append(fe.embed(img, det))
        accepted.append(img)
    arr = np.vstack(embs)
    # all enrolment images must show the same person
    cm = arr @ arr.T
    if cm.min() < config.FACE_MATCH_THRESHOLD - 0.15:
        raise EnrollmentError("Enrolment images do not look like the same person")
    # refuse if this face already belongs to another employee (stops duplicate/proxy enrolment)
    for other_id, oemb in load_embeddings(eng).items():
        if other_id != employee_id and float((arr @ oemb.T).max()) >= config.FACE_MATCH_THRESHOLD:
            raise EnrollmentError("This face already matches another registered employee")
    code = emp_svc.get_employee(employee_id, eng)["emp_code"]
    with eng.begin() as c:
        for i, (v, img) in enumerate(zip(embs, accepted), 1):
            path = save_encrypted(rgb_to_jpeg_bytes(img), config.EMPLOYEE_PHOTO_DIR,
                                  f"{code}_{i}_{np.random.randint(10**8):08d}")
            c.execute(insert(face_profiles).values(employee_id=employee_id, embedding_enc=_emb_to_blob(v),
                      embedding_dim=len(v), model_name=config.FACE_MODEL_NAME, image_path=path))
    audit.log("admin", actor, "face_enrolled", "employees", employee_id, {"images": len(embs)}, eng)
    return len(embs)


def verify_face(employee_id: int, rgb: np.ndarray, eng=None, engine_=None):
    """Identity check on one frame. Returns (VerifyResult, FaceDetection|None, embedding|None)."""
    eng = eng or engine()
    fe = engine_ or FaceEngine.get()
    try:
        det = fe.single_face(rgb)
    except FaceError as e:
        return VerifyResult(False, reason=str(e)), None, None
    emb = fe.embed(rgb, det)
    bank = load_embeddings(eng)
    own = bank.get(employee_id)
    if own is None:
        return VerifyResult(False, reason="No face enrolled for this employee"), det, emb
    conf = float((own @ emb).max())
    others = [float((v @ emb).max()) for k, v in bank.items() if k != employee_id]
    best_other = max(others) if others else -1.0
    d = {"best_other": round(best_other, 4), "threshold": config.FACE_MATCH_THRESHOLD}
    if conf < config.FACE_MATCH_THRESHOLD:
        return VerifyResult(False, round(conf, 4), reason="Face not recognised (unknown or unverified)", details=d), det, emb
    if others and best_other >= conf - config.FACE_MARGIN_OVER_OTHERS:
        return VerifyResult(False, round(conf, 4), reason="Face is ambiguous with another employee, rejected", details=d), det, emb
    return VerifyResult(True, round(conf, 4), reason="Face verified", details=d), det, emb


def verify_live(employee_id: int, frame_a: np.ndarray, frame_b: np.ndarray | None, challenge: str | None,
                eng=None, engine_=None) -> VerifyResult:
    """Full identity + liveness check used when marking attendance.

    frame_a: neutral photo (this is the photo saved with the attendance).
    frame_b: challenge photo (head turned toward `challenge`). Required when LIVENESS_REQUIRED.
    """
    fe = engine_ or FaceEngine.get()
    res, det_a, emb_a = verify_face(employee_id, frame_a, eng, fe)
    if not res.ok:
        return res
    live_scores = []
    if config.LIVENESS_REQUIRED:
        p = liveness.passive_score(frame_a, det_a.box)
        res.details["passive"] = {k: round(float(v), 4) for k, v in p.details.items()}
        live_scores.append(p.score)
        if not p.passed:
            return VerifyResult(False, res.confidence, p.score, p.reason, res.details)
        if frame_b is None or challenge is None:
            return VerifyResult(False, res.confidence, p.score, "Liveness challenge photo missing", res.details)
        res_b, det_b, emb_b = verify_face(employee_id, frame_b, eng, fe)
        if not res_b.ok:
            return VerifyResult(False, res_b.confidence, p.score, "Challenge photo: " + res_b.reason, res.details)
        if cosine(emb_a, emb_b) < config.FACE_MATCH_THRESHOLD:
            return VerifyResult(False, res.confidence, p.score, "The two photos are not the same person", res.details)
        pb = liveness.passive_score(frame_b, det_b.box)
        live_scores.append(pb.score)
        if not pb.passed:
            return VerifyResult(False, res.confidence, pb.score, "Challenge photo: " + pb.reason, res.details)
        turn = liveness.head_turn_check(det_a.landmarks, det_b.landmarks, challenge)
        res.details["head_turn"] = {"moved": turn.score, "challenge": challenge}
        if not turn.passed:
            return VerifyResult(False, res.confidence, p.score, turn.reason, res.details)
    res.liveness_score = round(float(np.mean(live_scores)), 4) if live_scores else None
    return res
