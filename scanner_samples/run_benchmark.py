from __future__ import annotations

import base64
import csv
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import ScannerFrameIn, detect_and_warp_card, get_db, scan_card_frame  # noqa: E402


def browser_frame(path: Path) -> Image.Image:
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    return image


def data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def card_identity(card: dict) -> tuple[str, str, str]:
    return (
        str(card.get("set_code") or "").upper(),
        str(card.get("collector_number") or "").lstrip("0") or "0",
        str(card.get("lang") or "").lower(),
    )


def main() -> int:
    labels_path = ROOT / "scanner_samples" / "labels.csv"
    image_dir = labels_path.parent / "images"
    rows = list(csv.DictReader(labels_path.open(encoding="utf-8", newline="")))
    results = []
    db = get_db()
    try:
        for index, label in enumerate(rows, 1):
            image = browser_frame(image_dir / label["filename"])
            started = time.perf_counter()
            warped, detection_score = detect_and_warp_card(image)
            detection_ms = round((time.perf_counter() - started) * 1000)
            encoded = data_url(image)
            started = time.perf_counter()
            response = scan_card_frame(
                ScannerFrameIn(
                    image_data=encoded,
                    full_image_data=encoded,
                    live=True,
                ),
                db,
            )
            scan_ms = round((time.perf_counter() - started) * 1000)
            expected = (
                label["set_code"].upper(),
                label["collector_number"].lstrip("0") or "0",
                label["language"].lower(),
            )
            identities = [card_identity(card) for card in response.get("cards", [])]
            exact = expected in identities
            printing = any(identity[:2] == expected[:2] for identity in identities)
            result = {
                "file": label["filename"],
                "expected": expected,
                "detected": warped is not None,
                "detection_score": round(detection_score, 3),
                "detection_ms": detection_ms,
                "scan_ms": scan_ms,
                "engine": response.get("ocr_engine"),
                "recognized_text": response.get("recognized_text", ""),
                "name_text": response.get("name_text", ""),
                "matches": identities[:8],
                "printing_pass": printing,
                "exact_pass": exact,
            }
            results.append(result)
            status = "PASS" if exact else ("PRINT" if printing else "FAIL")
            print(
                f"[{index}/{len(rows)}] {status:5} {label['filename']} "
                f"contour={result['detected']} scan={scan_ms}ms matches={identities[:3]}",
                flush=True,
            )
    finally:
        db.close()
    summary = {
        "samples": len(results),
        "contours": sum(result["detected"] for result in results),
        "printing_passes": sum(result["printing_pass"] for result in results),
        "exact_passes": sum(result["exact_pass"] for result in results),
        "average_scan_ms": round(sum(result["scan_ms"] for result in results) / max(1, len(results))),
    }
    report = {"summary": summary, "results": results}
    (labels_path.parent / "benchmark-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["printing_passes"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
