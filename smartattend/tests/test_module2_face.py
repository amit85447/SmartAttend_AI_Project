"""Face recognition tests on REAL face photos (LFW public dataset via scikit-learn, downloaded once).
Skipped automatically when the dataset or model weights cannot be downloaded (no internet)."""
import numpy as np
import pytest
from datetime import time

pytest.importorskip("facenet_pytorch")
from PIL import Image
import config
from services import employees as E, face_service as F
from models import liveness


@pytest.fixture(scope="module")
def lfw():
    try:
        from sklearn.datasets import fetch_lfw_people
        return fetch_lfw_people(min_faces_per_person=40, resize=1.0, color=True)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"LFW unavailable: {e}")


@pytest.fixture(scope="module")
def fe():
    from models.face_model import FaceEngine
    try:
        return FaceEngine.get()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"FaceNet weights unavailable: {e}")


def photos(lfw, person, n, skip=0):
    idx = np.where(lfw.target == person)[0][skip:skip + n]
    return [np.asarray(Image.fromarray((lfw.images[i] * 255).astype(np.uint8)).resize((376, 500))) for i in idx]


@pytest.fixture()
def enrolled(setup, lfw, fe, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EMPLOYEE_PHOTO_DIR", tmp_path / "emp")
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "k.key")
    eng, sched, _ = setup
    ids = []
    for person, (name, mail) in enumerate([("Person A", "a@x.com"), ("Person B", "b@x.com")]):
        i = E.register_employee(name, "IT", "Analyst", mail, None, sched, "Passw0rd!", eng=eng)
        E.set_consent(i, True, eng=eng)
        F.enroll(i, photos(lfw, person, 4), eng=eng, engine_=fe)
        ids.append(i)
    return eng, ids


def test_enroll_requires_consent(setup, lfw, fe):
    eng, sched, _ = setup
    i = E.register_employee("No Consent", "IT", "x", "n@x.com", None, sched, "Passw0rd!", eng=eng)
    with pytest.raises(F.EnrollmentError, match="consent"):
        F.enroll(i, photos(lfw, 0, 4), eng=eng, engine_=fe)


def test_genuine_accepted_impostor_and_unknown_rejected(enrolled, lfw, fe):
    eng, (a, b) = enrolled
    ok = sum(F.verify_face(a, img, eng, fe)[0].ok for img in photos(lfw, 0, 8, skip=6))
    assert ok >= 7, f"genuine accepted only {ok}/8"
    for img in photos(lfw, 1, 6, skip=6):          # B's face while claiming to be A
        assert not F.verify_face(a, img, eng, fe)[0].ok
    for img in photos(lfw, 5, 6):                   # person never enrolled
        assert not F.verify_face(a, img, eng, fe)[0].ok


def test_duplicate_face_enrolment_refused(enrolled, lfw, fe, setup):
    eng, ids = enrolled
    sched = 1
    c = E.register_employee("Clone", "IT", "x", "clone@x.com", None, sched, "Passw0rd!", eng=eng)
    E.set_consent(c, True, eng=eng)
    with pytest.raises(F.EnrollmentError, match="already matches"):
        F.enroll(c, photos(lfw, 0, 4, skip=10), eng=eng, engine_=fe)


def test_embeddings_are_encrypted_at_rest(enrolled):
    from sqlalchemy import select
    from database.tables import face_profiles
    eng, _ = enrolled
    with eng.connect() as c:
        blob = c.execute(select(face_profiles.c.embedding_enc)).scalar()
    assert len(bytes(blob)) != 512 * 4 and bytes(blob).startswith(b"gAAAA")   # Fernet token, not raw floats


def test_head_turn_logic():
    left = np.array([[40, 50], [80, 50], [50, 70], [45, 90], [75, 90]], float)    # nose toward image-left
    front = np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], float)
    right = np.array([[40, 50], [80, 50], [70, 70], [45, 90], [75, 90]], float)
    assert liveness.head_turn_check(front, left, "left").passed
    assert not liveness.head_turn_check(front, left, "right").passed
    assert liveness.head_turn_check(front, right, "right").passed
    assert not liveness.head_turn_check(front, front, "left").passed     # a static photo never "turns"


def test_static_photo_replay_fails_challenge(enrolled, lfw, fe):
    """Same photo shown twice (printed-photo attack): identity matches but no head turn -> rejected."""
    eng, (a, _) = enrolled
    img = photos(lfw, 0, 1, skip=8)[0]
    res = F.verify_live(a, img, img.copy(), "left", eng, fe)
    assert not res.ok


def test_passive_liveness_drops_on_simulated_screen_replay(lfw, fe):
    """Simulated attack: blur + strong periodic moire pattern, like re-photographing a monitor."""
    import cv2
    img = photos(lfw, 0, 1, skip=8)[0]
    det = fe.single_face(img)
    base = liveness.passive_score(img, det.box).score
    yy, xx = np.indices(img.shape[:2])
    moire = (22 * np.sin(2 * np.pi * xx / 4.0) * np.sin(2 * np.pi * yy / 5.0))[..., None]
    fake = np.clip(cv2.GaussianBlur(img, (7, 7), 0).astype(float) + moire, 0, 255).astype(np.uint8)
    fake_score = liveness.passive_score(fake, det.box).score
    assert fake_score < base


def test_real_head_turn_between_two_real_photos_passes(enrolled, lfw, fe, monkeypatch):
    """Positive path: two real photos of the same person with different head poses.
    Passive threshold is relaxed here because LFW images are tiny, upscaled crops; this test
    exercises identity + head-turn logic. Opposite challenge must fail."""
    monkeypatch.setattr(config, "LIVENESS_THRESHOLD", 0.0)
    eng, (a, _) = enrolled
    imgs = photos(lfw, 0, 40, skip=6)
    dets = []
    for im in imgs:
        fs = [f for f in fe.detect(im) if f.prob >= 0.95]
        if len(fs) == 1:
            dets.append((im, liveness.head_yaw_index(fs[0].landmarks)))
    best = None
    for ia, ya in dets:
        for ib, yb in dets:
            if yb - ya > 0.2 and (best is None or yb - ya > best[0]):
                best = (yb - ya, ia, ib)
    assert best, "no pose-varied pair found"
    _, frame_a, frame_b = best                       # frame_b has the nose further toward image-right
    good = F.verify_live(a, frame_a, frame_b, "right", eng, fe)
    bad = F.verify_live(a, frame_a, frame_b, "left", eng, fe)
    assert good.ok and good.liveness_score is not None
    assert not bad.ok
