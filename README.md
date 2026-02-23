# Exam PDF Parser

한국 수능/모의고사 PDF를 **MinerU + Gemini Pro** 3계층 파이프라인으로 파싱하여 구조화된 JSON을 생성하는 도구입니다. CLI와 FastAPI 웹 서비스를 모두 지원합니다.

## 주요 기능

- **3-Layer 파이프라인**: MinerU 딥러닝 OCR → Gemini Pro LLM 구조화 → 자동 검증
- **22가지 문제 유형 지원**: 듣기, 서술형, 오류수정, 배열, 문장전환 등
- **검증 시스템**: 스키마 완전성, 번호 연속성, 선지, 듣기(1-17번), 그룹 문제, 콘텐츠 품질
- **정답지 대조 평가**: 커버리지, 지문 유사도, 선지 정확도, 문제 텍스트 유사도 가중 평가
- **FastAPI 웹 서비스**: 동기/비동기 파싱 API, 대시보드 UI
- **상용화 기반**: API 키 인증, Rate limiting, Docker 배포

## 아키텍처

```
PDF File
  │
  ▼
┌─────────────────────────────────────────────────┐
│  Layer 1: MinerU v2 — 딥러닝 OCR + 레이아웃 분석   │
│  (Korean 최적화, MM Markdown 출력)                │
└──────────────────────┬──────────────────────────┘
                       │ Markdown + 이미지/표
                       ▼
┌─────────────────────────────────────────────────┐
│  Layer 2: Gemini 3 Pro — LLM 구조화               │
│  (Question/Choice/ExamInfo → Pydantic JSON)      │
└──────────────────────┬──────────────────────────┘
                       │ ParsedExam
                       ▼
┌─────────────────────────────────────────────────┐
│  Layer 3: Validator — 구조적 검증                  │
│  (스키마, 번호, 선지, 듣기, 그룹, 콘텐츠 품질)       │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
              구조화된 JSON 출력
         (ParsedExam + ValidationResult)
```

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

> **GPU 참고**: MinerU는 PyTorch 기반으로, CUDA GPU가 있으면 자동으로 GPU를 사용합니다. GPU 없이도 CPU 모드로 정상 작동하지만, OCR 속도가 약 3배 느려집니다.

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
uv pip install "mineru[core]"  # MinerU 전체 의존성 (torch, doclayout-yolo 등)

# 웹 서버 포함 설치
uv pip install -e ".[web]"

# 전체 설치
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
GOOGLE_API_KEY=your_gemini_api_key_here  # 필수
```

## 빠른 시작

### CLI 사용법

```bash
# 사용 가능한 모델 목록
python main.py --list-models

# OCR 엔진 상태 확인
python main.py --list-ocr

# PDF 파싱
python main.py exam.pdf -m mineru+gemini-3-pro-preview -o output/result.json

# 검증 포함 파싱 (정답지 비교)
python main.py exam.pdf -m mineru+gemini-3-pro-preview --validate --answer-key test/answer.md
```

### Full Flow 파이프라인

```bash
# 기본 실행
python scripts/full_flow.py path/to/exam.pdf

# 모델 지정
python scripts/full_flow.py exam.pdf --model mineru+gemini-3-pro-preview --llm_name gemini-3-pro-preview

# 출력 디렉토리 지정
python scripts/full_flow.py exam.pdf -o output/my_results/
```

### 배치 처리

```bash
# 8개 워커로 병렬 처리
python scripts/batch_parser.py ./exams/ -m mineru+gemini-3-pro-preview -w 8 -o results/
```

## 웹 서비스

### 로컬 실행

```bash
uv pip install -e ".[web]"
uvicorn src.server:app --host 0.0.0.0 --port 8000
```

### API 엔드포인트

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/parse` | 동기 PDF 파싱 (5페이지 이하 권장) |
| POST | `/api/parse/async` | 비동기 파싱 → job_id 반환 |
| GET | `/api/jobs/{job_id}` | 작업 상태 조회 |
| GET | `/api/models` | 사용 가능 모델 목록 |
| POST | `/api/validate` | ParsedExam JSON 검증 |
| GET | `/health` | 헬스 체크 |

### 사용 예시

```bash
# 동기 파싱
curl -X POST http://localhost:8000/api/parse \
  -F "file=@exam.pdf" \
  -F "model=mineru+gemini-3-pro-preview"

# 비동기 파싱
curl -X POST http://localhost:8000/api/parse/async \
  -F "file=@exam.pdf" \
  -F "model=mineru+gemini-3-pro-preview"

# 작업 상태 확인
curl http://localhost:8000/api/jobs/{job_id}
```

### 인증

`API_KEYS` 환경 변수 설정 시 `X-API-Key` 헤더 또는 `api_key` 쿼리 파라미터로 인증 필요. 미설정 시 인증 비활성화 (개발 모드).

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/models
```

## Docker 배포

```bash
# 빌드
docker build -t exam-parser .

# 실행
docker run -p 8000:8000 -e GOOGLE_API_KEY=your-key exam-parser

# docker-compose (프로덕션)
docker compose up -d
```

`docker-compose.yml`에서 Rate limiting, CORS, 워커 수 등 설정 가능:

```env
API_KEYS=key1,key2,key3
RATE_LIMIT_PER_MINUTE=60
MAX_CONCURRENT_PARSES=10
CORS_ORIGINS=https://your-frontend.com
UVICORN_WORKERS=2
```

## 토큰 사용량 및 비용

### LLM 가격

| 모델 | 입력 ($/1M tokens) | 출력 ($/1M tokens) | 시험지당 예상 비용 |
|------|:-----------------:|:-----------------:|:----------------:|
| `gemini-3-pro-preview` | $1.25 | $10.00 | **~$0.15** |

### 토큰 사용량 (8페이지 시험지 기준)

| 단계 | 입력 토큰 | 출력 토큰 |
|------|:--------:|:--------:|
| MinerU → Gemini 구조화 (Layer 2) | ~50,000 | ~8,000 |

## 프로젝트 구조

```
exam-pdf-parser/
├── main.py                  # CLI 진입점
├── pyproject.toml           # UV/pip 패키지 설정
├── Dockerfile               # 멀티스테이지 프로덕션 빌드
├── docker-compose.yml       # 프로덕션 배포 설정
├── .env.example             # 환경 변수 템플릿
├── src/
│   ├── parser.py            # 파싱 오케스트레이터 (ExamParser)
│   ├── pdf_parser.py        # PDF → 이미지 변환 (PyMuPDF)
│   ├── schema.py            # Pydantic 데이터 모델 (22개 문제 유형)
│   ├── prompt.py            # LLM 프롬프트 (수능 듣기 전용 섹션 포함)
│   ├── config.py            # 모델/가격/환경 설정
│   ├── validator.py         # 파싱 결과 검증 (Layer 3)
│   ├── evaluator.py         # 정답지 대조 평가
│   ├── explainer.py         # 해설 생성 모듈
│   ├── server.py            # FastAPI 웹 서비스
│   ├── auth.py              # API 키 인증
│   ├── rate_limit.py        # Rate limiting
│   ├── cli.py               # CLI 인터페이스
│   ├── static/              # 대시보드 UI
│   ├── models/
│   │   ├── base.py          # ModelClient ABC
│   │   ├── hybrid_client.py # OCR+LLM 하이브리드 클라이언트
│   │   └── _utils.py        # 유틸리티
│   └── ocr/
│       ├── base.py          # OCREngine ABC
│       └── mineru_ocr.py    # MinerU v2 엔진
├── scripts/
│   ├── full_flow.py         # Full Flow 파이프라인
│   ├── batch_parser.py      # 대량 PDF 배치 처리
│   ├── benchmark.py         # 성능 벤치마크
│   ├── run_comparison.py    # 모델 비교 도구
│   └── validate.py          # 검증 스크립트
└── test/                    # 테스트 PDF 및 정답 데이터
```

## 데이터 모델

### ParsedExam 구조

```json
{
  "exam_info": {
    "title": "2025학년도 9월 고3 모의고사 영어",
    "year": 2025,
    "month": 9,
    "grade": 3,
    "subject": "영어",
    "total_questions": 45
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
      "vocabulary_notes": [],
      "has_image": false,
      "has_table": false,
      "group_range": null
    }
  ]
}
```

### 문제 유형 (22종)

| 유형 | 설명 | 유형 | 설명 |
|------|------|------|------|
| 듣기 | 듣기 평가 (1-17번) | 주제/요지 | 주제/요지 파악 |
| 어휘 | 어휘 문제 | 제목 | 제목 추론 |
| 문법 | 문법 문제 | 심경변화 | 심경 변화 |
| 목적 | 글의 목적 | 주장 | 필자 주장 |
| 함의 | 함의 추론 | 빈칸 | 빈칸 추론 |
| 순서 | 문장 순서 | 삽입 | 문장 삽입 |
| 요약 | 요약문 완성 | 무관한문장 | 무관한 문장 |
| 지칭 | 지칭 추론 | 내용일치 | 내용 일치/불일치 |
| 도표 | 도표/그래프 | 장문 | 장문 독해 |
| 서술형 | 주관식 | 오류수정 | 오류 수정 |
| 배열 | 문장 배열 | 문장전환 | 문장 전환 |

## MinerU OCR 설정

환경 변수로 MinerU 동작을 커스터마이즈할 수 있습니다:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MINERU_LANGUAGE` | `korean` | OCR 언어 (`korean`, `en`, `ch`, `japan`) |
| `MINERU_PARSE_METHOD` | `auto` | `auto` (자동 감지), `ocr` (강제 OCR), `txt` (텍스트만) |
| `MINERU_FORMULA_ENABLE` | `true` | 수식 감지 — 비수학 시험은 비활성화 권장 |
| `MINERU_TABLE_ENABLE` | `true` | 표 감지 — 어휘/문법 표 포함 시험은 활성화 유지 |
| `MINERU_MAKE_MODE` | `mm_markdown` | `mm_markdown` (전체), `nlp_markdown` (텍스트만) |

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
- Python 3.12, 모던 3.12+ 문법 사용 (`X | Y` union, `match` 등)
- 한국어/영어 이중 언어 주석
- Google-style docstrings

### 확장

**새 OCR 엔진 추가**: `OCREngine`(`src/ocr/base.py`) 서브클래스 → `set_pdf_path()` + `extract_from_pdf()` 구현 → `OCR_ENGINES`(`src/ocr/__init__.py`)에 등록

**새 LLM 추가**: `_LLM_PRICING`(`src/config.py`)에 가격 추가 → `_LLM_BACKENDS`에 등록 → `hybrid_client.py`에 `_call_*` 구현

## 라이선스

MIT License
