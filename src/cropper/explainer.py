"""
Question explanation generator using Gemini Vision.
크롭된 문제 이미지를 Gemini에 보내 해설을 생성합니다.
"""

import logging
from pathlib import Path

from ..schema import CroppedQuestion

logger = logging.getLogger(__name__)

_EXPLANATION_PROMPT = """이 시험 문제 이미지를 분석하고 해설을 작성하세요.

## 요구사항
- 문제 번호: {q_num}번
- 한국어로 해설 작성
- 정답 근거를 지문에서 찾아 설명
- 오답 선택지가 왜 틀린지 간략히 설명
- 핵심 어휘/문법 포인트 정리

## 출력 형식
### 정답: [번호]
### 해설
[상세 해설]
### 핵심 포인트
- [포인트 1]
- [포인트 2]
"""


class QuestionExplainer:
    """Generate explanations for cropped question images using Gemini Vision."""

    def __init__(self, llm_name: str = "gemini-3-pro-preview"):
        self._llm_name = llm_name
        self._client = None
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    def _ensure_client(self):
        """Lazy-init the Gemini client."""
        if self._client is not None:
            return
        from google import genai

        self._client = genai.Client()

    def explain_question(self, question: CroppedQuestion) -> str:
        """
        Send a cropped question image to Gemini and get an explanation.

        Args:
            question: CroppedQuestion with image_path set

        Returns:
            Explanation text
        """
        self._ensure_client()
        from google.genai.types import GenerateContentConfig, Part

        prompt = _EXPLANATION_PROMPT.format(q_num=question.question_number)

        # Read image bytes from file
        img_path = Path(question.image_path)
        if not img_path.exists():
            logger.warning("Image not found for question %d: %s", question.question_number, img_path)
            return ""

        img_bytes = img_path.read_bytes()
        image_part = Part.from_bytes(data=img_bytes, mime_type="image/png")

        response = self._client.models.generate_content(
            model=self._llm_name,
            contents=[image_part, prompt],
            config=GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=2048,
            ),
        )

        if response.usage_metadata:
            self._total_input_tokens += response.usage_metadata.prompt_token_count or 0
            self._total_output_tokens += response.usage_metadata.candidates_token_count or 0

        return response.text or ""

    def add_explanations(self, questions: list[CroppedQuestion]) -> list[CroppedQuestion]:
        """
        Add explanations to all cropped questions.

        Args:
            questions: List of CroppedQuestion with image_path set

        Returns:
            Same list with explanation field populated
        """
        for q in questions:
            if not q.image_path:
                logger.warning("Question %d has no image_path, skipping explanation", q.question_number)
                continue
            try:
                q.explanation = self.explain_question(q)
                logger.info("Generated explanation for question %d", q.question_number)
            except Exception:
                logger.exception("Failed to generate explanation for question %d", q.question_number)
                q.explanation = None
        return questions

    def get_token_usage(self) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) totals."""
        return self._total_input_tokens, self._total_output_tokens
