"""Deep-learning face detection and embedding.

Detector : MTCNN (facenet-pytorch)
Embedder : FaceNet InceptionResnetV1 pretrained on VGGFace2 -> 512-d L2-normalised vector
Matching : cosine similarity between embeddings.
First run downloads the pretrained weights (~110 MB) once.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import torch
from PIL import Image
import config


class FaceError(Exception):
    """Raised with a user-readable reason when no usable face is found."""


@dataclass
class FaceDetection:
    box: np.ndarray            # x1,y1,x2,y2 in pixels
    prob: float
    landmarks: np.ndarray      # 5x2: left eye, right eye, nose, left mouth, right mouth


class FaceEngine:
    _instance = None

    def __init__(self, device: str | None = None):
        from facenet_pytorch import MTCNN, InceptionResnetV1
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.mtcnn = MTCNN(keep_all=True, device=self.device, post_process=False, min_face_size=40)
        self.net = InceptionResnetV1(pretrained="vggface2").eval().to(self.device)

    @classmethod
    def get(cls) -> "FaceEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- detection -----------------------------------------------------------
    def detect(self, rgb: np.ndarray) -> list[FaceDetection]:
        boxes, probs, lms = self.mtcnn.detect(Image.fromarray(rgb), landmarks=True)
        if boxes is None:
            return []
        return [FaceDetection(b, float(p), l) for b, p, l in zip(boxes, probs, lms) if p is not None]

    def single_face(self, rgb: np.ndarray) -> FaceDetection:
        faces = [f for f in self.detect(rgb) if f.prob >= config.MIN_FACE_PROB]
        if not faces:
            raise FaceError("No clear face detected. Face the camera in good light.")
        if len(faces) > 1:
            raise FaceError("More than one face in the photo. Only one person may be in frame.")
        return faces[0]

    # -- embedding -----------------------------------------------------------
    def _crop(self, rgb: np.ndarray, det: FaceDetection) -> torch.Tensor:
        from facenet_pytorch.models.utils.detect_face import extract_face
        face = extract_face(Image.fromarray(rgb), det.box, image_size=160, margin=0)  # 3x160x160 float 0-255
        return (face.float() - 127.5) / 128.0                                         # FaceNet standardisation

    @torch.no_grad()
    def embed(self, rgb: np.ndarray, det: FaceDetection | None = None) -> np.ndarray:
        det = det or self.single_face(rgb)
        x = self._crop(rgb, det).unsqueeze(0).to(self.device)
        v = self.net(x)[0].cpu().numpy().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
