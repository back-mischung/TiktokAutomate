from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiktok_client import TikTokClient


if __name__ == "__main__":
    video_file = sys.argv[1] if len(sys.argv) > 1 else "../hood_video_generator/output/2026-06-09_001/final_video.mp4"
    result = TikTokClient().upload_video_to_inbox(video_file)
    print(result)

