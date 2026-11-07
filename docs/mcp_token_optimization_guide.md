# MCP 토큰 최적화 가이드

MCP(Model Context Protocol) 서버를 여러 개 붙인 에이전트에서 **쓸데없이 새는 토큰**을 줄이는 방법을 정리했습니다.
원인 분석 → 동적 도구 로딩 → 프롬프트 캐싱 → 스키마 경량화 → 페이로드 압축 → 히스토리 컴팩션 → 게이트웨이 아키텍처 → 클라이언트 설정 순서입니다.

- 작성 기준일: **2026-11-07** (모델명·가격·기본값은 이 날짜의 공식 문서 기준)
- 실습 코드: [`pipeline/mcp_token_optimizer.py`](../pipeline/mcp_token_optimizer.py), 테스트: [`tests/test_mcp_optimizer.py`](../tests/test_mcp_optimizer.py)
- 표에 적힌 "측정" 값은 출처와 토크나이저가 다르므로 **절대값보다 비율**로 읽으세요. 같은 조건의 전후 비교는 8.5절 방법으로 직접 재현할 수 있습니다.

---

## 0. 3줄 요약

1. 비용은 `턴 수 × (도구 정의 + 누적 히스토리)`로 늘어납니다. **도구 정의는 매 턴 반복되는 고정비**, 히스토리는 **턴마다 커지는 변동비**입니다.
2. 가장 큰 절감은 **도구를 상시 노출하지 않는 것**에서 나옵니다. 100개 카탈로그를 2~3개로 라우팅하면 정의 토큰이 97% 이상 줄고(2.6절 실측), 정확도까지 올라가는 사례가 보고됩니다(2.2절).
3. 그다음이 **프롬프트 캐시**(반복 접두사 0.1× 과금)와 **도구 결과 요약**(원시 JSON → 표·요약, 5장)입니다. 세 가지는 서로 충돌하지 않고 곱해집니다.

| 기법 | 줄이는 것 | 이 문서의 근거 수치 | 적용 난이도 |
| --- | --- | --- | --- |
| 동적 도구 로딩(툴 검색) | 도구 정의 반복분 | 55k → 8.7k(85%), 46,273 → 843(Claude Code 실측) | 중 |
| 코드 실행 / Code Mode | 정의 + 중간 결과 | 150k → 2k(98.7%), API 2,500개 → ~1,000토큰 | 중~상 |
| 프롬프트 캐싱 | 반복 접두사 비용 | 캐시 읽기 0.1× (Anthropic), 최대 95% 할인(OpenAI) | 하 |
| 스키마 경량화 | 도구당 정의 | 937 → 237토큰(−75%) | 하 |
| 결과 요약·표 변환 | 도구 결과 | 21,021 → 96토큰(요약), 표 변환 −82% | 하 |
| 컨텍스트 편집·컴팩션 | 히스토리 | 오래된 tool_result 삭제, 150k 임계 자동 요약 | 중 |

---

## 1. MCP 토큰 폭증의 원인

### 1.1 도구 정의 오버헤드 — 질문하기 전에 이미 지불하는 비용

MCP 클라이언트는 연결된 모든 서버에 `tools/list`를 보내고, 받은 정의(`name` + `description` + `inputSchema`)를 **매 요청의 `tools` 파라미터에 그대로** 싣습니다. Anthropic 문서는 `tools` 파라미터의 토큰이 "도구 이름·설명·스키마"이며 입력 토큰으로 과금된다고 명시합니다. 즉 사용자가 아무 말도 하기 전에 이미 청구서가 시작됩니다.

실측치는 서버 성격에 따라 크게 갈립니다.

| 측정 대상 | 도구 수 | 정의 토큰 | 도구당 | 출처 |
| --- | --- | --- | --- | --- |
| gopls (Go LSP) | 8 | 878 | 109 | ImportStatic, 2026-10-06 (o200k) |
| terraform-mcp-server v1.3.0 | 9 | 1,718 | 190 | 〃 |
| github-mcp-server v1.14.0 (기본) | 46 | 11,207 | 243 | 〃 |
| github-mcp-server (모든 toolset) | 91 | 23,206 | 255 | 〃 |
| mcp-grafana v1.6.3 | 81 | 20,493 | 253 | 〃 |
| 7개 인기 서버 합계 | 131 | 46,273 | 353 | ContextBolt, 2026-11-05 (Claude Code `/context`) |
| 멀티서버 표준 구성(GitHub·Slack·Sentry·Grafana·Splunk) | — | ~55,000 | — | Anthropic, Tool search 문서 |
| "50개 이상 MCP 도구" 예시 | 50+ | ~72,000 | ~1,400 | Anthropic, Advanced tool use |

토크나이저와 집계 방식이 달라 서로 비교하면 안 되지만, 경향은 일관됩니다. **도구 하나에 200~400토큰, 제품 API를 그대로 미러링한 서버는 800토큰을 넘기도 합니다.** 같은 GitHub 서버라도 toolset을 전부 켜면 46개 → 91개로 늘어 두 배가 됩니다(ContextBolt 실측: 18,870 → 40,447토큰).

토큰이 어디에 몰려 있는지도 측정되어 있습니다.

- ImportStatic: GitHub 서버 46개 도구에서 **inputSchema가 83%, 설명이 12%**
- Nodeflare(2026-10-16): OpenAPI/Pydantic 생성 스타일 `create_issue` 정의 937토큰 중 **inputSchema 64%, description 32%**
- 0-co(2026-03-17): 도구 18종에서 **설명이 40~60%**, 최고/최저 편차 12.5배(`regex` 953 vs `search` 76)

즉 "설명을 짧게 쓰자"만으로는 절반도 못 줄입니다. 스키마에 붙은 `title`·`examples`·`anyOf` 널 유니언 같은 **생성기 부산물**을 걷어내야 합니다(4장).

### 1.2 원시 페이로드 — 도구 결과가 그대로 컨텍스트가 된다

MCP `tools/call`의 결과는 `content`(텍스트·이미지·오디오·리소스 링크·임베디드 리소스) 또는 `structuredContent`(JSON)로 돌아옵니다. 문제는 클라이언트가 이걸 **가공 없이** 모델에 넣는 경우입니다.

- 300건 이슈 목록을 필드 7개로 반환하면 21,021토큰(이 저장소 유틸리티 기준 추정). 이 중 모델이 실제로 쓰는 건 제목·상태 몇 개입니다.
- Anthropic의 예: 2시간 회의 스크립트가 Google Drive → Salesforce로 흐르는 동안 **같은 텍스트가 두 번** 컨텍스트를 통과해 50,000토큰이 추가됩니다.
- Claude Code는 도구 출력이 10,000토큰을 넘으면 경고하고, `MAX_MCP_OUTPUT_TOKENS`를 올리지 않는 한 **25,000토큰에서 자릅니다**(ContextBolt, Claude Code 문서 인용).
- 스펙은 하위 호환을 위해 `structuredContent`와 함께 **직렬화한 JSON을 TextContent로도 반환하도록 권고**합니다. 서버가 이걸 그대로 따르면 같은 데이터가 두 번 실립니다. 클라이언트가 `structuredContent`를 우선하고 텍스트 중복을 버리는 처리가 필요합니다.

### 1.3 히스토리 누적 — 턴마다 전체를 다시 보낸다

Messages API에는 서버 측 상태가 없습니다. **매 턴 이전 대화 전체를 다시 보냅니다.** 도구 호출 결과도 히스토리의 일부이므로, 한 번 들어온 2만 토큰짜리 응답은 대화가 끝날 때까지 매 턴 과금됩니다.

`N`턴 대화, 턴당 도구 정의 `D`, 턴 `i`까지 누적 히스토리 `H_i`라 하면 총 입력 토큰은

```
Total = Σ(i=1..N) (D + H_i) ≈ N·D + N(N+1)/2 · h     (h = 턴당 평균 증가분)
```

- 첫 항 `N·D`는 **고정비**(도구 정의) — 2~4장으로 줄입니다.
- 둘째 항은 `O(N²)` — 히스토리 압축(5~6장) 없이는 대화가 길어질수록 급격히 커집니다.
- 프롬프트 캐싱(3장)은 이 합계의 **단가**를 낮추는 계수로 작용합니다.

### 1.4 숫자로 보는 비용 (Claude Sonnet 5.5, 입력 $2/MTok, 5분 캐시 쓰기 $2.50, 읽기 $0.10)

7개 서버·131개 도구(46,273토큰)를 붙인 채 **21회 요청**하는 대화를 가정합니다.

| 시나리오 | 요청당 입력 | 21회 총액 | A 대비 |
| --- | --- | --- | --- |
| A. 전부 로드 + 캐시 없음 | 46,273 | **$1.944** | — |
| B. 전부 로드 + 프롬프트 캐시 적중 | 46,273 (읽기 0.1×) | $0.208 | −89.3% |
| C. 지연 로딩(지시문 843 + 도구 3개 ≈ 2,343, 가정) + 캐시 없음 | 2,343 | $0.098 | −94.9% |
| D. 지연 로딩 + 캐시 적중 | 2,343 | **$0.0105** | −99.5% |
| E. 코드 실행 모드(≈1,000) + 캐시 없음 | 1,000 | $0.042 | −97.8% |

도구를 쓰지도 않은 대화에서 **턴당 2달러 가까운 고정비**가 사라지는 셈입니다. 캐시(B)와 지연 로딩(C)은 곱해지고(D), 코드 실행(E)은 중간 결과까지 줄이므로 대화가 길수록 격차가 벌어집니다.

> 캐시는 공짜가 아닙니다. 5분 캐시 쓰기는 1.25×, 1시간 캐시 쓰기는 2×입니다. **한 번만 쓰고 끝나는 요청**이나 5분 TTL이 계속 만료되는 사용 패턴에서는 쓰기 프리미엄만 내고 읽기 이득을 못 봅니다(3.4절).

### 1.5 도구가 많을수록 모델이 틀린다

Anthropic은 도구 선택 정확도가 **30~50개를 넘으면 떨어지기 시작**한다고 보고합니다(Tool search 문서). Tool Search Tool을 켰을 때 Opus 4는 49% → 74%, Opus 4.5는 79.5% → 88.1%로 올랐습니다(Advanced tool use). 토큰 절감은 부수 효과이고, **정확도가 주된 이유**인 경우가 많습니다.

---

## 2. 동적 도구 로딩 (Dynamic Tool Loading)

### 2.1 원리: 카탈로그는 밖에, 정의는 필요할 때만

정적 노출은 "모든 도구 설명서를 책상에 펼쳐놓고 일 시작하기"입니다. 동적 로딩은 "색인만 두고, 필요할 때 책장에서 꺼내기"입니다. 구현은 세 층으로 나뉩니다.

1. **메타 도구(router 도구)** — `search_tools(query, limit, detail)` 하나만 상시 노출. 수백 토큰.
2. **점진적 공개(progressive disclosure)** — 검색 결과를 `이름만` → `이름+한 줄 설명` → `전체 스키마`로 단계적으로 확장합니다. Anthropic의 `search_tools` 예시도 `detail` 파라미터로 이 3단계를 제안합니다.
3. **지연 로딩(deferred loading)** — 프로바이더가 지원하면 도구 정의를 요청에서 빼두고, 모델이 검색한 순간에만 확장합니다.

### 2.2 Anthropic Tool Search Tool (서버 측 지연 로딩)

- `tools` 배열에 `tool_search_tool_regex_20251119` 또는 `tool_search_tool_bm25_20251119`를 넣고, 나머지 도구에 `defer_loading: true`를 지정합니다.
- 초기 컨텍스트에는 검색 도구(≈500토큰)와 비지연 도구만 들어갑니다. 검색 결과는 최대 5개(모델이 `limit` 조정)의 `tool_reference` 블록으로 붙고, API가 전체 정의로 확장합니다.
- **캐시 보존**: 지연된 도구는 시스템 프롬프트 접두사에 포함되지 않고, 발견된 정의는 히스토리에 인라인으로 붙습니다. 그래서 도구를 동적으로 추가해도 접두사 캐시가 깨지지 않습니다(3.2절).
- 공식 수치: 50+ MCP 도구 72K → 8.7K(컨텍스트 95% 보존), 정확도 Opus 4.5 79.5% → 88.1%.
- 적용 기준: 도구 10개 이상, 정의 10K토큰 초과, 선택 정확도 저하, MCP 서버 다수(200+ 도구). 도구 10개 미만이고 매 요청 다 쓰면 그냥 정적 노출이 낫습니다.

### 2.3 코드 실행 / Code Mode / Programmatic Tool Calling

도구를 "함수 호출"이 아니라 "코드로 부를 API"로 바꾸는 접근입니다.

- **Anthropic Code execution with MCP(2025-11-04)**: 도구를 파일 트리(`servers/github/getDocument.ts`)로 제시하고 모델이 코드를 씁니다. 필요한 정의만 읽고, 중간 결과는 실행 환경에서 필터링합니다. **150,000 → 2,000토큰(98.7%)**.
- **Programmatic Tool Calling**: 모델이 쓴 스크립트가 여러 도구를 호출하고 결과를 가공한 뒤 최종 출력만 컨텍스트로 돌아옵니다. 평균 43,588 → 27,297(−37%), `tools` 배열에 10~49개가 있는 요청에서 20~40% 절감. 단, 순차 단일 호출 워크플로(τ²-bench)에서는 8% **더 비쌌습니다** — 컨테이너 기동·스크립트 생성 고정비 때문입니다.
- **Cloudflare Code Mode(2025-09-26, 2026-02-20)**: MCP 도구를 TypeScript API로 변환. 서버 측 Code Mode는 `search()` + `execute()` 두 도구 ≈1,000토큰으로 Cloudflare API 2,500개 엔드포인트를 커버합니다. 네이티브 MCP로 만들면 1.17M 토큰(99.9% 절감).

주의: 코드 실행은 **샌드박스·권한·감사** 비용을 동반합니다. "토큰이 아깝다"만으로 도입할 게 아니라, 다단계·대량 결과 워크플로가 실제로 있는지로 판단하세요.

### 2.4 클라이언트 기본값 (2026-11 기준)

| 클라이언트 | 기본 동작 | 시작 시 로드되는 것 | 비고 |
| --- | --- | --- | --- |
| Claude Code 2.1.x | MCP 도구 **지연 로딩 기본** | 도구 이름 + 서버 지시문(지시문 843토큰, 7서버 / 세션 14.2K) | `ENABLE_TOOL_SEARCH` = unset/`true`/`auto`/`false` |
| Codex 0.164 | 도구 지연 + `ALL_TOOLS` 검색 | 사실상 없음(측정: 14,994 = 서버 없을 때와 동일) | `omit_tools_from`, `enabled_tools` |
| VS Code agent mode | 선택된 도구 전부 | 선택분 | **128개/요청 하드 리밋** |
| Cursor | 서버 단위 on/off | 문서에 수치 없음(2025 포럼: 실질 80, 40은 경고) | Customize에서 토글 |
| Claude Desktop | 전 서버 전 도구 로드 | 전부 | 서버 수를 줄이는 게 유일한 수단 |

### 2.5 라우터를 직접 만들 때의 설계 규칙

프로바이더 기능을 못 쓰는 환경(자체 에이전트, 사내 게이트웨이)에서는 직접 만들어야 합니다. [`pipeline/mcp_token_optimizer.py`](../pipeline/mcp_token_optimizer.py)의 `ToolRouter`가 이 규칙의 최소 구현입니다.

1. **어휘 검색 + 의미 검색 하이브리드** — BM25만으로는 "결제 실패 알려줘"와 `post_message` 같은 표현 차이를 못 잇습니다. 임베딩을 섞고(`alpha`), 임베딩이 없으면 키워드 사전(`keywords`)으로 보완합니다. 한국어는 조사 때문에 음절 바이그램으로 토큰화하면 형태소 분석기 없이도 어간이 만납니다.
2. **결정적 정렬** — 점수 동률일 때 이름순으로 고정합니다. 같은 질의에 같은 도구 순서가 나와야 프롬프트 접두사가 안정되고 캐시가 산다(3.2절).
3. **상대 점수 하한** — 1등 대비 55% 미만 후보는 버립니다. 바이그램 충돌("데이터베이스"와 "스택트레이스"의 공통 조각 "이스")로 생기는 오답을 걸러냅니다.
4. **토큰 예산 기반 선택** — `max_tokens`를 넘는 정의는 건너뜁니다. 도구 1등이 900토큰이면 2등을 포기하는 게 낫습니다.
5. **폴백** — 검색이 빈손이면 이름 목록(전체의 2~3%)을 먼저 보여주고 2차 검색을 유도합니다. "도구가 없다"고 답하는 것보다 쌉니다.
6. **라우팅은 리콜 단계** — 상위 후보를 리랭커(작은 모델)로 재정렬하거나, 실행 전 사용자에게 후보를 보여주는 UX가 안전합니다.

### 2.6 이 저장소 예제 측정 (100개 도구 카탈로그)

10개 서버 × 10개 도구(각 6~8개 파라미터, 생성기 부산물 포함) 카탈로그:

```
전체 상시 노출: 38,355 토큰 (도구당 384)
```

| 질의 | 선택된 도구 | 주입 토큰 | 절감 |
| --- | --- | --- | --- |
| 열린 버그 이슈 목록을 GitHub에서 뽑아서 Slack으로 알려줘 | `github__list_issues`, `slack__post_message` | 821 | 97.9% |
| 게시판 DB에서 지난주 가입자 수를 조회해 표로 정리해줘 | `postgres__query` | 406 | 98.9% |
| Notion 데이터베이스에서 진행 중인 작업만 찾아줘 | `notion__query_database` | 372 | 99.0% |
| Sentry에서 결제 에러 스택트레이스 확인해줘 | `sentry__get_event` | 369 | 99.0% |
| 이번 달 AWS 비용 리포트 뽑아줘 | `aws__cost_report` | 409 | 98.9% |
| GitHub PR 리뷰 상태를 확인해서 Slack으로 알려줘 | `slack__post_message`, `github__list_pull_requests` | 781 | 98.0% |

```python
from pipeline.mcp_token_optimizer import ToolRouter, sample_catalog

router = ToolRouter(sample_catalog())          # 또는 실제 tools/list 결과로 만든 ToolSpec 목록
routed = router.route("열린 버그를 Slack으로 알려줘", k=2, min_relative_score=0.55)
print(routed.selected, routed.savings["saved_pct"])   # ['github__list_issues', 'slack__post_message'] 97.9
```

이름만 주입하면(`detail="name"`) 100개 전체가 797토큰입니다. "먼저 이름 목록, 필요하면 스키마" 2단계가 실무에서 가장 균형이 좋습니다.

---

## 3. 프롬프트 캐싱 전략

### 3.1 캐시가 보는 것: 접두사 계층

Anthropic은 `tools` → `system` → `messages` 순서의 **접두사**를 캐시합니다. 한 단계가 바뀌면 그 뒤가 전부 무효입니다.

| 항목 | Anthropic (2026-11 문서) | OpenAI (GPT-5.6+) |
| --- | --- | --- |
| 활성화 | `cache_control: {"type":"ephemeral"}` (자동/명시) | 기본 자동, `prompt_cache_options.mode`로 명시 |
| 최소 길이 | 모델별 512 / 1,024 / 2,048 / 4,096토큰 | 1,024 (GPT-5.6+), 이전 모델은 설정 의존 |
| 쓰기 단가 | 5분 1.25×, 1시간 2× | 30분 1.25×, 12시간 2.5× |
| 읽기 단가 | 0.1× (Opus 5.5·Sonnet 5.5는 0.05×, Fable/Mythos 5.1은 0.025×) | 0.1× (GPT-6.1 Sol/Terra 0.05×) |
| 수명 | 5분(갱신 무료) / 1시간 | 30분 / 12시간 |
| 브레이크포인트 | 최대 4개, 룩백 20블록 | 최대 4개 쓰기 |
| 무효화 | 도구 정의 수정 시 전체, `tool_choice` 변경 시 messages | 접두사 불일치 시 해당 구간 |

주의할 점 두 가지.

- **최소 길이 미달은 조용히 무시**됩니다. `cache_creation_input_tokens`와 `cache_read_input_tokens`가 0이면 캐시되지 않은 것입니다. Sonnet 5.5는 512토큰, Opus 4.5·Haiku 4.5는 4,096토큰처럼 모델별로 다릅니다.
- **캐시 쓰기 프리미엄**이 있습니다. 첫 요청 1.25×(5분), 재사용이 없으면 손해입니다.

### 3.2 MCP 서버를 캐시 친화적으로 만드는 규칙

캐시 적중률은 클라이언트 최적화가 아니라 **서버 구성 문제**인 경우가 많습니다.

1. **도구 순서를 고정하라.** MCP 스펙(2026-07-28)은 서버가 `tools/list`를 **결정적 순서**로 반환하라고 권고합니다. 그 이유로 "클라이언트의 도구 목록 캐싱과 프롬프트 캐시 적중률"을 명시합니다. 서버가 `dict` 순회 순서나 DB 조회 순서에 의존하면 매 요청 접두사가 달라져 캐시가 전멸합니다.
2. **설명에 변하는 값을 넣지 마라.** 타임스탬프, "현재 3개 이슈", 버전 문자열, 사용자 이름이 설명에 들어가면 캐시 키가 매번 달라집니다.
3. **`tools/list` 캐싱 힌트를 활용하라.** 스펙 2026-07-28은 `tools/list`에 `ttlMs`와 `cacheScope`(`public`/`private`)를 붙이게 합니다. 도구 목록이 사용자별로 다르면 `private`, 아니면 `public`으로 게이트웨이가 공유할 수 있게 합니다.
4. **요청마다 도구 집합을 바꾸지 마라.** 필터링으로 `tools` 배열을 턴마다 재구성하면 `tools` 계층이 바뀌어 전체 캐시가 무효가 됩니다. 대신 `defer_loading`으로 접두사를 고정하고 필요한 정의만 히스토리에 붙입니다(2.2절). Anthropic 문서도 "지연 도구는 접두사를 건드리지 않으므로 동적 추가가 캐시를 깨지 않는다"고 명시합니다.
5. **브레이크포인트는 마지막 도구에.** `tools` 배열의 마지막 항목에 `cache_control`을 두면 도구 정의 전체가 하나의 접두사로 캐시됩니다. `mcp_toolset`으로 묶었다면 툴셋 항목에 답니다(내부 순서는 클라이언트가 제어하지 못함).
6. **정적/준정적/동적을 분리하라.** 시스템 프롬프트·도구 정의(정적) → 문서 컨텍스트(준정적) → 대화(동적) 순으로 쌓고, 브레이크포인트를 경계마다 둡니다.
7. **자주 바뀌는 도구는 빼라.** 매 턴 결과가 달라지는 도구(예: 대시보드 상태)는 정의를 고정하고 데이터만 결과로 받으세요.

### 3.3 캐시 vs 지연 로딩: 경쟁이 아니라 보완

| 조합 | 첫 요청 | 이후 턴 | 총액(21턴) |
| --- | --- | --- | --- |
| 전부 로드, 캐시 없음 | 46,273 | 46,273 | $1.944 |
| 전부 로드 + 캐시 | 46,273 쓰기 | 0.1× 읽기 | $0.208 |
| 지연 로딩, 캐시 없음 | 2,343 | 2,343 | $0.098 |
| 지연 로딩 + 캐시 | 2,343 쓰기 | 0.1× 읽기 | $0.0105 |

### 3.4 캐시가 손해인 경우

- 한 번만 호출되는 배치 작업: 쓰기 1.25×만 내고 읽기 0.
- TTL 5분을 넘겨 대화가 띄엄띄엄 이어짐: 매번 쓰기. 1시간 TTL(2×)과 비교해 계산하세요.
- 동시 요청: 첫 응답이 시작되기 전에는 캐시 엔트리가 없습니다. 병렬 요청은 첫 응답 후에 보내야 적중합니다.
- 컨텍스트 편집(`clear_tool_uses`)과 함께 쓸 때: 삭제는 접두사를 바꿔 캐시를 무효화합니다. `clear_at_least`로 한 번에 크게 지워 쓰기 비용을 상쇄하세요(6.2절).

---

## 4. 도구 스키마 경량화 (Tool Schema Pruning)

### 4.1 어디를 잘라야 하는가

측정 결과는 일관됩니다: **inputSchema가 절반~80%**. 그 안에서도 모델이 판단에 쓰지 않는 것들이 차지합니다.

| 요소 | 모델이 쓰는가 | 처리 |
| --- | --- | --- |
| `name`, `description` | 예 (도구 선택의 핵심) | 유지, 단 4문장 이내로 |
| `type`, `required`, `enum`, `format`, `minimum/maximum`, `pattern` | 예 (인자 구성) | 유지 |
| 프로퍼티 `description` | 부분적으로 | 1~2문장으로 절단 |
| `title` (프로퍼티명 반복) | 아니오 | 제거 |
| `examples` | 드물게 | 제거(가장 비싼 축 중 하나) |
| `$schema`, `$id`, `$comment` | 아니오 | 제거 |
| `default: null` + `anyOf [T, null]` | 아니오 (`optional`로 충분) | 평범한 optional로 축약 |
| 중첩 객체의 `title`/`examples` | 아니오 | 재귀 제거 |
| 미사용 파라미터(서버가 무시하는 옵션) | 아니오 | 아예 삭제 |

### 4.2 효과 (측정)

- Nodeflare 재작성 실험: `create_issue` 937 → 838(−10.6%, `$schema`·`title`·`examples` 제거) → 684(−27%, 널 유니언 축약) → 509(−45.7%, 프로퍼티 설명 정리) → **237(−74.7%, 설명 4문장 재작성)**.
- 이 저장소 카탈로그 100개: `prune_tool_definition` 적용 시 38,355 → 28,516(−25.7%, 도구당 384 → 285). 인위적 카탈로그라 부산물이 적어 절감폭이 작습니다. 실제 서버(OpenAPI 생성)에서는 4.1의 항목이 훨씬 많습니다.

```python
from pipeline.mcp_token_optimizer import prune_tool_definition, estimate_json_tokens

slim = prune_tool_definition(raw_def, max_description_chars=200, max_properties=8)
print(estimate_json_tokens(raw_def), "->", estimate_json_tokens(slim))
```

### 4.3 도구 설계 자체를 바꾸기

- **CRUD를 하나로 합칠지 결정하라.** GitHub의 `issue_write`는 create/update를 `method` 인자로 합쳐 도구 슬롯은 아꼈지만, 17개 프로퍼티로 807토큰이 됐습니다. 슬롯 절약과 스키마 증가는 트레이드오프입니다.
- **"언제 쓰지 말라"를 한 줄 넣어라.** 잘못된 호출 1회는 정의 토큰 200개보다 비쌉니다.
- **출력 스키마(`outputSchema`)는 최소로.** 검증용으로만 쓰고, 모델에 보이는 필드는 결과 요약에 필요한 것만.
- **이름에 서버 프리픽스.** 게이트웨이가 합칠 때 `github_create_issue`처럼 충돌을 막습니다(스펙도 프리픽스 같은 구분 전략을 권고).

### 4.4 하지 말 것

- `enum`, `required`, 단위(초/밀리초), 범위를 지우면 호출 오류가 늘고 재시도로 토큰이 더 나갑니다.
- 설명을 기계적으로 잘라 문장이 끊기면 모델이 도구를 오선택합니다. 문장 단위로 자르세요(구현은 `prune_tool_definition`).

---

## 5. 도구 반환 페이로드 최적화

### 5.1 Summary-First 패턴

"전체 몇 건인지 + 앞쪽 몇 건 + 다음에 무엇을 물으면 되는지"를 먼저 돌려주고, 상세는 요청이 있을 때 페이지로 줍니다.

```text
total issues: 300
| id | title | state |
| --- | --- | --- |
| 1000 | Login fails on Android build 0 | closed |
... (5행)
showing 5 of 300. call again with offset=5 (or a narrower filter) for the next page.
```

측정(이 저장소, 300건 × 7필드): **21,021 → 96토큰(−99.5%)**. 모델은 "300건 중 5건"이라는 사실과 페이징 방법을 알기 때문에 다음 행동을 정할 수 있습니다.

### 5.2 포맷 변환: JSON → 표/TSV

같은 데이터라도 키를 반복하지 않으면 토큰이 줄어듭니다.

| 표현 | 토큰 | 원본 대비 |
| --- | --- | --- |
| 원시 JSON(7필드, 300행) | 21,021 | — |
| 마크다운 표(7열, 300행) | 14,447 | −31% |
| 마크다운 표(3열, 300행) | 3,781 | **−82%** |
| TSV(3열, 300행) | **3,174** | **−85%** |
| 요약(3열, 5행 + 페이징 안내) | **96** | **−99.5%** |

- 열이 많아지면 표의 이점이 줄어듭니다. **필드 프로젝션(필요한 열만)** 과 함께 써야 합니다.
- 셀 값이 길면(본문·설명) `max_cell_chars`로 자르고 "전문은 `get_issue(id)`" 식의 포인터를 남깁니다.
- XML/HTML 래퍼는 피하세요. 태그는 순수 오버헤드입니다.

### 5.3 서버·클라이언트 측 사전 필터링

- **서버**: `limit` 기본값을 작게(10~20), `fields` 프로젝션 지원, `cursor` 페이징 필수, 집계 도구(`count`, `group_by`) 제공. "전부 반환"을 기본값으로 두지 마세요.
- **클라이언트/게이트웨이**: `jq` 수준의 필드 선택, `null`/빈 값 제거(`strip_empty`), 중복 래퍼(`data.items[].attributes.*`) 평탄화.
- **실행 환경**(코드 실행·PTC): 10,000행을 코드로 받아 필터·집계하고 **5행만 출력**. Anthropic 예시의 핵심입니다.

### 5.4 페이징 규약

```python
{"total": 300, "offset": 0, "returned": 20, "next_offset": 20, "items": [...]}
```

- `next_offset: null`이 "끝"을 뜻하게 하고, `has_more` 같은 중복 신호를 만들지 않습니다.
- 모델이 같은 페이지를 반복 요청하지 않도록 **현재 위치를 응답 안에** 씁니다.
- 페이지 크기는 도구별로 다르게(목록 20, 로그 100) 두되 스키마 기본값에 명시합니다.

### 5.5 트렁케이션

예산이 정해진 클라이언트(Claude Code 기본 25K)에서는 잘리는 지점이 문제입니다. 앞만 남기면 스택트레이스의 **원인 줄**과 로그의 **마지막 에러**가 사라집니다. 머리와 꼬리를 함께 남기고, 잘린 양과 다음 행동을 마커로 알려주세요.

```
…[truncated 4,120 tokens; request a page/filter for the rest]…
```

### 5.6 흔한 낭비

- `structuredContent`와 동일한 JSON을 `TextContent`로 중복 반환(스펙의 하위 호환 권고) → 클라이언트가 한쪽만 쓰기.
- base64 이미지를 텍스트에 인라인 → 이미지 블록으로 분리, 필요 없으면 썸네일/URI만.
- `null` 범벅, 빈 배열, 메타데이터(`request_id`, `etag`, `rate_limit`) → `strip_empty`·화이트리스트.
- 성공 응답에 요청 전문 에코 → 제거.

---

## 6. 컨텍스트 관리와 히스토리 컴팩션

### 6.1 원칙

턴 3의 도구 결과는 턴 20의 판단에 거의 쓰이지 않습니다. 그런데도 매 턴 다시 과금됩니다. **"원문은 버리고 결론만 남긴다"** 가 원칙입니다. 남길 것은 ① 사용자가 정한 것 ② 확정된 사실(파일 경로, ID, 수치) ③ 다음 단계입니다.

### 6.2 Anthropic의 서버 측 기능

| 기능 | 동작 | 주요 파라미터 |
| --- | --- | --- |
| Tool result clearing (`clear_tool_uses_20250919`) | 오래된 tool_result를 플레이스홀더로 교체 | `trigger`(기본 100K), `keep`(기본 3쌍), `clear_at_least`, `exclude_tools`, `clear_tool_inputs` |
| Thinking block clearing (`clear_thinking_20251015`) | 이전 턴의 사고 블록 정리 | `keep` |
| 서버 측 컴팩션 (`compact_20260112`) | 임계 도달 시 대화를 요약 블록으로 대체 | `trigger` 기본 150K, 최소 50K |

- 두 기능 모두 **서버 측**에서 적용되고 클라이언트는 원문 히스토리를 그대로 유지합니다.
- `clear_at_least`는 "캐시를 깰 만큼 지웠는지"를 보장하는 장치입니다. 조금씩 자주 지우면 캐시 쓰기만 반복됩니다.
- 응답의 `context_management.applied_edits`에서 `cleared_tool_uses`, `cleared_input_tokens`를 확인할 수 있습니다.
- 베타 헤더: `context-management-2025-06-27`.

### 6.3 직접 구현하는 체크포인트 요약

프로바이더 기능을 못 쓰면 클라이언트에서:

1. **N턴마다** 오래된 구간을 요약합니다(예: 8턴 또는 40K토큰).
2. 요약 스키마를 고정합니다: `결정사항 / 산출물 경로 / 미해결 질문 / 다음 단계`. 자유 요약은 매번 형태가 달라 캐시도 깨고 정보도 샙니다.
3. 원문은 워크스페이스 파일이나 DB에 두고 **참조 ID**만 남깁니다. "전문은 `runs/2026-11-07/step3.log`"처럼.
4. 도구 결과는 **들어오는 순간** 요약본+원문 경로 두 개로 저장합니다. 나중에 요약하려고 원문을 다시 읽는 건 두 번 비용을 내는 일입니다.

### 6.4 클라이언트별

| 클라이언트 | 기능 | 비고 |
| --- | --- | --- |
| Claude Code | 자동 컴팩션, `/compact` | 오래된 도구 출력 정리와 함께 동작 |
| Codex | 세션 단위 컨텍스트 관리 | `disabled_tools`로 결과 자체를 줄이는 게 우선 |
| Cline 등 IDE 에이전트 | 자동 컨덴스(auto-condense) | 요약 시점·보존 규칙은 버전별로 다름 |
| 자체 에이전트 | 위 6.3 직접 구현 | Messages API는 상태가 없음을 전제 |

### 6.5 안티패턴

- 매 턴 전체 히스토리를 요약(요약 비용이 원문 비용을 넘음).
- 요약에 원문 코드/로그를 그대로 복사(압축률 0).
- 도구 결과를 "나중에 필요할지도"라며 전부 보존(대부분 필요 없음).
- 컨텍스트 한계에 닿은 뒤에야 정리(이미 늦음 — 70~80%에서 시작).

---

## 7. 아키텍처 패턴과 오픈소스 도구

### 7.1 계층별 책임

```
[LLM 클라이언트]  ── 도구 정의 주입/지연, 프롬프트 캐시, 히스토리 압축
      │  (MCP)
[MCP 게이트웨이/프록시] ── 서버 통합, 도구 allow/deny, 이름 프리픽스, 검색 도구 주입,
      │                    결과 트렁케이션, 응답 캐시, 감사 로그
[개별 MCP 서버] ── 스키마 경량화, 페이징·프로젝션 기본값, 결정적 도구 순서,
                     structuredContent/text 중복 제거
```

토큰은 **세 층 모두**에서 줄일 수 있고, 게이트웨이가 가장 손이 적게 갑니다(클라이언트를 바꾸지 않아도 됨).

### 7.2 게이트웨이가 실제로 하는 일

- **도구 필터링**: 서버 단위·도구 단위 allow/deny. GitHub toolset 46→91개 사례처럼 "전부 켜기"를 막는 것만으로 두 배 차이.
- **중복 제거**: 같은 일을 하는 두 서버(Chrome DevTools + Playwright = 57개 도구, 17,885토큰)를 하나로.
- **검색 도구 주입**: 전체 목록 대신 `find_tool`/`call_tool` 또는 `retrieve_tools`(BM25)만 노출.
- **이름 프리픽스**: `github_create_issue`처럼 충돌 방지(스펙 권고).
- **응답 캐시·압축**: 동일 요청 결과 캐시, 큰 응답 트렁케이션, 민감 필드 마스킹.
- **감사·정책**: 누가 어떤 도구를 얼마나 불렀는지. 토큰 최적화와 보안은 같은 지점에서 만납니다.

### 7.3 오픈소스 비교 (2026-10~11 확인)

| 제품 | 라이선스 | 토큰 관련 기능 | 특징 |
| --- | --- | --- | --- |
| **Docker MCP Gateway** (0.44.x) | MIT | 프로파일별 도구 allowlist, 동적 도구 발견 | 컨테이너 격리, 서명 검증, 시크릿 차단. Docker Desktop/CLI 플러그인 |
| **ToolHive** (v0.55~0.59) | Apache-2.0 | 서버별 `--tools` 필터, vMCP `find_tool`/`call_tool` 옵티마이저, **의미 검색으로 최대 85% 절감 주장(벤더 수치)** | 컨테이너 격리 + egress 프록시, OIDC/Cedar 정책, K8s 오퍼레이터 |
| **mcp-proxy** (joshrotenberg) | — | `expose_tools`/`hide_tools`, BM25 검색 모드, 응답 캐시 | Rust/tower 기반 리버스 프록시, 재시도·서킷브레이커·카나리 |
| **MCPProxy** (v0.71.1) | MIT | `retrieve_tools`(BM25 검색), 에이전트별 프로파일 | 로컬 우선, 도구 정의 해시·변경 검토(rug pull 방지), macOS 메뉴바 |
| **FastMCP** | Apache-2.0 | 미들웨어로 도구 필터·태그·버전 관리 | 파이썬 서버 프레임워크, 서버 측 구현에 적합 |
| **Cloudflare Code Mode SDK** | 오픈소스 | `search()`+`execute()` 2도구 ≈1,000토큰 | 대규모 API를 서버 측에서 코드 모드로 노출 |

선택 기준:

- **개인 개발자**: 클라이언트 기능(Claude Code 지연 로딩, Codex `enabled_tools`) + FastMCP로 서버 스키마 정리. 게이트웨이는 필요할 때.
- **소규모 팀**: MCPProxy 또는 Docker MCP Gateway로 통합·필터·감사.
- **플랫폼/보안 요구**: ToolHive(K8s, SSO, 정책) 또는 사내 게이트웨이.
- **API가 수백~수천 엔드포인트**: 서버 측 Code Mode(2도구)가 유일하게 확장되는 해법.

### 7.4 서버를 직접 쓴다면

1. `tools/list`는 결정적 순서 + `ttlMs`/`cacheScope`.
2. 스키마는 4장 규칙으로 생성 단계에서 정리(수기 편집 금지 — 생성 파이프라인에 넣기).
3. 목록 도구는 `limit`(기본 20)·`fields`·`cursor`를 스키마에 넣고, 응답에 `total`과 `next_offset`.
4. `outputSchema`는 검증용 최소 스키마, `structuredContent`와 텍스트 중복은 클라이언트가 처리.
5. 큰 본문은 `resource_link`(URI)로 넘기고 모델이 필요할 때 `resources/read`. 스펙이 지원하는 정식 경로입니다.
6. 요청 하나에 도구 하나. 다단계 워크플로를 도구 안에 숨기면 모델이 중간 상태를 못 봅니다(코드 모드는 예외).

---

## 8. 클라이언트 설정 팁과 벤치마크

### 8.1 Claude Code

```json
// ~/.claude/settings.json (예시)
{
  "permissions": { "deny": ["mcp__github__*", "mcp__playwright__browser_run_code_unsafe"] }
}
```

- 기본값이 지연 로딩입니다. `ENABLE_TOOL_SEARCH=false`로 끄면 46.3K가 통째로 들어옵니다(측정: 세션 시작 76.8K).
- `auto`는 도구가 컨텍스트의 10%를 넘을 때만 검색을 켭니다. `auto:5`처럼 조정 가능.
- `/context`로 서버별·도구별 토큰을 확인하세요. `claude -p "/context"`로 대화 없이도 볼 수 있습니다.
- 거부 규칙으로 GitHub 도구를 전부 막으면 46.3K → 26.6K로 줄고 목록에서도 사라집니다(측정).
- `MAX_MCP_OUTPUT_TOKENS`로 결과 상한을 조정. 기본 25K.
- 중복 서버(claude.ai 커넥터 + 직접 추가한 같은 서버)를 정리.

### 8.2 Codex

```toml
[mcp_servers.github]
command = "github-mcp-server"
args = ["stdio"]
disabled_tools = ["delete_file", "create_or_update_file"]

[mcp_servers.filesystem]
enabled_tools = ["read_text_file", "list_directory", "search_files"]

[mcp_servers.chrome-devtools]
enabled = false
```

- `omit_tools_from = ["direct"]` 등으로 도구를 어디에 노출할지 제어.
- `codex exec` 로 첫 요청 `input_tokens`를 재면 효과를 바로 볼 수 있습니다(측정: 서버 0개와 7개가 동일 14,994).

### 8.3 VS Code / Cursor / Claude Desktop

- VS Code agent mode: 요청당 **128개** 한도("Cannot have more than 128 tools per request"). 도구 선택기에서 서버 단위로 끄고, 실험적 `github.copilot.chat.virtualTools.threshold`로 그룹화.
- Cursor: 문서에 수치가 없고, 2025년 포럼 기준 실질 80개·40개는 경고. Customize에서 서버 토글.
- Claude Desktop: 전부 로드하므로 **서버 수를 줄이는 것**이 유일한 방법. 5개 서버·50개 도구면 턴당 12K 안팎이 기본으로 나갑니다.

### 8.4 시나리오별 벤치마크 (3.1·3.3절 재정리)

| 시나리오 | 요청당 토큰 | 21턴 비용 | 절감 |
| --- | --- | --- | --- |
| 전부 로드 | 46,273 | $1.944 | — |
| + 프롬프트 캐시 | 46,273(읽기 0.1×) | $0.208 | 89.3% |
| 지연 로딩 | 2,343 | $0.098 | 94.9% |
| 지연 로딩 + 캐시 | 2,343 | $0.0105 | 99.5% |
| 코드 실행 | ~1,000 | $0.042 | 97.8% |

턴 수가 늘수록 격차는 커집니다(1.3절 `O(N²)` 항). 100턴 대화라면 전부 로드+무캐시는 $9.25, 지연 로딩+캐시는 약 $0.03입니다.

### 8.5 측정 방법론 (숫자를 믿기 전에)

- **토크나이저가 다릅니다.** Claude 4.7 이후 모델은 같은 텍스트에 이전 모델보다 약 30% 많은 토큰을 씁니다(Anthropic 고지, Nodeflare 인용). tiktoken(o200k) 수치는 OpenAI 계열 근사치입니다.
- 정확한 값은 provider API로: `POST /v1/messages/count_tokens`(Anthropic)에 `tools` 배열을 넣으면 도구 정의만의 토큰이 나옵니다. 무료입니다.
- 클라이언트 표시값(Claude Code `/context`)은 추정치이며 실행마다 몇 % 흔들립니다.
- 비교는 **같은 질의·같은 도구 집합·같은 토크나이저**로, 최소 10회 반복해 중앙값을 쓰세요.

---

## 9. 적용 체크리스트

**오늘 (30분)**

- [ ] 클라이언트에서 현재 도구 정의 토큰을 측정한다(`/context`, `count_tokens`, 또는 `estimate_json_tokens`).
- [ ] 쓰지 않는 서버·toolset을 끈다. 중복 서버를 찾는다.
- [ ] 지연 로딩/툴 검색이 켜져 있는지 확인한다(Claude Code 기본 on, Codex 기본 on, VS Code 128 한도).

**이번 주**

- [ ] 도구 정의를 스키마 프루닝 파이프라인에 넣는다(생성 단계에서).
- [ ] 목록 도구에 `limit`·`fields`·`cursor` 기본값을 넣고, 결과를 요약+표로 반환한다.
- [ ] 시스템 프롬프트·도구 정의에 변하는 값을 제거해 캐시 적중률을 올린다(응답의 cache_read 확인).
- [ ] 큰 결과 도구에 트렁케이션(머리+꼬리+안내)을 넣는다.

**이번 달**

- [ ] 툴 라우터(또는 게이트웨이)를 도입하고 도구 10개 이상 환경에서 A/B 한다.
- [ ] 히스토리 컴팩션(서버 측 또는 체크포인트 요약)을 넣는다.
- [ ] 코드 실행/Code Mode가 맞는 워크플로(다단계·대량)를 하나 골라 파일럿.
- [ ] 비용 대시보드: 요청당 입력 토큰, 캐시 읽기 비율, 도구별 평균 결과 토큰.

---

## 10. 이 저장소의 예제

```bash
python -m pipeline.mcp_token_optimizer          # 데모(100개 도구, 6개 질의, 페이로드 예시)
python -m unittest tests.test_mcp_optimizer -v  # 51개 테스트
```

제공하는 것:

| 함수/클래스 | 역할 |
| --- | --- |
| `ToolRouter` | BM25(+선택적 임베딩) 라우팅, 결정적 정렬, 상대 점수 하한, 토큰 예산 |
| `ToolSpec.to_definition(detail)` | 이름만 / 이름+설명 / 전체 — 점진적 공개 |
| `build_tool_search_tool` | 메타 도구 스키마(≈112토큰) |
| `prune_schema`, `prune_tool_definition` | JSON Schema 가지치기·설명 절단 |
| `summarize_records`, `to_markdown_table`, `to_tsv` | Summary-First, 표 변환 |
| `paginate`, `truncate_text`, `strip_empty`, `project_fields` | 페이징·트렁케이션·정리 |
| `estimate_tokens`, `payload_report`, `estimate_savings` | 전후 비교 |

한계:

- `estimate_tokens`는 **근사치**입니다(CJK 1자=1, 그 외 4자=1). 청구서에 쓰는 값은 provider API로 확인하세요.
- 라우터는 리콜 단계입니다. 도구가 수천 개거나 설명이 빈약하면 리랭커·임베딩 인덱스가 필요합니다.
- 한국어 바이그램 토큰화는 조사 문제를 줄이지만, "이스" 같은 충돌 조각이 생깁니다. 상대 점수 하한과 키워드 사전으로 보완하고, 정확도가 중요하면 형태소 분석기나 임베딩을 붙이세요.
- 이 모듈은 세션·캐시를 관리하지 않습니다. 실제 비용 절감은 클라이언트 루프(히스토리·캐시 브레이크포인트·컴팩션)와 함께 설계해야 합니다.

---

## 부록 A. 출처

확인일 2026-11-07.

| 주제 | 문서 |
| --- | --- |
| 코드 실행으로 MCP 토큰 98.7% 절감 | https://www.anthropic.com/research/code-execution-with-mcp (2025-11-04) |
| Tool Search Tool, PTC, 정확도 향상 | https://www.anthropic.com/research/advanced-tool-use (2025-11-24) |
| Tool search 레퍼런스(모델 호환, `defer_loading`) | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool |
| PTC 레퍼런스(토큰 절감 조건) | https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling |
| 도구 컨텍스트 4가지 접근 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/manage-tool-context |
| 프롬프트 캐싱(가격·최소 길이·무효화) | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| 도구 정의 캐싱·`defer_loading`과 캐시 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching |
| 컨텍스트 편집(`clear_tool_uses`) | https://platform.claude.com/docs/en/build-with-claude/context-editing |
| 서버 측 컴팩션 | https://platform.claude.com/docs/en/build-with-claude/compaction-threshold |
| MCP 커넥터(툴셋·allowlist) | https://platform.claude.com/docs/en/agents-and-tools/mcp-connector |
| OpenAI 프롬프트 캐싱 | https://developers.openai.com/api/docs/guides/prompt-caching |
| MCP 스펙 — Tools(2026-07-28) | https://modelcontextprotocol.io/specification/2026-07-28/server/tools |
| MCP 스펙 — Caching(`ttlMs`, `cacheScope`) | https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching |
| Code Mode (클라이언트) | https://blog.cloudflare.com/code-mode/ (2025-09-26) |
| Code Mode (서버, 2도구 1,000토큰) | https://blog.cloudflare.com/code-mode-mcp/ (2026-02-20) |
| 7개 서버 131도구 실측 | https://contextbolt.com/blog/too-many-mcp-servers/ (2026-11-05) |
| 4개 서버 정의 토큰 실측 | https://importstatic.com/ai/mcp-tool-definition-token-overhead (2026-10-06) |
| 스키마 재작성 937→237 | https://nodeflare.tech/blog/mcp-tool-definition-token-audit (2026-10-16) |
| 도구 18종 토큰 실측 | https://github.com/0-co/agent-friend/discussions/4 (2026-03-17) |
| 스키마 오버헤드 이슈(11종) | https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2808 (2026-05-28) |
| ToolHive | https://github.com/stacklok/toolhive |
| mcp-proxy | https://github.com/joshrotenberg/mcp-proxy |
| MCPProxy vs ToolHive | https://mcpproxy.app/guides/toolhive-vs-mcpproxy/ |
| 게이트웨이 3종 비교 | https://indexagentica.com/compare/mcp-gateways/ |
| Cursor MCP 문서 | https://cursor.com/docs/mcp |
| VS Code 도구 문서(128 한도) | https://code.visualstudio.com/docs/agents/run/tools |

## 부록 B. 측정 재현

```bash
# 1) 카탈로그 기준선
python - <<'PY'
from pipeline.mcp_token_optimizer import ToolRouter, sample_catalog
r = ToolRouter(sample_catalog())
print("baseline:", r.baseline_tokens())          # 38,355
print("name only:", r.baseline_tokens("name"))   # 797
PY

# 2) 라우팅 절감
python -m pipeline.mcp_token_optimizer

# 3) 실제 서버 정의를 재고 싶다면: tools/list 결과를 ToolSpec으로 옮겨 같은 함수 사용
```

Anthropic API로 정확히 재려면:

```bash
curl -s https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2026-10-21" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-5-5","tools":'"$(cat tools.json)"',"messages":[{"role":"user","content":"x"}]}'
```
