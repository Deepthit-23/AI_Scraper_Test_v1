"""
Image / vision input for the pipeline.

Sends a product image (photo of a label, nameplate, or datasheet scan) to
Groq's Llama 4 Scout vision model, which reads all the text and describes
what it sees. The returned text is then fed into the same extract_product()
function used by the web scraper and PDF reader — no special handling needed.

Supported formats: JPEG, PNG, WebP, GIF (static).
Max size Groq accepts: ~20 MB per image.

Usage:
    from scraper.image_ingest import image_to_clean_text
    result = image_to_clean_text("path/to/product_label.jpg")
    if result.success:
        record = extract_product(result.extracted_text, source_id=result.source_path)
"""

import os
import base64
from dataclasses import dataclass
from typing import Optional
from groq import Groq

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_MIME_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

VISION_PROMPT = (
    "This image shows a product, product label, nameplate, or datasheet scan. "
    "Please do two things:\n"
    "1. Transcribe ALL text visible in the image exactly as written, preserving structure.\n"
    "2. Describe any specs, tables, diagrams, or part numbers shown even if not text "
    "(e.g. 'diagram shows a valve with inlet labeled 1/2 NPT').\n"
    "Output everything as plain text. This will feed a product data extraction pipeline "
    "so completeness matters more than formatting."
)


@dataclass
class ImageExtract:
    source_path: str
    extracted_text: str
    success: bool
    error: Optional[str] = None


def image_to_clean_text(image_path: str) -> ImageExtract:
    """
    Read a product image and return extracted text ready for extract_product().
    image_path: local path to the image file.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set — see .env.example")

    if not os.path.exists(image_path):
        return ImageExtract(image_path, "", False, f"File not found: {image_path}")

    ext = image_path.rsplit(".", 1)[-1].lower()
    mime_type = _MIME_MAP.get(ext, "image/jpeg")

    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=VISION_MODEL,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                        },
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content
        return ImageExtract(image_path, text, True)

    except Exception as e:
        return ImageExtract(image_path, "", False, str(e))


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/samples/product_label.jpg"
    from dotenv import load_dotenv
    load_dotenv()
    result = image_to_clean_text(path)
    if result.success:
        print(f"Extracted {len(result.extracted_text)} chars:\n")
        print(result.extracted_text[:1000])
    else:
        print(f"Failed: {result.error}")
