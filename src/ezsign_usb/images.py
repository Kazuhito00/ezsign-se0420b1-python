"""Four pixels per byte, most significant pixel first (0=K, 1=W, 2=Y, 3=R)."""
from pathlib import Path
from PIL import Image, ImageOps

SIZE = (400, 300)
PALETTE = ((0, 0, 0), (255, 255, 255), (255, 192, 0), (255, 0, 0))
IMAGE_BYTES = SIZE[0] * SIZE[1] // 4


def prepare_image(source: Image.Image | str | Path, *, dither: bool = False) -> Image.Image:
    """Fit onto white 400x300 canvas without stretching; quantize to device colors."""
    if isinstance(source, Image.Image):
        image = ImageOps.exif_transpose(source).convert('RGBA')
    else:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGBA')
    white = Image.new('RGBA', image.size, 'white')
    image = Image.alpha_composite(white, image).convert('RGB')
    image = ImageOps.pad(image, SIZE, method=Image.Resampling.LANCZOS, color='white')
    palette = Image.new('P', (1, 1))
    palette.putpalette([v for rgb in PALETTE for v in rgb] * 64)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    return image.quantize(palette=palette, dither=mode).convert('RGB')


def encode_image(image: Image.Image) -> bytes:
    """Encode an already prepared image; reject unknown colors or dimensions."""
    if image.size != SIZE:
        raise ValueError(f"Image must be {SIZE}")
    codes = {color: i for i, color in enumerate(PALETTE)}
    # Accept pure yellow as well as the official application's amber yellow.
    codes[(255, 255, 0)] = 2
    channels = iter(image.convert('RGB').tobytes())
    pixels = list(zip(channels, channels, channels))
    out = bytearray()
    for i in range(0, len(pixels), 4):
        value = 0
        for pixel in pixels[i:i+4]:
            if pixel not in codes:
                raise ValueError(f"Unsupported pixel {pixel}; use prepare_image() first")
            value = (value << 2) | codes[pixel]
        out.append(value)
    return bytes(out)


def decode_image(data: bytes) -> Image.Image:
    if len(data) != IMAGE_BYTES:
        raise ValueError(f"Expected {IMAGE_BYTES} bytes, got {len(data)}")
    image = Image.new('RGB', SIZE)
    image.putdata([PALETTE[(byte >> shift) & 3] for byte in data for shift in (6, 4, 2, 0)])
    return image
