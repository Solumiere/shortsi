"""
Upload file and get a link to open on phone.
Uses litterbox.catbox.moe (72h storage, no registration).
Usage: python upload.py path/to/file.mp4
"""
import sys
import httpx
from pathlib import Path


def upload(file_path: str) -> str:
    """Upload file, return download link (72h)"""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"Uploading {p.name} ({p.stat().st_size // 1024} KB)...")

    with open(p, "rb") as f:
        r = httpx.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": (p.name, f)},
            timeout=120,
        )

    if r.status_code == 200 and r.text.startswith("http"):
        url = r.text.strip()
        print(f"\n\u2705 Open on phone:\n{url}\n")
        return url
    else:
        raise Exception(f"Upload failed: {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload.py <file>")
        sys.exit(1)
    upload(sys.argv[1])
