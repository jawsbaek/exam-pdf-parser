"""
DeepSeek OCR engine.
DeepSeek-OCR / DeepSeek-OCR-2 를 사용한 문서 OCR.
Transformer 기반 Vision-Language 모델로, 문서를 Markdown으로 변환합니다.
CUDA GPU가 필요합니다 (flash-attention 권장).
"""

import os
import tempfile

from PIL import Image

from .base import OCREngine, _check_import


class DeepSeekOCREngine(OCREngine):
    """
    DeepSeek-OCR: Vision-Language model for document OCR.

    Converts document images to structured Markdown text.
    Supports two modes:
    - "markdown": Layout-preserving Markdown conversion (default)
    - "free": Free OCR without layout analysis

    Requires: transformers, torch, einops, addict, easydict
    Optional: flash-attn (for faster inference on CUDA)
    """

    MODELS = {
        "deepseek-ocr": "deepseek-ai/DeepSeek-OCR",
        "deepseek-ocr-2": "deepseek-ai/DeepSeek-OCR-2",
    }

    def __init__(self, model_variant: str = "deepseek-ocr-2", mode: str = "markdown"):
        super().__init__(name="deepseek-ocr", languages=["en", "ko", "zh"])
        self._model = None
        self._tokenizer = None
        self._model_variant = model_variant
        self._model_name = self.MODELS.get(model_variant, model_variant)
        self._mode = mode
        self._device = None

    def _initialize(self):
        import torch
        from transformers import AutoModel, AutoTokenizer

        # Determine device
        if torch.cuda.is_available():
            self._device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self._device = "mps"
        else:
            self._device = "cpu"

        # Determine attention implementation
        attn_impl = "eager"
        if self._device == "cuda":
            try:
                import flash_attn  # noqa: F401
                attn_impl = "flash_attention_2"
            except ImportError:
                attn_impl = "sdpa"

        import warnings
        warnings.warn(
            f"Loading {self._model_name} with trust_remote_code=True. "
            "Only use models from trusted sources.",
            stacklevel=2,
        )

        self._tokenizer = AutoTokenizer.from_pretrained(
            self._model_name, trust_remote_code=True
        )

        load_kwargs = {
            "trust_remote_code": True,
            "use_safetensors": True,
        }
        if attn_impl != "eager":
            load_kwargs["_attn_implementation"] = attn_impl

        self._model = AutoModel.from_pretrained(self._model_name, **load_kwargs)
        self._model = self._model.eval()

        if self._device == "cuda":
            import torch as _torch
            self._model = self._model.to(_torch.bfloat16).cuda()
        elif self._device == "mps":
            self._model = self._model.to("mps")

    def _get_prompt(self) -> str:
        if self._mode == "free":
            return "<image>\nFree OCR. "
        return "<image>\n<|grounding|>Convert the document to markdown. "

    def _extract_from_image(self, image: Image.Image) -> str:
        """
        Extract text from a single PIL Image using DeepSeek-OCR.
        The model's infer() method requires a file path, so we save
        the image to a temp file first.
        """
        # Save image to temp file (model.infer requires file path)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.save(tmp, format="PNG")
            tmp_path = tmp.name

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Use appropriate size settings based on model variant
                if "ocr-2" in self._model_variant:
                    base_size, image_size = 1024, 768
                else:
                    base_size, image_size = 1024, 640

                result = self._model.infer(
                    self._tokenizer,
                    prompt=self._get_prompt(),
                    image_file=tmp_path,
                    output_path=tmp_dir,
                    base_size=base_size,
                    image_size=image_size,
                    crop_mode=True,
                    save_results=False,
                )

                # Result may be a string or dict depending on version
                if isinstance(result, str):
                    return result
                elif isinstance(result, dict):
                    return result.get("text", result.get("markdown", str(result)))
                elif isinstance(result, list):
                    return "\n".join(str(r) for r in result)
                else:
                    return str(result)
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def is_available() -> bool:
        return _check_import("transformers", "torch", "PIL")
