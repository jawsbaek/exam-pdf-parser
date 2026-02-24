"""
Question-level cropping pipeline.
시험지를 문제 단위로 크롭하여 이미지 + 해설 구조로 파싱합니다.
"""

import logging
import time
from pathlib import Path

from ..config import get_settings
from ..ocr import get_ocr_engine
from ..schema import CroppedExam, ExamInfo
from .cropper import QuestionCropper
from .detector import QuestionRegionDetector
from .explainer import QuestionExplainer

logger = logging.getLogger(__name__)


def crop_and_explain(
    pdf_path: str,
    output_dir: str = "output/cropped",
    dpi: int = 300,
    add_explanations: bool = False,
    llm_name: str = "gemini-3-pro-preview",
) -> CroppedExam:
    """
    시험지 PDF → 문제별 크롭 이미지 + 해설.

    Pipeline:
        1. MinerU로 레이아웃 분석 (middle_json with bbox data)
        2. 문제 번호 패턴으로 영역 그루핑
        3. PyMuPDF로 영역별 크롭
        4. (선택) Gemini Vision으로 해설 생성

    Args:
        pdf_path: Path to exam PDF file
        output_dir: Directory to save cropped PNG images
        dpi: Resolution for cropped images (default 300)
        add_explanations: Whether to generate Gemini explanations
        llm_name: Gemini model name for explanations

    Returns:
        CroppedExam with per-question images and optional explanations
    """
    t0 = time.monotonic()

    # 1. MinerU layout analysis
    logger.info("Step 1: Running MinerU layout analysis on %s", pdf_path)
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

    ocr_engine.set_pdf_path(pdf_path)
    ocr_engine._ensure_initialized()
    _markdown = ocr_engine._convert_pdf(pdf_path)

    middle_json = ocr_engine.get_layout_data()
    if middle_json is None:
        raise RuntimeError("MinerU did not produce layout data (middle_json). Is MinerU v2.x installed?")

    t1 = time.monotonic()
    logger.info("MinerU analysis done in %.1fs", t1 - t0)

    # 2. Detect question regions
    logger.info("Step 2: Detecting question regions")
    detector = QuestionRegionDetector()
    regions = detector.detect(middle_json)

    if not regions:
        logger.warning("No question regions detected in %s", pdf_path)
        return CroppedExam(
            exam_info=ExamInfo(title=Path(pdf_path).stem),
            questions=[],
            crop_metrics={"mineru_time": t1 - t0, "total_time": time.monotonic() - t0},
        )

    t2 = time.monotonic()
    logger.info("Detected %d questions in %.1fs", len(regions), t2 - t1)

    # 3. Crop question images
    logger.info("Step 3: Cropping %d question images at %d DPI", len(regions), dpi)
    cropper = QuestionCropper(pdf_path, dpi=dpi)
    questions = cropper.crop_regions(regions, output_dir=output_dir)

    t3 = time.monotonic()
    logger.info("Cropping done in %.1fs", t3 - t2)

    # 4. Generate explanations (optional)
    if add_explanations:
        logger.info("Step 4: Generating explanations via Gemini Vision")
        explainer = QuestionExplainer(llm_name=llm_name)
        questions = explainer.add_explanations(questions)
        t4 = time.monotonic()
        logger.info("Explanations done in %.1fs", t4 - t3)

    total_time = time.monotonic() - t0
    logger.info("Pipeline complete: %d questions in %.1fs", len(questions), total_time)

    return CroppedExam(
        exam_info=ExamInfo(title=Path(pdf_path).stem),
        questions=questions,
        total_questions=len(questions),
        crop_metrics={
            "mineru_time": round(t1 - t0, 1),
            "detection_time": round(t2 - t1, 1),
            "crop_time": round(t3 - t2, 1),
            "total_time": round(total_time, 1),
            "dpi": dpi,
        },
    )
