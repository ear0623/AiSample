"""C++ 예제와 문서의 정합성 검증.

컴파일을 대체하지 않는다. UHT/컴파일러 없이도 잡을 수 있는 것만 검사한다.

  - 헤더 규약(#pragma once, CoreMinimal, *.generated.h 마지막 포함)
  - 괄호 균형
  - UCLASS/USTRUCT/UENUM 매크로와 선언의 짝
  - 헤더에 선언한 멤버 함수가 구현(.cpp)에 존재하는가
  - 복제(ReplicatedUsing ↔ OnRep_*, DOREPLIFETIME)
  - NetSerialize 대칭(로드/저장 경로, bOutSuccess)
  - 문서에서 참조하는 파일이 실제로 존재하는가
  - 추가 요구사항 섹션(3.8 인게임 건축, 3.9 디테일)이 문서에 있는가

실행:
    python -m unittest tests.test_cpp_examples -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIRS = [
    REPO_ROOT / "examples" / "unreal_cpp_character",
    REPO_ROOT / "examples" / "unreal_cpp_building",
]
DOCS = [
    REPO_ROOT / "docs" / "open_world_content_and_architecture_guide.md",
    REPO_ROOT / "docs" / "unreal_character_and_customization_guide.md",
]

CPP_KEYWORDS = {
    "return", "if", "for", "while", "switch", "case", "else", "break",
    "continue", "delete", "new", "using", "typedef", "sizeof", "throw",
}

DECL_RE = re.compile(
    r"^[ \t]+(?:virtual\s+|static\s+|explicit\s+|inline\s+|FORCEINLINE\s+)*"
    r"(?:const\s+)?[A-Za-z_][\w:<>,\s\*&]*?[\s\*&]([A-Za-z_]\w*)\s*"
    r"\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?;",
    re.MULTILINE,
)

MACRO_RE = re.compile(r"^\s*(UCLASS|USTRUCT|UENUM|UINTERFACE)\s*\(", re.MULTILINE)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def strip_code(source: str) -> str:
    """주석과 문자열/문자 리터럴을 제거한다(괄호 세기 전처리)."""
    out = []
    i = 0
    n = len(source)
    state = None

    while i < n:
        char = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if state is None:
            if char == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if char == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if char == '"':
                state = "string"
                out.append('""')
                i += 1
                continue
            if char == "'":
                state = "char"
                out.append("''")
                i += 1
                continue
            out.append(char)
            i += 1
        elif state == "line":
            if char == "\n":
                state = None
                out.append("\n")
            i += 1
        elif state == "block":
            if char == "*" and nxt == "/":
                state = None
                i += 2
                continue
            if char == "\n":
                out.append("\n")
            i += 1
        else:  # string / char
            if char == "\\":
                i += 2
                continue
            if (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = None
            i += 1

    return "".join(out)


def header_files():
    for directory in EXAMPLE_DIRS:
        for path in sorted(directory.glob("*.h")):
            yield path


def source_files():
    for directory in EXAMPLE_DIRS:
        for path in sorted(directory.glob("*.cpp")):
            yield path


def class_name_of_header(text: str) -> str:
    """헤더의 첫 UCLASS 이름을 돌려준다(모듈 매크로 유무 모두 허용)."""
    match = re.search(r"class\s+(?:[A-Z0-9_]+_API\s+)?([AU][A-Za-z0-9_]+)\s*:", text)
    return match.group(1) if match else ""


class CppExampleTest(unittest.TestCase):
    def test_example_files_exist(self):
        expected = [
            "unreal_cpp_character/CharacterCustomizationTypes.h",
            "unreal_cpp_character/ModularCharacter.h",
            "unreal_cpp_character/ModularCharacter.cpp",
            "unreal_cpp_building/BuildingTypes.h",
            "unreal_cpp_building/BuildManager.h",
            "unreal_cpp_building/BuildManager.cpp",
            "unreal_cpp_building/BuildSystemComponent.h",
            "unreal_cpp_building/BuildSystemComponent.cpp",
        ]
        for relative in expected:
            with self.subTest(file=relative):
                self.assertTrue((REPO_ROOT / "examples" / relative).is_file(), relative)

    def test_header_conventions(self):
        for path in header_files():
            with self.subTest(header=path.name):
                text = read_text(path)
                stripped = strip_code(text)
                first_line = next(line for line in stripped.splitlines() if line.strip())
                self.assertEqual(first_line.strip(), "#pragma once")

                includes = re.findall(r'#include\s+"([^"]+)"', text)
                self.assertIn("CoreMinimal.h", includes)
                self.assertTrue(includes[-1].endswith(".generated.h"),
                                f"{path.name}: 마지막 include는 *.generated.h여야 한다")

    def test_balanced_delimiters(self):
        for path in list(header_files()) + list(source_files()):
            with self.subTest(file=path.name):
                stripped = strip_code(read_text(path))
                for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                    self.assertEqual(stripped.count(opener), stripped.count(closer),
                                     f"{path.name}: {opener}{closer} 불균형")

    def test_macros_followed_by_declaration(self):
        for path in header_files():
            text = strip_code(read_text(path))
            for match in MACRO_RE.finditer(text):
                macro = match.group(1)
                rest = text[match.end():]
                # 매크로 인자 괄호를 건너뛴 뒤 첫 선언을 찾는다.
                depth = 1
                index = 0
                while index < len(rest) and depth > 0:
                    if rest[index] == "(":
                        depth += 1
                    elif rest[index] == ")":
                        depth -= 1
                    index += 1

                following = [line.strip() for line in rest[index:].splitlines() if line.strip()]
                self.assertTrue(following, f"{path.name}: {macro} 뒤에 선언이 없다")
                declaration = following[0]

                expected = {
                    "UCLASS": "class",
                    "USTRUCT": "struct",
                    "UENUM": "enum",
                    "UINTERFACE": "class",
                }[macro]
                self.assertTrue(
                    declaration.startswith(expected),
                    f"{path.name}: {macro} 뒤에 {expected}가 와야 하는데 '{declaration}'",
                )

    def test_declarations_have_definitions(self):
        for path in header_files():
            cpp_path = path.with_suffix(".cpp")
            if not cpp_path.is_file():
                continue

            header_text = strip_code(read_text(path))
            cpp_text = strip_code(read_text(cpp_path))
            class_name = class_name_of_header(header_text)
            self.assertTrue(class_name, f"{path.name}: 클래스 선언을 찾지 못했다")

            lines = header_text.splitlines()
            for line_number, line in enumerate(lines):
                match = DECL_RE.match(line)
                if not match:
                    continue

                name = match.group(1)
                if name in CPP_KEYWORDS:
                    continue

                # BlueprintImplementableEvent는 구현이 생성 코드에 있으므로 제외한다.
                context = "\n".join(lines[max(0, line_number - 4):line_number])
                if "BlueprintImplementableEvent" in context:
                    continue

                defined = (
                    re.search(rf"\b\w+::{re.escape(name)}\(", cpp_text) is not None
                    or re.search(rf"\b\w+::{re.escape(name)}_Implementation\(", cpp_text) is not None
                )
                self.assertTrue(
                    defined,
                    f"{path.name}: {name} 선언이 있으나 {cpp_path.name}에 정의가 없다",
                )

    def test_replicated_properties_have_onrep(self):
        for path in header_files():
            text = strip_code(read_text(path))
            for on_rep in set(re.findall(r"ReplicatedUsing\s*=\s*(OnRep_\w+)", text)):
                with self.subTest(header=path.name, on_rep=on_rep):
                    self.assertIn(f"void {on_rep}(", text,
                                  f"{path.name}: {on_rep} 선언이 없다")

                    cpp_path = path.with_suffix(".cpp")
                    if cpp_path.is_file():
                        cpp_text = strip_code(read_text(cpp_path))
                        class_name = class_name_of_header(text)
                        self.assertIn(f"{class_name}::{on_rep}(", cpp_text,
                                      f"{path.name}: {on_rep} 정의가 없다")

    def test_get_lifetime_replicated_props(self):
        for path in source_files():
            text = strip_code(read_text(path))
            if "DOREPLIFETIME" not in text:
                continue

            with self.subTest(source=path.name):
                self.assertIn("::GetLifetimeReplicatedProps(", text)
                self.assertIn("DOREPLIFETIME", text)

    def test_net_serialize_symmetry(self):
        for path in header_files():
            text = strip_code(read_text(path))
            for struct_name in re.findall(r"struct\s+(F\w+)\s*$", text, re.MULTILINE):
                has_traits = (
                    f"TStructOpsTypeTraits<{struct_name}>" in text
                    and "WithNetSerializer = true" in text
                )
                declares_net_serialize = f"{struct_name}::NetSerialize(" in text
                if declares_net_serialize:
                    with self.subTest(header=path.name, struct=struct_name):
                        self.assertTrue(has_traits,
                                        f"{path.name}: {struct_name}의 TStructOpsTypeTraits 선언이 없다")
                        self.assertIn("bOutSuccess = true;", text)

    def test_enums_are_uint8_with_count_last(self):
        for path in header_files():
            text = strip_code(read_text(path))
            for enum_match in re.finditer(r"enum\s+class\s+(\w+)\s*:\s*(\w+)\s*\{([^}]*)\}", text):
                name, underlying, body = enum_match.groups()
                with self.subTest(header=path.name, enum=name):
                    self.assertEqual(underlying, "uint8", f"{name}은 uint8 기반이어야 한다")

                    values = [entry.strip() for entry in body.split(",") if entry.strip()]
                    if not any(value.startswith("Count") for value in values):
                        continue

                    last_value = values[-1].split()[0]
                    self.assertEqual(last_value, "Count", f"{name}: Count가 마지막 값이어야 한다")

    def test_leader_pose_and_morph_api_usage(self):
        text = strip_code(read_text(REPO_ROOT / "examples" / "unreal_cpp_character" / "ModularCharacter.cpp"))
        for api in ("SetLeaderPoseComponent", "SetMorphTarget", "SetSkeletalMesh", "CreateDynamicMaterialInstance"):
            with self.subTest(api=api):
                self.assertIn(api, text)

        self.assertIn("bSyncAttachParentLOD", text)
        self.assertIn("bUseAttachParentBound", text)

    def test_build_system_uses_server_authority(self):
        text = strip_code(read_text(REPO_ROOT / "examples" / "unreal_cpp_building" / "BuildManager.cpp"))
        for api in ("HasAuthority", "OverlapBlockingTestWithParams", "SpawnActor"):
            with self.subTest(api=api):
                self.assertIn(api, text)

        self.assertIn("RecomputeIntegrity", text)

    def test_upgrade_properties_end_with_semicolon(self):
        for path in header_files():
            lines = strip_code(read_text(path)).splitlines()
            for index, line in enumerate(lines):
                if "UPROPERTY(" not in line:
                    continue

                # 매크로 인자 괄호를 건너뛴 뒤 선언이 ;로 끝나는지 확인한다.
                rest = "\n".join(lines[index:])
                depth = 0
                position = rest.find("UPROPERTY(")
                end = None
                for offset in range(position, len(rest)):
                    if rest[offset] == "(":
                        depth += 1
                    elif rest[offset] == ")":
                        depth -= 1
                        if depth == 0:
                            end = offset
                            break
                self.assertIsNotNone(end, f"{path.name}:{index + 1}: UPROPERTY 괄호가 닫히지 않았다")

                declaration = rest[end + 1:]
                self.assertIn(";", declaration[: declaration.find("UPROPERTY") if "UPROPERTY" in declaration else 400],
                              f"{path.name}:{index + 1}: UPROPERTY 대상 선언이 ;로 끝나지 않는다")


class DocLinkTest(unittest.TestCase):
    def test_relative_links_resolve(self):
        for doc in DOCS:
            text = read_text(doc)
            for target in re.findall(r"\]\((?!https?://|#)([^)]+)\)", text):
                path_part = target.split("#")[0]
                if not path_part:
                    continue
                with self.subTest(doc=doc.name, target=target):
                    self.assertTrue((doc.parent / path_part).resolve().exists(),
                                    f"{doc.name}: 링크 대상이 없다 -> {target}")

    def test_required_sections_present(self):
        architecture = read_text(DOCS[0])
        self.assertIn("### 3.8 인게임 건축 시스템(런타임 건설)", architecture)
        self.assertIn("### 3.9 건물 디테일 표현 기법", architecture)
        for keyword in (
            "고스트 프리뷰",
            "소켓 스냅",
            "지지 그래프",
            "트림 시트",
            "가중치 노멀",
            "DBuffer 데칼",
            "버텍스 컬러",
            "패럴랙스",
            "빛샘",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, architecture)

    def test_character_guide_sections_present(self):
        character = read_text(DOCS[1])
        for heading in (
            "## 3. 모듈러 의상 시스템",
            "## 4. 외모 커스터마이징 시스템",
            "SetLeaderPoseComponent",
            "FCharacterCustomizationData",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, character)


if __name__ == "__main__":
    unittest.main(verbosity=2)
