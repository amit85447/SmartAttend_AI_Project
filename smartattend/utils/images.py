"""Image helpers: decode uploads/camera bytes, encrypt-at-rest storage for photos."""
import io
from pathlib import Path
import numpy as np
from PIL import Image
from services import crypto


def bytes_to_rgb(data: bytes) -> np.ndarray:
    """Decode JPEG/PNG bytes to an RGB uint8 array (EXIF rotation applied)."""
    from PIL import ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def rgb_to_jpeg_bytes(arr: np.ndarray, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def save_encrypted(data: bytes, directory: Path, filename: str) -> str:
    """Write encrypted bytes into a private directory and return the path as text."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename + ".enc")
    path.write_bytes(crypto.encrypt(data))
    return str(path)


def load_encrypted(path: str) -> bytes:
    return crypto.decrypt(Path(path).read_bytes())
