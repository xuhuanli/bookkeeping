import base64
import io
import re
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 12 * 1024 * 1024
IMAGE_URL = re.compile(r'^/images/([a-f0-9]{32}\.jpg)$')


def store_image(raw: bytes, directory: Path) -> str:
    if not raw or len(raw) > MAX_UPLOAD:
        raise ValueError('图片不能超过 12 MB。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('支持 JPG、PNG 和 WebP 图片。请将 HEIC 转为 JPG 后上传。')
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1600, 1600))
                if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                    background = Image.new('RGB', image.size, '#ffffff')
                    image = image.convert('RGBA')
                    background.paste(image, mask=image.getchannel('A'))
                    image = background
                else:
                    image = image.convert('RGB')
                output = io.BytesIO()
                image.save(output, format='JPEG', quality=82, optimize=True)
                directory.mkdir(parents=True, exist_ok=True)
                name = uuid4().hex + '.jpg'
                (directory / name).write_bytes(output.getvalue())
                return '/images/' + name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('无法读取图片，请选择有效的 JPG、PNG 或 WebP。') from None


def image_path(url: str, directory: Path) -> Path:
    match = IMAGE_URL.fullmatch(url)
    if not match or not (directory / match[1]).is_file():
        raise ValueError('照片文件不存在，请重新上传或使用包含照片的完整备份。')
    return directory / match[1]


def check_photos(state, directory):
    for order in state['orders']:
        for url in order['photos']:
            image_path(url, directory)


def restore_photos(state, directory):
    # Embedded images make JSON backups portable to another computer.
    created = []
    mapping = {}
    try:
        for order in state['orders']:
            urls = []
            for photo in order.get('photos', []):
                if photo in mapping:
                    urls.append(mapping[photo])
                    continue
                if photo.startswith('data:image/'):
                    match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]+=*)', photo)
                    if not match:
                        raise ValueError('备份中的照片格式不正确。')
                    raw = base64.b64decode(match[2], validate=True)
                    url = store_image(raw, directory)
                    created.append(image_path(url, directory))
                    mapping[photo] = url
                    urls.append(url)
                else:
                    image_path(photo, directory)
                    urls.append(photo)
            order['photos'] = urls
        return created
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def embed_photos(state, directory):
    mapping = {}
    for order in state['orders']:
        for index, url in enumerate(order['photos']):
            if url not in mapping:
                mapping[url] = 'data:image/jpeg;base64,' + base64.b64encode(image_path(url, directory).read_bytes()).decode()
            order['photos'][index] = mapping[url]
    return state
