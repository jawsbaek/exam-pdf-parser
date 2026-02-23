"""
Pydantic models for structured output.
시험 문제 파싱 결과를 위한 데이터 스키마 정의.
"""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TypedDict
else:
    try:
        from typing_extensions import TypedDict  # pydantic requires this on Python < 3.12
    except ImportError:
        from typing import TypedDict

from pydantic import BaseModel, Field, model_validator


class QuestionType(str, Enum):
    """시험 문제 유형 (Korean exam question types + general fallback)"""

    LISTENING = "듣기"
    VOCABULARY = "어휘"
    GRAMMAR = "문법"
    MAIN_IDEA = "주제/요지"
    TITLE = "제목"
    MOOD_CHANGE = "심경변화"
    PURPOSE = "목적"
    CLAIM = "주장"
    IMPLICATION = "함의"
    BLANK_FILL = "빈칸"
    ORDER = "순서"
    INSERT = "삽입"
    SUMMARY = "요약"
    IRRELEVANT = "무관한문장"
    REFERENCE = "지칭"
    CONTENT_MATCH = "내용일치"
    GRAPH_TABLE = "도표"
    LONG_PASSAGE = "장문"
    OTHER = "기타"
    WRITING = "서술형"
    ERROR_CORRECTION = "오류수정"
    REARRANGE = "배열"
    REWRITE = "문장전환"


class ExamType(str, Enum):
    """Detected exam format type."""

    CSAT = "수능"           # Korean CSAT (수학능력시험)
    MOCK_EXAM = "모의고사"   # Mock exam (모의평가)
    WORKBOOK = "워크북"      # Practice workbook / final test
    OTHER = "기타"          # Unknown / other format


class VocabularyNote(BaseModel):
    """어휘 주석 (별표로 표시된 단어와 한글 뜻)"""

    word: str
    meaning: str


class Choice(BaseModel):
    """객관식 선택지"""

    number: int
    text: str


class Question(BaseModel):
    """개별 시험 문제"""

    number: int
    question_text: str = Field(description="The question prompt in Korean")
    question_type: QuestionType | None = None
    passage: str | None = Field(None, description="English passage/stimulus text")
    choices: list[Choice] = Field(default_factory=list)
    points: int = Field(default=2, description="Point value, typically 2 or 3")
    vocabulary_notes: list[VocabularyNote] = Field(
        default_factory=list, description="Vocabulary notes with Korean meanings (marked with *)"
    )
    has_image: bool = False
    has_table: bool = False
    image_description: str | None = None
    sub_questions: list[str] | None = Field(None, description="For grouped questions like [43~45]")
    group_range: str | None = Field(None, description="e.g. '43~45' for grouped questions")
    explanation: str | None = Field(None, description="해설/풀이 (explanation for this question)")


class ExamInfo(BaseModel):
    """시험 메타데이터"""

    title: str
    year: int | None = None
    month: int | None = None
    grade: int | None = None
    subject: str = ""
    total_questions: int | None = None
    exam_type: ExamType | None = None


class ParsedExam(BaseModel):
    """파싱된 전체 시험"""

    exam_info: ExamInfo
    questions: list[Question]

    @model_validator(mode="after")
    def _sync_total_questions(self) -> "ParsedExam":
        if self.questions:
            self.exam_info.total_questions = len(self.questions)
        return self


class AnswerEntry(BaseModel):
    """Ground truth entry for a single question."""

    number: int
    question_text: str
    passage: str | None = None
    choices: list[Choice] = []
    points: int = 2


class AnswerKey(BaseModel):
    """Ground truth answer key."""

    entries: list[AnswerEntry]


class OCRMetrics(TypedDict):
    """Metrics collected from the OCR/document parser engine."""

    engine: str
    init_time_seconds: float
    ocr_time_seconds: float
    total_time_seconds: float


class ParseResult(BaseModel):
    """파싱 결과 및 메트릭"""

    model_name: str
    parsed_exam: ParsedExam
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_cost_usd: float = 0.0
    parsing_time_seconds: float = 0.0
    pages_processed: int = 0
    ocr_metrics: OCRMetrics | None = None
    error: str | None = None
