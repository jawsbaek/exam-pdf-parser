"""Debug: inspect MinerU middle_json blocks to understand question detection failures."""

import json
import logging
import os
import re
import sys
import time

logging.basicConfig(level=logging.WARNING)

PDF_PATH = "test/2025년-9월-고3-모의고사-영어-문제.pdf"
CACHE_PATH = "output/debug_middle_json.json"


def run_mineru():
    """Run MinerU and cache middle_json (requires __name__ == '__main__' guard)."""
    from src.ocr import get_ocr_engine
    from src.config import get_settings

    ocr_engine = get_ocr_engine("mineru")
    settings = get_settings()
    if hasattr(ocr_engine, "configure"):
        ocr_engine.configure(
            language=settings.MINERU_LANGUAGE,
            parse_method=settings.MINERU_PARSE_METHOD,
            formula_enable=settings.MINERU_FORMULA_ENABLE,
            table_enable=settings.MINERU_TABLE_ENABLE,
            make_mode=settings.MINERU_MAKE_MODE,
        )
    ocr_engine.set_pdf_path(PDF_PATH)
    ocr_engine._ensure_initialized()
    ocr_engine._convert_pdf(PDF_PATH)
    middle_json = ocr_engine.get_layout_data()

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(middle_json, f, ensure_ascii=False, indent=2)
    print(f"Cached to {CACHE_PATH}")
    return middle_json


# Question number patterns
_Q_PATTERNS = [
    re.compile(r'^\[(\d{1,2})~(\d{1,2})\]'),
    re.compile(r'^【(\d{1,2})】'),
    re.compile(r'^\[(\d{1,2})\]'),
    re.compile(r'^(\d{1,2})\.\s'),
    re.compile(r'^(\d{1,2})\s'),
]


def extract_text(block):
    texts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            content = span.get("content", "")
            if content:
                texts.append(content)
    return " ".join(texts).strip()


def detect_q_num(text):
    text = text.strip()
    for p in _Q_PATTERNS:
        m = p.match(text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 50:
                return n
    return None


def analyze(middle_json):
    print(f"\n{'='*80}")
    print("BLOCK ANALYSIS PER PAGE")
    print(f"{'='*80}")

    all_detected = []

    for page_info in middle_json.get("pdf_info", []):
        page_idx = page_info.get("page_idx", 0)

        para_blocks = page_info.get("para_blocks", [])
        preproc_blocks = page_info.get("preproc_blocks", [])

        blocks = para_blocks or preproc_blocks
        block_source = "para_blocks" if para_blocks else "preproc_blocks"

        print(f"\n--- Page {page_idx} ({block_source}: {len(blocks)} blocks) ---")

        for i, block in enumerate(blocks):
            btype = block.get("type", "?")
            bbox = block.get("bbox", [])
            text = extract_text(block)
            q_num = detect_q_num(text) if text else None

            display_text = text[:120].replace('\n', ' ') if text else "(empty)"
            marker = f" *** Q{q_num}" if q_num else ""
            has_bbox = "bbox" if bbox else "NO-BBOX"

            print(f"  [{i:3d}] type={btype:8s} {has_bbox} | {display_text}{marker}")

            if q_num:
                all_detected.append(q_num)

    print(f"\n{'='*80}")
    print("DETECTION SUMMARY")
    print(f"{'='*80}")
    print(f"Detected questions: {sorted(set(all_detected))}")
    print(f"Count: {len(set(all_detected))}")
    missing = set(range(1, 46)) - set(all_detected)
    print(f"Missing (1-45): {sorted(missing)}")

    # Show available keys
    print(f"\n{'='*80}")
    print("STRUCTURE INFO")
    print(f"{'='*80}")
    for page_info in middle_json.get("pdf_info", [])[:1]:
        print(f"Page info keys: {list(page_info.keys())}")
        for key in ["para_blocks", "preproc_blocks"]:
            blocks = page_info.get(key, [])
            if blocks:
                print(f"  {key}[0] keys: {list(blocks[0].keys())}")
                print(f"  {key} count: {len(blocks)}")


if __name__ == "__main__":
    if os.path.exists(CACHE_PATH):
        print(f"Loading cached middle_json from {CACHE_PATH}")
        with open(CACHE_PATH) as f:
            middle_json = json.load(f)
    else:
        print("No cache found, running MinerU...")
        middle_json = run_mineru()

    analyze(middle_json)
