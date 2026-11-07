"""MCP 도구 정의·결과 페이로드 토큰 최적화 유틸리티 (표준 라이브러리만 사용).

MCP 서버를 여러 개 붙이면 두 곳에서 토큰이 새어 나갑니다.

1. **도구 정의(tool definition)** — 모든 ``tools/list`` 결과가 매 요청마다 프롬프트에 실립니다.
2. **도구 결과(tool result)** — DB 덤프·원시 JSON·파일 전문이 그대로 모델 컨텍스트에 들어갑니다.

이 모듈은 두 지점을 다루는 최소 구현을 담습니다.

* :class:`ToolRouter` — 100개 규모의 도구 카탈로그에서 질문과 관련된 2~3개만 골라
  프롬프트에 넣는 BM25 기반 라우터. 임베딩 함수를 주입하면 하이브리드(의미+어휘)로 동작합니다.
* :func:`prune_schema`, :func:`prune_tool_definition` — JSON Schema 가지치기.
* :func:`to_markdown_table`, :func:`summarize_records`, :func:`paginate`,
  :func:`truncate_text` — 결과 페이로드 요약·압축·페이징.
* :func:`estimate_tokens` — 토큰 수 근사치(정확한 값은 provider의 count_tokens API 사용).

3D 에셋 파이프라인과는 무관한 독립 모듈입니다. 네트워크·API 키 없이 동작하며,
``python -m pipeline.mcp_token_optimizer`` 로 데모를 실행할 수 있습니다.

주의: :func:`estimate_tokens` 는 어림값입니다. 절감률 비교에는 충분하지만,
청구서에 쓰는 절대값은 Anthropic ``/v1/messages/count_tokens`` 처럼
provider가 제공하는 토큰 계산 API로 확인하세요.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = [
    "ToolSpec",
    "ToolRouter",
    "RoutedRequest",
    "estimate_tokens",
    "estimate_json_tokens",
    "prune_schema",
    "prune_tool_definition",
    "build_tool_search_tool",
    "estimate_savings",
    "to_markdown_table",
    "to_tsv",
    "summarize_records",
    "truncate_text",
    "strip_empty",
    "project_fields",
    "paginate",
    "payload_report",
    "sample_catalog",
]

# ---------------------------------------------------------------------------
# 1. 토큰 근사
# ---------------------------------------------------------------------------

_CJK = re.compile(r"[\u3000-\u9fff\uf900-\ufaff\uac00-\ud7a3]")


def estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 근사한다.

    규칙은 단순하다. CJK 문자는 1자당 1토큰, 그 외 문자는 4자당 1토큰으로 센다.
    실제 BPE 토크나이저와는 ±20% 정도 차이가 날 수 있고, 제공자마다 토크나이저가
    다르므로 **절대값이 아니라 같은 조건의 전후 비교**에 쓴다.
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return cjk + math.ceil(other / 4)


def estimate_json_tokens(value: Any) -> int:
    """JSON 직렬화 기준 토큰 근사(공백 없는 compact 직렬화)."""
    return estimate_tokens(compact_json(value))


def compact_json(value: Any) -> str:
    """공백 없는 JSON 문자열. 원본 ``json.dumps`` 보다 10~20% 짧다."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 2. 도구 스펙과 라우터
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """MCP ``tools/list`` 항목 하나를 담는 불변 스펙."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server: str = ""
    keywords: tuple[str, ...] = ()
    read_only: bool | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.server}__{self.name}" if self.server else self.name

    def to_definition(self, detail: str = "full") -> dict[str, Any]:
        """프롬프트에 실을 도구 정의를 만든다.

        ``detail`` 은 점진적 공개(progressive disclosure) 수준이다.

        * ``"name"`` — 이름만. 검색 결과 목록에 적합.
        * ``"name+description"`` — 이름 + 한 줄 설명.
        * ``"full"`` — 이름 + 설명 + inputSchema.
        """
        if detail not in {"name", "name+description", "full"}:
            raise ValueError(f"unknown detail level: {detail!r}")
        if detail == "name":
            return {"name": self.qualified_name}
        if detail == "name+description":
            return {"name": self.qualified_name, "description": self.description}
        return {
            "name": self.qualified_name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def token_cost(self, detail: str = "full") -> int:
        return estimate_json_tokens(self.to_definition(detail))


_ASCII_WORD = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """BM25용 토큰화. ASCII 단어 + 한글 음절 바이그램.

    한글은 조사가 붙어 형태가 변하므로(이슈/이슈를/이슈에서) 음절 바이그램으로
    잘라 어간 일치를 거칠게 흉내 낸다. 외부 형태소 분석기 없이도 한국어 질의가
    영어 도구 설명과 만나게 하려는 실용적 타협이다.
    """
    lowered = text.lower()
    tokens = _ASCII_WORD.findall(lowered)
    for match in re.finditer(r"[\uac00-\ud7a3]+", lowered):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class ToolRouter:
    """도구 카탈로그에서 질문과 관련된 도구만 골라내는 BM25 라우터.

    Parameters
    ----------
    tools:
        전체 카탈로그. 100개 이상이어도 된다.
    embed:
        선택. 텍스트를 벡터로 바꾸는 함수. 주어지면 BM25 점수와 코사인 유사도를
        섞은 하이브리드 점수를 쓴다(``alpha`` 로 비중 조절).
    alpha:
        하이브리드에서 의미 점수의 비중. 0이면 순수 BM25.
    """

    def __init__(
        self,
        tools: Iterable[ToolSpec],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        embed: Callable[[str], Sequence[float]] | None = None,
        alpha: float = 0.5,
    ) -> None:
        self.tools: list[ToolSpec] = list(tools)
        if not self.tools:
            raise ValueError("tool catalog is empty")
        names = [t.qualified_name for t in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool names in catalog")
        self.k1 = k1
        self.b = b
        self.embed = embed
        self.alpha = alpha if embed is not None else 0.0

        self._docs: list[list[str]] = [self._document(t) for t in self.tools]
        self._doc_len = [len(d) for d in self._docs]
        self._avg_len = sum(self._doc_len) / len(self._doc_len)
        self._df: dict[str, int] = {}
        for doc in self._docs:
            for term in set(doc):
                self._df[term] = self._df.get(term, 0) + 1
        self._n = len(self._docs)
        self._tool_vectors: list[Sequence[float]] | None = (
            [self.embed(self._document_text(t)) for t in self.tools]
            if self.embed is not None
            else None
        )

    # -- 색인 ---------------------------------------------------------------
    @staticmethod
    def _document_text(tool: ToolSpec) -> str:
        # 이름을 두 번 넣어 이름 일치에 가중치를 준다. 서버 이름만 겹치는 질의에서
        # 같은 서버의 도구 열 개가 동점이 되는 문제를 줄인다.
        return " ".join([tool.server, tool.server, tool.name, tool.name, tool.description, *tool.keywords])

    def _document(self, tool: ToolSpec) -> list[str]:
        return _tokenize(self._document_text(tool))

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        # BM25+ 스타일의 양수 IDF. 모든 문서에 나오는 단어는 0에 가깝게.
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    # -- 점수 ---------------------------------------------------------------
    def bm25_scores(self, query: str) -> list[float]:
        terms = _tokenize(query)
        if not terms:
            return [0.0] * self._n
        scores = [0.0] * self._n
        for term in terms:
            idf = self._idf(term)
            if idf <= 0:
                continue
            for i, doc in enumerate(self._docs):
                tf = doc.count(term)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self._doc_len[i] / self._avg_len)
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores

    def _semantic_scores(self, query: str) -> list[float] | None:
        if self.embed is None or self._tool_vectors is None:
            return None
        q = list(self.embed(query))
        qn = math.sqrt(sum(v * v for v in q)) or 1.0
        out = []
        for vec in self._tool_vectors:
            vn = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append(sum(a * b for a, b in zip(q, vec)) / (qn * vn))
        return out

    def scores(self, query: str) -> list[float]:
        """최종 점수. 하이브리드일 때 각 점수를 0~1로 정규화해 섞는다."""
        lexical = self.bm25_scores(query)
        semantic = self._semantic_scores(query)
        if semantic is None:
            return lexical
        lex_max = max(lexical) or 1.0
        sem_min, sem_max = min(semantic), max(semantic)
        span = (sem_max - sem_min) or 1.0
        return [
            (1 - self.alpha) * (l / lex_max) + self.alpha * ((s - sem_min) / span)
            for l, s in zip(lexical, semantic)
        ]

    # -- 선택 ---------------------------------------------------------------
    def select(
        self,
        query: str,
        *,
        k: int = 3,
        max_tokens: int | None = None,
        detail: str = "full",
        min_score: float = 0.0,
        min_relative_score: float = 0.0,
        always: Sequence[str] = (),
    ) -> list[ToolSpec]:
        """질문에 필요한 도구를 최대 ``k`` 개 고른다.

        정렬은 ``(-점수, 이름)`` 으로 결정적이다. 같은 질의에 같은 순서가 나와야
        프롬프트 접두사가 고정되고 프롬프트 캐시가 깨지지 않는다.
        ``max_tokens`` 를 주면 정의 토큰 합이 예산을 넘지 않게 자른다.
        ``min_relative_score`` 는 1등 점수 대비 하한 비율이다. 한글 바이그램은
        "이스"처럼 서로 다른 단어에 걸쳐 겹치므로, 약한 동점성 후보를 잘라내는
        용도로 쓴다(데모는 0.55).
        """
        if k < 1:
            return []
        picked: list[ToolSpec] = []
        for name in always:
            tool = self._by_name(name)
            if tool is not None and tool not in picked:
                picked.append(tool)

        raw = self.scores(query)
        scored = sorted(
            zip(raw, self.tools),
            key=lambda pair: (-pair[0], pair[1].qualified_name),
        )
        floor = min_score
        if scored and min_relative_score > 0:
            floor = max(floor, scored[0][0] * min_relative_score)
        budget = max_tokens
        used = sum(t.token_cost(detail) for t in picked)
        for score, tool in scored:
            if len(picked) >= k:
                break
            if tool in picked:
                continue
            if score <= floor:
                break
            cost = tool.token_cost(detail)
            if budget is not None and used + cost > budget:
                continue
            picked.append(tool)
            used += cost
        return picked

    def _by_name(self, name: str) -> ToolSpec | None:
        for tool in self.tools:
            if tool.qualified_name == name or tool.name == name:
                return tool
        return None

    # -- 측정 ---------------------------------------------------------------
    def baseline_tokens(self, detail: str = "full") -> int:
        """모든 도구를 상시 노출했을 때의 정의 토큰 합(매 요청 비용)."""
        return sum(t.token_cost(detail) for t in self.tools)

    def route(
        self,
        query: str,
        *,
        k: int = 3,
        max_tokens: int | None = None,
        detail: str = "full",
        min_relative_score: float = 0.0,
    ) -> "RoutedRequest":
        """:func:`select` + 비용 계산을 한 번에. 데모·테스트에서 쓰는 편의 함수."""
        selected = self.select(
            query,
            k=k,
            max_tokens=max_tokens,
            detail=detail,
            min_relative_score=min_relative_score,
        )
        definitions = [t.to_definition(detail) for t in selected]
        baseline = self.baseline_tokens(detail)
        optimized = estimate_json_tokens(definitions)
        return RoutedRequest(
            query=query,
            selected=[t.qualified_name for t in selected],
            definitions=definitions,
            baseline_tokens=baseline,
            routed_tokens=optimized,
            savings=estimate_savings(baseline, optimized),
        )


@dataclass(frozen=True)
class RoutedRequest:
    """라우팅 결과와 그 비용."""

    query: str
    selected: list[str]
    definitions: list[dict[str, Any]]
    baseline_tokens: int
    routed_tokens: int
    savings: dict[str, float]


def build_tool_search_tool(
    detail_levels: Sequence[str] = ("name", "name+description", "full"),
) -> dict[str, Any]:
    """메타 도구 ``search_tools`` 정의.

    전체 스키마 대신 이 도구 하나(수백 토큰)만 상시 노출하고, 모델이 필요할 때
    검색해서 필요한 정의만 받아오게 하는 패턴의 골격이다.
    """
    return {
        "name": "search_tools",
        "description": (
            "Search the tool catalog by natural language. Returns matching tools; "
            "request detail='full' only for tools you intend to call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What you need to do."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                "detail": {"type": "string", "enum": list(detail_levels), "default": "name"},
            },
            "required": ["query"],
        },
    }


def estimate_savings(baseline_tokens: int, optimized_tokens: int) -> dict[str, float]:
    """절감량/절감률. 0으로 나누지 않도록 방어한다."""
    if baseline_tokens < 0 or optimized_tokens < 0:
        raise ValueError("token counts must be non-negative")
    saved = baseline_tokens - optimized_tokens
    pct = (saved / baseline_tokens * 100.0) if baseline_tokens else 0.0
    return {
        "baseline_tokens": baseline_tokens,
        "optimized_tokens": optimized_tokens,
        "saved_tokens": saved,
        "saved_pct": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# 3. JSON Schema 가지치기
# ---------------------------------------------------------------------------

_DROP_ANYWHERE = {"$schema", "$id", "$comment", "title", "examples", "default"}
_KEEP_ALWAYS = {"type", "properties", "required", "items", "enum", "description"}


def prune_schema(
    schema: Any,
    *,
    max_description_chars: int | None = 120,
    collapse_nullable: bool = True,
    drop_keys: Iterable[str] = (),
) -> Any:
    """모델이 도구를 고르는 데 필요 없는 JSON Schema 메타데이터를 걷어낸다.

    * ``$schema``, ``$id``, ``title``, ``examples``, ``default`` 제거
    * ``anyOf: [{...}, {"type": "null"}]`` → 널 허용 유니언을 평범한 optional 로 축약
    * 긴 프로퍼티 설명 절단(``max_description_chars``)
    * ``description``/``enum``/``minimum``/``pattern`` 처럼 판단에 필요한 정보는 보존

    실측 사례에서 도구 정의 토큰의 64~83%가 inputSchema 였고, 그 대부분이
    ``title``·``examples``·``anyOf`` 같은 생성기 부산물이었다.
    """
    extra_drop = set(drop_keys)

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node

        if collapse_nullable:
            variants = node.get("anyOf") or node.get("oneOf")
            if isinstance(variants, list):
                non_null = [
                    v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")
                ]
                if len(non_null) == 1 and len(non_null) != len(variants):
                    merged = dict(node)
                    merged.pop("anyOf", None)
                    merged.pop("oneOf", None)
                    merged.update(walk(non_null[0]))
                    return walk(merged)

        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _DROP_ANYWHERE or key in extra_drop:
                continue
            if key == "description" and isinstance(value, str):
                if max_description_chars and len(value) > max_description_chars:
                    out[key] = value[: max_description_chars - 1].rstrip() + "…"
                else:
                    out[key] = value
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: walk(spec) for name, spec in value.items()}
                continue
            if key in {"items", "additionalProperties", "not"}:
                out[key] = walk(value)
                continue
            if key in {"allOf", "anyOf", "oneOf"} and isinstance(value, list):
                out[key] = [walk(item) for item in value]
                continue
            out[key] = value
        return out

    return walk(schema)


def prune_tool_definition(
    definition: Mapping[str, Any],
    *,
    max_description_chars: int = 200,
    max_property_description_chars: int | None = 120,
    max_properties: int | None = None,
) -> dict[str, Any]:
    """도구 정의 하나를 가지치기한다(이름·설명·inputSchema)."""
    out = dict(definition)
    desc = out.get("description")
    if isinstance(desc, str) and len(desc) > max_description_chars:
        sentences = re.split(r"(?<=[.!?。])\s+", desc)
        trimmed = ""
        for sentence in sentences:
            if len(trimmed) + len(sentence) + 1 > max_description_chars and trimmed:
                break
            trimmed = f"{trimmed} {sentence}".strip()
        out["description"] = trimmed or desc[: max_description_chars - 1].rstrip() + "…"

    schema = out.get("input_schema") or out.get("inputSchema")
    if isinstance(schema, dict):
        pruned = prune_schema(schema, max_description_chars=max_property_description_chars)
        if max_properties is not None and isinstance(pruned.get("properties"), dict):
            props = pruned["properties"]
            required = pruned.get("required", [])
            keep = list(dict.fromkeys([*required, *props]))[:max_properties]
            pruned["properties"] = {k: props[k] for k in keep if k in props}
            if "required" in pruned:
                pruned["required"] = [r for r in required if r in pruned["properties"]]
        if "input_schema" in out:
            out["input_schema"] = pruned
        else:
            out["inputSchema"] = pruned
    return out


# ---------------------------------------------------------------------------
# 4. 결과 페이로드 최적화
# ---------------------------------------------------------------------------


def _stringify_cell(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = compact_json(value)
    else:
        text = str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def to_markdown_table(
    records: Sequence[Mapping[str, Any]],
    columns: Sequence[str] | None = None,
    *,
    max_cell_chars: int = 40,
) -> str:
    """레코드 목록을 마크다운 표로. 같은 데이터의 원시 JSON보다 토큰이 절반 이하다.

    키를 한 번만 쓰고 값만 반복하므로, 키가 반복되는 JSON 배열과 달리
    필드 수가 많을수록 이득이 커진다.
    """
    rows = list(records)
    if not rows:
        return "(no rows)"
    cols = list(columns or list(dict.fromkeys(key for row in rows for key in row)))
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = [
        "| " + " | ".join(_stringify_cell(row.get(c), max_cell_chars) for c in cols) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def to_tsv(
    records: Sequence[Mapping[str, Any]],
    columns: Sequence[str] | None = None,
    *,
    max_cell_chars: int = 60,
) -> str:
    """레코드 목록을 TSV로. 표 테두리가 없어 마크다운보다 조금 더 짧다."""
    rows = list(records)
    if not rows:
        return ""
    cols = list(columns or list(dict.fromkeys(key for row in rows for key in row)))
    lines = ["\t".join(cols)]
    for row in rows:
        lines.append(
            "\t".join(_stringify_cell(row.get(c), max_cell_chars) for c in cols)
        )
    return "\n".join(lines)


def summarize_records(
    records: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
    preview: int = 5,
    label: str = "rows",
    hint: bool = True,
) -> str:
    """Summary-First 패턴: 전체 건수 + 앞쪽 몇 건만 반환하고 나머지는 페이징 유도.

    모델이 "몇 건인지"와 "다음에 무엇을 물어야 하는지"를 알 수 있으면 충분한
    경우가 많다. 10,000행을 통째로 넣는 대신 5행 + 안내 문장을 넣는다.
    """
    rows = list(records)
    total = len(rows)
    head = rows[: max(0, preview)]
    lines = [f"total {label}: {total}"]
    if head:
        lines.append(to_markdown_table(head, columns))
    if total > len(head):
        if hint:
            lines.append(
                f"showing {len(head)} of {total}. "
                f"call again with offset={len(head)} (or a narrower filter) for the next page."
            )
        else:
            lines.append(f"showing {len(head)} of {total}.")
    return "\n".join(lines)


def truncate_text(
    text: str,
    max_tokens: int,
    *,
    keep_tail_ratio: float = 0.2,
    marker: str = "\n…[truncated {cut} tokens; request a page/filter for the rest]…\n",
) -> str:
    """텍스트를 토큰 예산에 맞춰 자른다.

    앞부분만 남기면 결론·에러 메시지가 잘리므로 꼬리도 일부 보존한다
    (로그·스택트레이스에서 유용).
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    total = estimate_tokens(text)
    if total <= max_tokens:
        return text
    budget_chars = max_tokens * 4  # ascii 기준 역산(보수적)
    tail_chars = int(budget_chars * max(0.0, min(1.0, keep_tail_ratio)))
    head_chars = max(0, budget_chars - tail_chars)
    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars else ""
    cut = total - estimate_tokens(head + tail)
    return head + marker.format(cut=max(cut, 0)) + tail


def strip_empty(value: Any) -> Any:
    """None·빈 문자열·빈 리스트/딕셔너리 필드를 재귀적으로 제거한다.

    API 응답의 ``null`` 범벅은 정보가 아니라 토큰이다.
    """
    if isinstance(value, list):
        return [strip_empty(v) for v in value if v not in (None, "", [], {})]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            cleaned = strip_empty(item)
            if cleaned not in (None, "", [], {}):
                out[key] = cleaned
        return out
    return value


def project_fields(
    records: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> list[dict[str, Any]]:
    """필요한 필드만 남긴다(서버·프록시 측 사전 필터링의 최소형)."""
    return [{f: row[f] for f in fields if f in row} for row in records]


def paginate(
    records: Sequence[Any], *, offset: int = 0, limit: int = 20
) -> dict[str, Any]:
    """오프셋 페이징 응답. 다음 호출에 필요한 정보를 함께 돌려준다."""
    if offset < 0 or limit < 1:
        raise ValueError("offset must be >= 0 and limit >= 1")
    rows = list(records)
    window = rows[offset : offset + limit]
    next_offset = offset + len(window)
    return {
        "total": len(rows),
        "offset": offset,
        "returned": len(window),
        "next_offset": next_offset if next_offset < len(rows) else None,
        "items": window,
    }


def payload_report(raw: Any, optimized_text: str) -> dict[str, Any]:
    """원본 페이로드와 최적화 결과의 토큰 비교."""
    if isinstance(raw, str):
        before = estimate_tokens(raw)
    else:
        before = estimate_json_tokens(raw)
    after = estimate_tokens(optimized_text)
    return {
        **estimate_savings(before, after),
        "before_tokens": before,
        "after_tokens": after,
    }


# ---------------------------------------------------------------------------
# 5. 데모용 카탈로그 (100개 도구)
# ---------------------------------------------------------------------------

_SERVER_TOOLS: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "github": [
        ("list_issues", "List issues in a repository with state and label filters.", ("issue", "bug", "ticket", "이슈", "버그", "목록")),
        ("get_issue", "Read one issue with body, comments and labels.", ("issue", "detail", "이슈")),
        ("create_issue", "Open a new issue in a repository.", ("issue", "create", "bug", "이슈", "생성")),
        ("update_issue", "Edit an issue's title, body, state or labels.", ("issue", "update", "close")),
        ("search_code", "Search code across repositories with GitHub search syntax.", ("code", "search", "grep")),
        ("list_pull_requests", "List pull requests with review state.", ("pr", "pullrequest", "review")),
        ("create_pull_request", "Open a pull request from a branch.", ("pr", "merge", "review")),
        ("list_commits", "List commits on a branch or path.", ("commit", "history", "git")),
        ("get_file_contents", "Read a file from a repository at a ref.", ("file", "source", "read")),
        ("list_releases", "List releases and tags of a repository.", ("release", "tag", "version")),
    ],
    "slack": [
        ("post_message", "Send a message to a Slack channel or thread.", ("slack", "message", "알림", "알려", "슬랙", "보내", "메시지", "notify")),
        ("list_channels", "List channels the user can post to.", ("channel", "list")),
        ("read_history", "Read recent messages from a channel.", ("history", "message", "read")),
        ("reply_thread", "Reply in an existing message thread.", ("reply", "thread")),
        ("search_messages", "Search messages by keyword or user.", ("search", "message")),
        ("upload_file", "Upload a file to a channel.", ("file", "upload", "첨부")),
        ("list_users", "List workspace members.", ("user", "member", "directory")),
        ("set_status", "Set the user's status and presence.", ("status", "presence")),
        ("create_channel", "Create a new channel and invite members.", ("channel", "create")),
        ("add_reaction", "Add an emoji reaction to a message.", ("reaction", "emoji")),
    ],
    "jira": [
        ("search_issues", "Search issues with JQL, returns key, summary and status.", ("jira", "jql", "issue", "검색")),
        ("get_issue", "Read a Jira issue with fields and comments.", ("issue", "detail")),
        ("create_issue", "Create a Jira issue in a project.", ("issue", "create", "ticket")),
        ("transition_issue", "Move an issue to another workflow status.", ("status", "workflow", "move")),
        ("add_comment", "Add a comment to an issue.", ("comment", "issue")),
        ("list_sprints", "List sprints of a board.", ("sprint", "board", "agile")),
        ("get_sprint_report", "Burndown and velocity for a sprint.", ("burndown", "velocity", "report")),
        ("assign_issue", "Assign an issue to a user.", ("assign", "owner")),
        ("list_projects", "List visible Jira projects.", ("project", "list")),
        ("log_work", "Log work hours against an issue.", ("worklog", "time", "hours")),
    ],
    "notion": [
        ("search", "Search pages and databases by title or content.", ("notion", "search", "document", "문서", "찾", "검색")),
        ("get_page", "Read a page as Markdown.", ("page", "read", "markdown")),
        ("create_page", "Create a page under a parent page or database.", ("page", "create", "write")),
        ("update_page", "Replace or append content blocks on a page.", ("page", "update", "edit")),
        ("query_database", "Query database rows with filters and sorts.", ("database", "query", "filter", "데이터베이스", "진행", "작업", "조회")),
        ("create_row", "Insert a row into a database.", ("row", "insert", "database")),
        ("list_databases", "List databases shared with the integration.", ("database", "list")),
        ("get_block_children", "List child blocks of a block or page.", ("block", "children")),
        ("append_blocks", "Append blocks to a page.", ("block", "append", "write")),
        ("delete_block", "Archive a block.", ("block", "delete")),
    ],
    "postgres": [
        ("query", "Run a read-only SQL query and return rows.", ("sql", "database", "query", "조회", "가입자", "통계")),
        ("list_tables", "List tables and views in a schema.", ("schema", "table", "list")),
        ("describe_table", "Show columns, types and indexes of a table.", ("schema", "column", "ddl")),
        ("explain_query", "Return the query plan for a SQL statement.", ("plan", "explain", "performance")),
        ("table_stats", "Row counts, size and bloat estimate for a table.", ("stats", "size", "bloat")),
        ("list_slow_queries", "Top queries by mean execution time.", ("slow", "performance", "pgstat")),
        ("insert_row", "Insert a row into a table.", ("insert", "write", "row")),
        ("update_row", "Update rows matching a condition.", ("update", "write", "row")),
        ("list_indexes", "List indexes of a table with usage counts.", ("index", "performance")),
        ("vacuum_status", "Last vacuum and autovacuum settings.", ("vacuum", "maintenance")),
    ],
    "filesystem": [
        ("read_file", "Read a UTF-8 text file.", ("file", "read", "text", "파일")),
        ("write_file", "Write or overwrite a text file.", ("file", "write", "save")),
        ("list_directory", "List entries of a directory.", ("directory", "list", "ls")),
        ("search_files", "Find files by glob or content pattern.", ("glob", "grep", "find", "검색")),
        ("move_file", "Move or rename a file.", ("move", "rename")),
        ("delete_file", "Delete a file.", ("delete", "remove")),
        ("file_info", "Size, timestamps and permissions of a file.", ("stat", "metadata", "info")),
        ("create_directory", "Create a directory, including parents.", ("mkdir", "directory")),
        ("read_binary_meta", "Return MIME type and dimensions of a binary file.", ("image", "mime", "metadata")),
        ("watch_directory", "Watch a directory for changes for N seconds.", ("watch", "events")),
    ],
    "browser": [
        ("open_url", "Open a URL in a controlled browser session.", ("browser", "navigate", "web", "웹")),
        ("click", "Click an element matched by selector or text.", ("click", "ui", "element")),
        ("type_text", "Type into a focused input.", ("type", "input", "form")),
        ("screenshot", "Capture the viewport as an image.", ("screenshot", "capture", "image")),
        ("extract_text", "Extract readable text from the current page.", ("scrape", "text", "content")),
        ("get_links", "List links on the page with their text.", ("links", "crawl")),
        ("fill_form", "Fill several fields and optionally submit.", ("form", "fill", "submit")),
        ("wait_for", "Wait until text or selector appears.", ("wait", "selector")),
        ("set_viewport", "Resize the browser viewport.", ("viewport", "resize")),
        ("go_back", "Navigate back in browser history.", ("back", "history")),
    ],
    "gdrive": [
        ("search_files", "Search Drive files by name, type or full text.", ("drive", "search", "file", "문서")),
        ("get_document", "Read a Google Doc as plain text or Markdown.", ("doc", "read", "text")),
        ("get_sheet", "Read a sheet range as rows.", ("sheet", "spreadsheet", "rows", "시트")),
        ("create_document", "Create a new Google Doc with content.", ("doc", "create", "write")),
        ("list_folder", "List files in a folder by id.", ("folder", "list")),
        ("upload_file", "Upload a local file to Drive.", ("upload", "file")),
        ("share_file", "Share a file with a user or make it link-visible.", ("share", "permission")),
        ("export_pdf", "Export a Doc or Sheet as PDF.", ("pdf", "export")),
        ("get_metadata", "Return owner, size and modified time.", ("metadata", "info")),
        ("move_file", "Move a file to another folder.", ("move", "folder")),
    ],
    "sentry": [
        ("list_issues", "List unresolved Sentry issues for a project.", ("sentry", "error", "issue", "에러", "이슈", "목록")),
        ("get_event", "Read a single error event with stack trace.", ("event", "stacktrace", "error", "스택트레이스", "상세")),
        ("list_projects", "List projects in the organization.", ("project", "list")),
        ("issue_counts", "Event counts per issue over a period.", ("count", "trend", "issue")),
        ("resolve_issue", "Mark an issue resolved or ignored.", ("resolve", "ignore")),
        ("list_releases", "List releases and their adoption.", ("release", "version")),
        ("create_alert", "Create an alert rule for a project.", ("alert", "rule")),
        ("get_performance", "p95 latency and throughput by transaction.", ("performance", "latency", "apdex")),
        ("list_members", "List organization members and roles.", ("member", "team")),
        ("delete_issue", "Delete an issue.", ("delete", "issue")),
    ],
    "aws": [
        ("s3_list_objects", "List S3 objects under a prefix.", ("s3", "bucket", "list", "스토리지")),
        ("s3_get_object", "Download an S3 object's body.", ("s3", "download", "object")),
        ("s3_put_object", "Upload an object to S3.", ("s3", "upload", "object")),
        ("logs_query", "Query CloudWatch Logs Insights.", ("cloudwatch", "logs", "query")),
        ("lambda_invoke", "Invoke a Lambda function synchronously.", ("lambda", "invoke", "function")),
        ("ec2_describe", "Describe EC2 instances and their state.", ("ec2", "instance", "server")),
        ("cost_report", "Cost and usage grouped by service for a period.", ("cost", "billing", "usage", "비용", "리포트", "청구")),
        ("iam_list_roles", "List IAM roles and attached policies.", ("iam", "role", "policy")),
        ("sqs_send", "Send a message to an SQS queue.", ("sqs", "queue", "message")),
        ("rds_describe", "Describe RDS instances and endpoints.", ("rds", "database", "instance")),
    ],
}


def sample_catalog() -> list[ToolSpec]:
    """데모/테스트용 100개 도구 카탈로그(10개 서버 × 10개 도구).

    실제 서버의 스키마 크기를 흉내 내려고 파라미터를 6~8개씩 넣고
    ``title``·``examples``·``anyOf`` 널 유니언 같은 생성기 부산물도 섞었다.
    """
    catalog: list[ToolSpec] = []
    for server, entries in _SERVER_TOOLS.items():
        for index, (name, description, keywords) in enumerate(entries):
            schema: dict[str, Any] = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "title": f"{name} parameters",
                "properties": {
                    "query": {
                        "title": "Query",
                        "type": "string",
                        "description": (
                            "검색/실행에 사용할 질의 또는 자연어 지시. 필터 문법을 지원하며, "
                            "빈 문자열이면 전체를 대상으로 한다. 결과는 서버 기본 정렬을 따른다."
                        ),
                        "examples": ["status = open", "최근 7일"],
                    },
                    "limit": {
                        "title": "Limit",
                        "anyOf": [{"type": "integer", "minimum": 1, "maximum": 200}, {"type": "null"}],
                        "default": None,
                        "description": "Maximum number of items to return. Defaults to the server value; larger values cost more tokens downstream.",
                    },
                    "fields": {
                        "title": "Fields",
                        "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                        "default": None,
                        "description": "프로젝션할 필드 목록. 지정하면 응답이 짧아진다.",
                    },
                    "cursor": {
                        "title": "Cursor",
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "description": "이전 응답의 nextCursor 값.",
                    },
                    "timeout_s": {
                        "title": "Timeout",
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 600,
                        "description": "서버 측 실행 제한 시간(초).",
                    },
                    "dry_run": {
                        "title": "Dry run",
                        "type": "boolean",
                        "description": "Validate arguments and return the planned call without side effects.",
                        "examples": [False],
                    },
                },
                "required": ["query"],
            }
            if index % 3 == 0:
                schema["properties"]["labels"] = {
                    "title": "Labels",
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "호출에 붙일 임의 메타데이터.",
                }
            catalog.append(
                ToolSpec(
                    name=name,
                    description=description,
                    input_schema=schema,
                    server=server,
                    keywords=keywords,
                    read_only=name.startswith(("list", "get", "read", "search", "describe", "query", "extract")),
                )
            )
    return catalog


# ---------------------------------------------------------------------------
# 6. 데모
# ---------------------------------------------------------------------------


def _demo() -> int:  # pragma: no cover - 실행 확인용
    catalog = sample_catalog()
    router = ToolRouter(catalog)
    baseline = router.baseline_tokens()
    print(f"catalog: {len(catalog)} tools, baseline definitions = {baseline:,} tokens\n")

    queries = [
        "열린 버그 이슈 목록을 GitHub에서 뽑아서 Slack으로 알려줘",
        "게시판 DB에서 지난주 가입자 수를 조회하고 표로 정리해줘",
        "Notion 데이터베이스에서 진행 중인 작업만 찾아줘",
        "Sentry에서 결제 에러 스택트레이스 확인해줘",
        "이번 달 AWS 비용 리포트 뽑아줘",
        "GitHub PR 리뷰 상태를 확인해서 Slack으로 알려줘",
    ]
    for query in queries:
        routed = router.route(query, k=2, min_relative_score=0.55)
        names = ", ".join(routed.selected)
        pct = routed.savings["saved_pct"]
        print(f"- {query}")
        print(f"    selected: {names}")
        print(
            f"    tokens: {routed.routed_tokens:,} / {routed.baseline_tokens:,}"
            f"  ({pct}% saved)\n"
        )

    # 페이로드 예시: 300건 원시 JSON → 요약 + 표 + 페이징
    rows = [
        {
            "id": 1000 + i,
            "title": f"Login fails on Android build {i}",
            "state": "open" if i % 3 else "closed",
            "labels": ["bug"],
            "assignee": None if i % 4 else "kim",
            "created_at": "2026-11-0%dT09:00:00Z" % (i % 9 + 1),
            "body": "사용자가 로그인 화면에서 튕긴다는 제보. 재현 절차 " + "x" * 40,
        }
        for i in range(300)
    ]
    summary = summarize_records(rows, columns=["id", "title", "state"], preview=5, label="issues")
    report = payload_report(rows, summary)
    print("payload: raw JSON -> summary-first")
    print(f"    {report['before_tokens']:,} -> {report['after_tokens']:,} tokens"
          f"  ({report['saved_pct']}% saved)")
    print("    " + summary.replace("\n", "\n    "))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_demo())
