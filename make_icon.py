"""Draw the Light Overlay icon."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 32, 48, 256)


def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pad = max(1, size // 16)
    radius = max(2, size // 6)
    pen.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=(28, 28, 30, 255),
        outline=(142, 142, 147, 255),
        width=max(1, size // 32),
    )
    bar_w = max(2, size // 7)
    gap = max(2, size // 10)
    left = size // 5
    base = size - size // 4
    heights = (0.42, 0.68, 0.50)
    colors = ((161, 161, 166, 255), (125, 190, 255, 255), (242, 242, 247, 255))
    for index, (height, color) in enumerate(zip(heights, colors)):
        x0 = left + index * (bar_w + gap)
        y0 = base - int((size * 0.55) * height)
        pen.rounded_rectangle(
            (x0, y0, x0 + bar_w, base),
            radius=max(1, bar_w // 3),
            fill=color,
        )
    return image


def main() -> None:
    folder = Path(__file__).resolve().parent / "assets"
    folder.mkdir(exist_ok=True)
    draw(256).save(
        folder / "lightoverlay.ico",
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )


if __name__ == "__main__":
    main()
