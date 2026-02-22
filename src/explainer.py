"""
Explanation generation module for parsed exam questions.
LLM을 사용하여 시험 문제의 해설을 생성합니다.
"""

import json
import logging

from .config import get_settings
from .schema import ParsedExam, Question, QuestionType

logger = logging.getLogger(__name__)


def _should_explain(q: Question) -> bool:
    """Return True if we can generate a meaningful explanation for this question."""
    if q.question_type == QuestionType.LISTENING:
        return False
    if not q.passage and not q.choices:
        return False
    return True


def _build_prompt(questions: list[Question]) -> str:
    """Build a single batched Korean explanation prompt for a list of questions."""
    lines = [
        "다음 시험 문제들에 대한 해설을 JSON 형식으로 작성해 주세요.",
        "각 문제마다 다음 항목을 포함하세요:",
        "  1. 정답 근거 (answer rationale)",
        "  2. 핵심 문법/어휘 포인트 (key grammar/vocabulary points)",
        "  3. 오답 분석 (wrong answer analysis for MCQ, if applicable)",
        "",
        "응답 형식 (JSON array, 문제 번호 순서대로):",
        '[{"number": <문제번호>, "explanation": "<해설 텍스트>"}, ...]',
        "",
        "문제 목록:",
        "",
    ]

    for q in questions:
        lines.append(f"### 문제 {q.number}")
        if q.question_type:
            lines.append(f"유형: {q.question_type.value}")
        lines.append(f"문제: {q.question_text}")
        if q.passage:
            lines.append(f"지문:\n{q.passage}")
        if q.choices:
            lines.append("선택지:")
            for c in q.choices:
                lines.append(f"  {c.number}. {c.text}")
        lines.append("")

    return "\n".join(lines)


def add_explanations(parsed_exam: ParsedExam, llm_name: str = "gemini-3-pro-preview") -> ParsedExam:
    """Generate explanations for exam questions using an LLM and return an updated ParsedExam.

    Args:
        parsed_exam: The parsed exam to add explanations to.
        llm_name: LLM model name to use (currently only Gemini supported).

    Returns:
        A new ParsedExam with explanation fields populated where possible.
    """
    try:
        from google import genai
    except ImportError:
        logger.error("google-genai package not installed. Run: pip install google-genai")
        return parsed_exam

    settings = get_settings()
    if not settings.GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not set; cannot generate explanations.")
        return parsed_exam

    # Identify questions we can explain
    explainable = [q for q in parsed_exam.questions if _should_explain(q)]
    if not explainable:
        logger.info("No explainable questions found.")
        return parsed_exam

    # Build explanation map from LLM response
    explanation_map: dict[int, str] = {}
    try:
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        prompt = _build_prompt(explainable)

        response = client.models.generate_content(
            model=llm_name,
            contents=prompt,
            config={"temperature": 0.3, "max_output_tokens": 8192},
        )

        if not response.text:
            logger.warning("Gemini returned empty response for explanations (possibly blocked by safety filters)")
            return parsed_exam

        raw = response.text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        entries = json.loads(raw)
        for entry in entries:
            num = entry.get("number")
            exp = entry.get("explanation", "").strip()
            if num and exp:
                explanation_map[num] = exp

    except Exception as exc:
        logger.warning("Explanation generation failed: %s", exc)
        return parsed_exam

    # Rebuild questions with explanations filled in
    updated_questions = []
    for q in parsed_exam.questions:
        if q.number in explanation_map:
            updated_questions.append(q.model_copy(update={"explanation": explanation_map[q.number]}))
        else:
            updated_questions.append(q)

    return parsed_exam.model_copy(update={"questions": updated_questions})
