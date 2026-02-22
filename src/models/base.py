"""
Base class for LLM model clients.
모든 모델 클라이언트의 기본 인터페이스를 정의합니다.
"""

from abc import ABC, abstractmethod

from ..schema import ParsedExam


class ModelClient(ABC):
    """Base class for all model clients"""

    def __init__(self, model_name: str):
        """
        Initialize model client.

        Args:
            model_name: Name of the model to use
        """
        self.model_name = model_name
        self.input_tokens = 0
        self.output_tokens = 0

    @abstractmethod
    def parse_exam(
        self,
        images: list[tuple[bytes, str]],
        instruction: str | None = None
    ) -> ParsedExam:
        """
        Parse exam PDF images into structured data.

        Args:
            images: List of (image_bytes, mime_type) tuples
            instruction: Optional custom instruction prompt

        Returns:
            ParsedExam object
        """
        pass

    def set_pdf_path(self, pdf_path: str) -> None:
        """Set PDF path for engines that support direct PDF processing. Override in subclass."""
        pass

    def _add_tokens(self, input_t, output_t):
        """Accumulate token counts, treating None as 0."""
        self.input_tokens += input_t or 0
        self.output_tokens += output_t or 0

    def get_token_usage(self) -> tuple[int, int]:
        """
        Get token usage statistics.

        Returns:
            Tuple of (input_tokens, output_tokens)
        """
        return (self.input_tokens, self.output_tokens)

