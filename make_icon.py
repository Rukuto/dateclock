"""Generate a multi-resolution .ico file for the DateClock executable."""
from PIL import Image, ImageDraw


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    # Outer dark circle (background)
    d.ellipse((pad, pad, size - pad, size - pad),
              fill=(20, 24, 36, 255),
              outline=(255, 255, 255, 255),
              width=max(1, size // 32))
    cx, cy = size / 2, size / 2
    # Hour hand
    d.line((cx, cy, cx, cy - size * 0.30),
           fill=(255, 255, 255, 255),
           width=max(1, size // 16))
    # Minute hand
    d.line((cx, cy, cx + size * 0.32, cy + size * 0.10),
           fill=(255, 255, 255, 255),
           width=max(1, size // 22))
    # Centre dot
    r = max(1, size // 20)
    d.ellipse((cx - r, cy - r, cx + r, cy + r),
              fill=(255, 255, 255, 255))
    return img


sizes = [16, 24, 32, 48, 64, 128, 256]
images = [make_icon(s) for s in sizes]
images[0].save("dateclock.ico", sizes=[(s, s) for s in sizes])
print("Wrote dateclock.ico")
