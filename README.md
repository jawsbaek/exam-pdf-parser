# Exam PDF Parser

한국 시험지 PDF를 **MinerU + Gemini** 파이프라인으로 파싱하여 구조화된 JSON과 해설을 자동 생성하는 도구입니다.

## 주요 기능

- **3-Layer 하이브리드 파이프라인**: MinerU 딥러닝 OCR → Gemini LLM 구조화 → 자동 해설 생성
- **49문제 파싱, 48문제 해설 생성** (98% 커버리지) 실증 완료
- **10개 문서 파서 x 3개 LLM** = 30가지 모델 조합 지원
- **듣기 문제 자동 감지 및 스킵**
- **JSON + Markdown 듀얼 출력**
- **배치 처리**: 최대 8개 워커 병렬 처리 지원

## 아키텍처

```
PDF File
  │
  ▼
┌─────────────────────────────────────────────────┐
│  Layer 1: MinerU v2 — 딥러닝 OCR + 레이아웃 분석   │
│  (933 OCR regions, ~170초/8페이지 PDF)            │
└──────────────────────┬──────────────────────────┘
                       │ Markdown + 이미지 좌표
                       ▼
┌─────────────────────────────────────────────────┐
│  Layer 2: Gemini Flash/Pro — LLM 구조화           │
│  (Question/Choice/ExamInfo → Pydantic JSON)      │
└──────────────────────┬──────────────────────────┘
                       │ ParsedExam (49 questions)
                       ▼
┌─────────────────────────────────────────────────┐
│  Layer 3: Explainer — 해설 생성 (배치 1회 호출)     │
│  (temperature 0.3, max 8192 tokens)              │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
              ┌────────┴────────┐
              │                 │
         JSON 출력         Markdown 요약
    (구조화된 문제+해설)   (사람이 읽는 형식)
```

## 소요 시간

| 단계 | 소요 시간 | 비고 |
|------|----------|------|
| MinerU OCR (Layer 1) | ~170초 | 8페이지 PDF 기준, 933 OCR regions |
| Gemini LLM 구조화 (Layer 2) | ~10-20초 | PDF당 |
| 해설 생성 (Layer 3) | ~15-30초 | 전체 문제 배치 1회 호출 |
| **전체 파이프라인** | **~3-4분** | **시험지 1개 기준** |
| 배치 처리 (8 workers) | ~25-30분 | 시험지 50개 기준 |

> **GPU 가속**: CUDA GPU 사용 시 MinerU OCR이 ~50초로 단축됩니다 (약 3배 빠름).

## 토큰 사용량 및 비용

### LLM 모델별 가격

| 모델 | 입력 ($/1M tokens) | 출력 ($/1M tokens) | 시험지당 예상 비용 |
|------|:-----------------:|:-----------------:|:----------------:|
| `gemini-3-flash-preview` | $0.15 | $3.50 | **~$0.05** |
| `gemini-3-pro-preview` | $1.25 | $10.00 | **~$0.15** |
| `gpt-5.1` | $2.50 | $10.00 | **~$0.20** |

### 토큰 사용량 상세 (8페이지 시험지 기준)

| 단계 | 입력 토큰 | 출력 토큰 |
|------|:--------:|:--------:|
| PDF 구조화 (Layer 2) | ~50,000 | ~8,000 |
| 해설 생성 (Layer 3) | ~5,000 | ~8,000 |
| **합계** | **~55,000** | **~16,000** |

> **비용 예시**: `gemini-3-flash-preview` 기준으로 시험지 100장 파싱+해설 생성 시 약 **$5.00** (약 7,000원).

## 하드웨어 요구 사항

| 항목 | 최소 사양 | 권장 사양 |
|------|----------|----------|
| **CPU** | x86_64 또는 ARM64 | Apple Silicon M1+ / Intel i5+ |
| **RAM** | 8GB | 16GB+ (MinerU 모델 로딩) |
| **GPU** | 불필요 (CPU 모드 지원) | NVIDIA CUDA GPU (MinerU 3배 가속) |
| **디스크** | 5GB (모델 + 의존성) | 10GB+ (캐시 포함) |
| **OS** | macOS 13+, Ubuntu 20.04+ | macOS (Apple Silicon), Ubuntu 22.04+ |
| **Python** | 3.11 | 3.12 |
| **네트워크** | 필수 (Gemini API 호출) | 안정적인 인터넷 연결 |

> **GPU 참고**: MinerU는 PyTorch 기반으로, CUDA GPU가 있으면 자동으로 GPU를 사용합니다. Apple Silicon의 MPS도 부분 지원됩니다. GPU 없이도 CPU 모드로 정상 작동하지만, OCR 속도가 약 3배 느려집니다.

## 설치

### UV 사용 (권장)

```bash
# UV 설치 (아직 없다면)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 프로젝트 클론
git clone https://github.com/jawsbaek/exam-pdf-parser.git
cd exam-pdf-parser

# MinerU 포함 설치 (권장)
uv pip install -e ".[doc-mineru]"

# 전체 설치 (모든 파서 + 개발 도구)
uv pip install -e ".[all]"
```

### pip 사용

```bash
pip install -r requirements.txt
pip install mineru  # MinerU 별도 설치
```

### API 키 설정

```bash
cp .env.example .env
```

`.env` 파일에 다음 키를 설정하세요:

```env
GOOGLE_API_KEY=your_gemini_api_key_here      # 필수 (Gemini 사용)
OPENAI_API_KEY=your_openai_api_key_here      # 선택 (GPT-5.1 사용 시)
ANTHROPIC_API_KEY=your_anthropic_api_key_here # 선택
```

## 빠른 시작

### Full Flow 파이프라인 (PDF 파싱 + 해설 생성)

```bash
# 기본 실행 (내장 테스트 PDF 3개)
python scripts/full_flow.py

# 특정 PDF 파싱
python scripts/full_flow.py path/to/exam.pdf

# MinerU + Gemini 3 Pro 모델 지정
python scripts/full_flow.py exam.pdf --model mineru+gemini-3-pro-preview --llm gemini-3-pro-preview

# 해설 생성 스킵 (파싱만)
python scripts/full_flow.py exam.pdf --skip-explain

# 출력 디렉토리 지정
python scripts/full_flow.py exam.pdf -o output/my_results/
```

### CLI 기본 사용법

```bash
# 사용 가능한 모델 목록
python main.py --list-models

# OCR 엔진 상태 확인
python main.py --list-ocr

# 단일 모델로 파싱
python main.py exam.pdf -m mineru+gemini-3-flash-preview -o output/result.json

# 검증 포함 파싱 (정답 키 비교)
python main.py exam.pdf -m mineru+gemini-3-flash-preview --validate --answer-key test/answer.md
```

### 모델 비교

```bash
python scripts/run_comparison.py exam.pdf \
  --models mineru+gemini-3-flash-preview,mineru+gemini-3-pro-preview \
  --output output/comparison/ \
  --report output/report.md
```

### 배치 처리 (대량 PDF)

```bash
# 8개 워커로 병렬 처리
python scripts/batch_parser.py ./exams/ -m mineru+gemini-3-flash-preview -w 8 -o results/
```

## 지원 모델

모든 모델은 하이브리드 형식: `{문서파서}+{LLM}` (예: `mineru+gemini-3-flash-preview`)

### 문서 파서 (Layer 1)

| 파서 | 유형 | 특징 |
|------|------|------|
| **mineru** | 딥러닝 PDF→Markdown | 레이아웃 분석 + OCR 통합, **권장** |
| **marker** | 딥러닝 PDF→Markdown | 빠른 속도, 좋은 품질 |
| **docling** | 딥러닝 PDF→Markdown | IBM Research 개발 |
| pymupdf-text | 직접 텍스트 추출 | 가장 빠름, 이미지 PDF 불가 |
| tesseract | 전통 OCR | 무료, 널리 사용 |
| easyocr | 전통 OCR | 다국어 지원 |
| paddleocr | 전통 OCR | 중국어/한국어 강점 |
| surya | ML OCR | 다국어 특화 |
| trocr | Transformer OCR | Microsoft 개발, 고정밀 |
| deepseek-ocr | Transformer OCR | 최신 대규모 모델 |

### LLM 백엔드 (Layer 2 & 3)

| LLM | 특징 | 비용 효율 |
|-----|------|----------|
| **gemini-3-flash-preview** | 빠르고 저렴, **권장** | ★★★★★ |
| gemini-3-pro-preview | 고품질, 복잡한 문제에 적합 | ★★★☆☆ |
| gpt-5.1 | OpenAI 최신, 높은 정확도 | ★★☆☆☆ |

> 총 **30개 조합** (10 파서 x 3 LLM). `python main.py --list-models`로 전체 목록 확인.

## 프로젝트 구조

```
exam-pdf-parser/
├── main.py                  # CLI 진입점
├── pyproject.toml           # UV/pip 패키지 설정
├── requirements.txt         # 레거시 pip 의존성
├── .env.example             # API 키 템플릿
├── .python-version          # Python 버전 (3.12)
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI 인터페이스
│   ├── parser.py            # 파싱 오케스트레이터
│   ├── pdf_parser.py        # PDF → 이미지 변환 (PyMuPDF)
│   ├── schema.py            # Pydantic 데이터 모델 (19개 문제 유형)
│   ├── prompt.py            # LLM 프롬프트 템플릿
│   ├── config.py            # 모델/가격 설정
│   ├── explainer.py         # 해설 생성 모듈 (Gemini 배치 호출)
│   ├── evaluator.py         # 정답 비교 평가
│   ├── validator.py         # 파싱 결과 검증
│   ├── models/
│   │   ├── base.py          # ModelClient ABC
│   │   ├── hybrid_client.py # OCR+LLM 하이브리드 파이프라인
│   │   └── _utils.py        # 유틸리티
│   └── ocr/
│       ├── base.py          # OCR 엔진 ABC
│       ├── mineru_ocr.py    # MinerU 엔진
│       ├── marker_ocr.py    # Marker 엔진
│       ├── docling_ocr.py   # Docling 엔진
│       ├── pymupdf_ocr.py   # PyMuPDF 텍스트 추출
│       ├── tesseract_ocr.py # Tesseract OCR
│       ├── easyocr_ocr.py   # EasyOCR
│       ├── paddleocr_ocr.py # PaddleOCR
│       ├── surya_ocr.py     # Surya OCR
│       ├── trocr_ocr.py     # TrOCR (Transformer)
│       └── deepseek_ocr.py  # DeepSeek OCR
├── scripts/
│   ├── full_flow.py         # Full Flow 파이프라인 (파싱+해설)
│   ├── batch_parser.py      # 대량 PDF 배치 처리
│   ├── benchmark.py         # 성능 벤치마크
│   ├── run_comparison.py    # 모델 비교 도구
│   └── validate.py          # 검증 스크립트
├── docs/
│   └── PROGRESS_REPORT.md   # 개발 진행사항 보고서
└── test/                    # 테스트 PDF 및 정답 데이터
```

## 출력 형식

### JSON 출력 예시

```json
{
  "exam_info": {
    "title": "2025학년도 9월 고3 모의고사 영어",
    "year": 2025,
    "month": 9,
    "grade": 3,
    "subject": "영어",
    "total_questions": 29
  },
  "questions": [
    {
      "number": 18,
      "question_text": "다음 글의 목적으로 가장 적절한 것은?",
      "question_type": "목적",
      "passage": "Dear Mr. Anderson, I am writing to...",
      "choices": [
        {"number": 1, "text": "행사 참가를 요청하려고"},
        {"number": 2, "text": "일정 변경을 알리려고"},
        {"number": 3, "text": "감사 인사를 전하려고"},
        {"number": 4, "text": "정보 제공을 요청하려고"},
        {"number": 5, "text": "불만 사항을 전달하려고"}
      ],
      "points": 2,
      "explanation": "1. 정답 근거: 편지의 핵심 표현 'I am writing to invite you'에서 목적을 파악할 수 있습니다.\n2. 핵심 어휘: invite, participate, annual event\n3. 오답 분석: 2번은 일정 변경 관련 표현이 없고..."
    }
  ]
}
```

### Markdown 요약

각 문제별로 문제 텍스트, 지문, 선택지(①②③④⑤), 해설이 포함된 읽기 쉬운 문서가 생성됩니다.

```
## Question 18 [목적] (2점)

**문제:** 다음 글의 목적으로 가장 적절한 것은?

**지문:** Dear Mr. Anderson, I am writing to...

**선택지:**
① 행사 참가를 요청하려고
② 일정 변경을 알리려고
③ 감사 인사를 전하려고
④ 정보 제공을 요청하려고
⑤ 불만 사항을 전달하려고

**해설:** 1. 정답 근거: 편지의 핵심 표현 'I am writing to invite you'에서...
```

## 벤치마크 결과

### 테스트 데이터셋 (모델: `mineru+gemini-3-flash-preview`)

| PDF | 유형 | 페이지 | 추출 문제 수 | 해설 생성 수 | 스킵(듣기) |
|-----|------|:------:|:-----------:|:-----------:|:---------:|
| 2025년 9월 고3 모의고사 영어 | 수능 모의고사 | 8 | 29 | 28 | 1 |
| Hyper4 학생용 28 | 학원 문법 연습 | - | 10 | 10 | 0 |
| Hyper4 학생용 29 | 학원 문법 연습 | - | 10 | 10 | 0 |
| **합계** | | | **49** | **48 (98%)** | **1** |

- **해설 생성률**: 98% (듣기 문제 1개만 자동 스킵)
- **파싱 정확도**: Pydantic 검증 통과 (스키마 완전성, 번호 연속성, 선택지 수)
- **해설 품질**: 정답 근거 + 핵심 문법/어휘 + 오답 분석 3단 구조

### 해설 품질 예시

**문제 31 (빈칸 유형):**
> "Mia read stories ________ her children. / The master showed a nice room ________ us."

**생성된 해설:**
> 1. 정답 근거: 'read'와 'show'는 3형식에서 간접목적어 앞에 전치사 'to'를 취하는 동사입니다.
> 2. 핵심 문법: give, send, show, tell, write, read, teach 등은 'to' 사용
> 3. 오답 분석: 'of'는 ask, 'for'는 buy/make/cook 등과 쓰임

## 개발

```bash
# 개발 의존성 설치
uv pip install -e ".[dev]"

# 코드 포맷팅
black src/ scripts/ --line-length 120

# 린트
ruff check src/ scripts/ --fix

# 테스트
pytest tests/
```

### 코드 스타일

- Line length: 120 (black, ruff)
- Ruff rules: E, F, I, W
- Python 3.12
- 한국어/영어 이중 언어 주석
- Google-style docstrings

## 라이선스

MIT License
