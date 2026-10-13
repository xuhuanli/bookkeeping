from hashlib import sha256
from pathlib import Path


def instance_id(root: Path, data_dir: Path, images_dir: Path) -> str:
    """Identify this local ledger without publishing its filesystem paths."""
    locations = '|'.join(str(p.resolve()) for p in (root, data_dir, images_dir))
    return sha256(locations.encode()).hexdigest()[:16]
