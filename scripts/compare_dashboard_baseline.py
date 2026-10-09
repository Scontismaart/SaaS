"""Read-only decoded-pixel comparison of real-browser synthetic baselines."""
import argparse
import json

from PIL import Image, ImageChops


def compare(first, second):
    with Image.open(first) as source, Image.open(second) as repeat:
        if source.size != repeat.size:
            raise ValueError("Baseline dimensions differ")
        difference = ImageChops.difference(source.convert("RGB"), repeat.convert("RGB"))
        pixels = difference.tobytes()
        changed = sum(any(pixels[index:index + 3]) for index in range(0, len(pixels), 3))
        width, height = source.size
        return {"width": width, "height": height, "changed_pixels": changed,
                "ratio": changed / (width * height)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("capture")
    arguments = parser.parse_args()
    result = compare(arguments.baseline, arguments.capture)
    print(json.dumps(result))
    raise SystemExit(1 if result["changed_pixels"] else 0)
