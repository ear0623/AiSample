#!/usr/bin/env python3
"""언리얼 엔진 5 에디터에서 실행하는 임포트 도우미.

이 파일은 일반 파이썬이 아니라 **UE5 에디터의 파이썬 환경**에서 실행한다.
(Python Editor Script Plugin 활성화 → Output Log의 Cmd 입력창에서
 `py "/절대경로/pipeline/ue5_import.py"`)

하는 일
  1) ue5/ 폴더의 FBX(또는 GLB)를 지정한 콘텐츠 폴더로 임포트
  2) 텍스처 압축 설정을 엔진 규격에 맞춘다
       BaseColor   : sRGB On,  Default(BC7/BC1)
       Normal      : sRGB Off, Normalmap(BC5), 필요 시 Green 채널 반전
       ORM/마스크   : sRGB Off, Masks(BC1/BC3)
  3) 마스터 머티리얼에서 Material Instance를 만들어 텍스처 파라미터를 연결
  4) 정적 메시에 Nanite를 켠다(가능한 경우)

버전 주의
  프로퍼티·서브시스템 이름은 UE 5.3~5.6 기준으로 작성했다. 엔진 버전에 따라
  이름이 다를 수 있으므로, 처음 실행할 때 Output Log의 경고를 확인하고
  필요하면 아래 상수만 고쳐 쓰면 된다. 실패해도 예외로 멈추지 않고
  "에디터에서 직접 하라"는 안내만 남기도록 감쌌다.
"""

from __future__ import annotations

import unreal  # type: ignore  # UE5 에디터에서만 존재

LOG_PREFIX = "[ai3d] "

# --------------------------------------------------------------------------- #
# 설정: 프로젝트에 맞게 고쳐 쓴다
# --------------------------------------------------------------------------- #
ASSET_NAME = "Chair"                       # 에셋 이름(파일 접두사와 맞춘다)
SOURCE_DIR = r"C:/project/ai3d/output/chair/ue5"   # FBX와 텍스처가 있는 폴더
CONTENT_DIR = "/Game/AI3D/Chair"           # 임포트 대상 콘텐츠 폴더
MASTER_MATERIAL = "/Game/AI3D/M_AI3D_Master"  # 아래 파라미터를 가진 마스터 머티리얼


def log(message: str) -> None:
    unreal.log(LOG_PREFIX + message)


def warn(message: str) -> None:
    unreal.log_warning(LOG_PREFIX + message)


# --------------------------------------------------------------------------- #
# 1) 임포트
# --------------------------------------------------------------------------- #
def _import_one(filename: str, destination: str) -> list[str]:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", filename)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", True)

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tools.import_asset_tasks([task])

    imported = list(task.get_editor_property("imported_object_paths") or [])
    for path in imported:
        log(f"imported {path}")
    return imported


def import_assets(source_dir: str, content_dir: str) -> dict[str, str]:
    import os

    result: dict[str, str] = {"meshes": "", "textures": ""}
    if not os.path.isdir(source_dir):
        warn(f"source dir not found: {source_dir}")
        return result

    for entry in sorted(os.listdir(source_dir)):
        lower = entry.lower()
        path = os.path.join(source_dir, entry)
        if lower.endswith((".fbx", ".glb", ".gltf")):
            imported = _import_one(path, content_dir)
            if imported:
                result["meshes"] = imported[0]
        elif lower.endswith((".png", ".tga", ".tif", ".tiff")):
            _import_one(path, content_dir)
            result["textures"] = content_dir
    return result


# --------------------------------------------------------------------------- #
# 2) 텍스처 설정
# --------------------------------------------------------------------------- #
def configure_textures(content_dir: str) -> dict[str, str]:
    """폴더 안 텍스처를 이름 규칙으로 찾아 압축 설정을 맞춘다."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path(content_dir, recursive=True)

    configured: dict[str, str] = {}
    for asset in assets:
        path = str(asset.package_name)
        name = path.rsplit("/", 1)[-1].lower()
        texture = unreal.EditorAssetLibrary.load_asset(path)
        if not isinstance(texture, unreal.Texture2D):
            continue

        try:
            if "normal" in name or name.endswith("_n"):
                texture.set_editor_property("srgb", False)
                texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
                # glTF 계열 노멀맵은 OpenGL(+Y up) 규약이라 엔진(DirectX)과 Green이 반대다.
                # 파이프라인에서 미리 뒤집었다면 False로 둔다.
                texture.set_editor_property("flip_green_channel", True)
                kind = "normal"
            elif any(key in name for key in ("orm", "_arm", "metallic", "roughness", "occlusion", "ao")):
                texture.set_editor_property("srgb", False)
                texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
                kind = "mask"
            elif "basecolor" in name or "albedo" in name or "diffuse" in name or name.endswith("_bc"):
                texture.set_editor_property("srgb", True)
                texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
                kind = "color"
            else:
                continue

            unreal.EditorAssetLibrary.save_loaded_asset(texture, False)
            configured[path] = kind
            log(f"texture {kind:<6} {path}")
        except Exception as exc:  # noqa: BLE001 - 버전별 프로퍼티 차이 흡수용
            warn(f"could not configure {path}: {exc}")
    return configured


# --------------------------------------------------------------------------- #
# 3) 머티리얼 인스턴스
# --------------------------------------------------------------------------- #
def create_material_instance(
    parent_path: str,
    name: str,
    content_dir: str,
    basecolor: str | None = None,
    normal: str | None = None,
    orm: str | None = None,
) -> str:
    """마스터 머티리얼에서 MI를 만들고 텍스처 파라미터를 연결한다.

    마스터 머티리얼에는 다음 이름의 Texture2D 파라미터가 있어야 한다.
        BaseColor, Normal, ORM          (UMG/서브스트레이트 방식과 동일)
    """
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()
    instance = tools.create_asset(name, content_dir, unreal.MaterialInstanceConstant, factory)
    if instance is None:
        raise RuntimeError(f"failed to create material instance {name} in {content_dir}")

    parent = unreal.EditorAssetLibrary.load_asset(parent_path)
    if parent is None:
        warn(f"master material not found: {parent_path}")
    else:
        unreal.MaterialEditingLibrary.set_material_instance_parent(instance, parent)

    for parameter, path in (("BaseColor", basecolor), ("Normal", normal), ("ORM", orm)):
        if not path:
            continue
        texture = unreal.EditorAssetLibrary.load_asset(path)
        if texture is None:
            warn(f"texture not found for {parameter}: {path}")
            continue
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(instance, parameter, texture)

    unreal.MaterialEditingLibrary.update_material_instance(instance)
    unreal.EditorAssetLibrary.save_loaded_asset(instance, False)
    log(f"material instance {instance.get_path_name()}")
    return instance.get_path_name()


def find_texture(content_dir: str, *keywords: str) -> str | None:
    """이름에 키워드가 들어간 텍스처 경로를 찾는다."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for asset in registry.get_assets_by_path(content_dir, recursive=True):
        name = str(asset.asset_name).lower()
        if all(key.lower() in name for key in keywords):
            return str(asset.package_name)
    return None


# --------------------------------------------------------------------------- #
# 4) Nanite
# --------------------------------------------------------------------------- #
def enable_nanite(mesh_path: str) -> bool:
    """정적 메시에 Nanite를 켠다. 실패하면 에디터에서 직접 켜도록 안내한다."""
    try:
        mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        if not isinstance(mesh, unreal.StaticMesh):
            warn(f"not a static mesh: {mesh_path}")
            return False
        settings = unreal.MeshNaniteSettings()
        settings.set_editor_property("keep_triangle_percent", 1.0)
        settings.set_editor_property("position_precision", 1)  # 1 = World Relative
        subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        subsystem.set_nanite_settings(mesh, settings, apply_changes=True)
        unreal.EditorAssetLibrary.save_loaded_asset(mesh, False)
        log(f"nanite enabled: {mesh_path}")
        return True
    except Exception as exc:  # noqa: BLE001
        warn(
            f"could not enable Nanite via script ({exc}). "
            "에디터에서 메시를 열고 Details > Nanite Settings > Enable을 켜면 된다."
        )
        return False


# --------------------------------------------------------------------------- #
# 실행
# --------------------------------------------------------------------------- #
def main(asset_name: str = ASSET_NAME, source_dir: str = SOURCE_DIR,
         content_dir: str = CONTENT_DIR, master_material: str = MASTER_MATERIAL) -> None:
    log(f"start: {asset_name} from {source_dir}")
    imported = import_assets(source_dir, content_dir)
    configure_textures(content_dir)

    pixel_name = asset_name.replace(" ", "")
    basecolor = find_texture(content_dir, "basecolor") or find_texture(content_dir, "albedo")
    normal = find_texture(content_dir, "normal")
    orm = find_texture(content_dir, "orm")

    if master_material:
        create_material_instance(
            master_material,
            f"MI_{pixel_name}",
            content_dir,
            basecolor=basecolor,
            normal=normal,
            orm=orm,
        )

    if imported.get("meshes"):
        enable_nanite(imported["meshes"])

    log("done")


if __name__ == "__main__":
    main()
