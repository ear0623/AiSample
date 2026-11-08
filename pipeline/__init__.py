"""AI 3D 에셋 생성 파이프라인 패키지.

``mcp_token_optimizer`` 는 MCP 토큰 최적화, ``open_world_helper`` 는
오픈월드 제작 계획 계산기, ``indoor_metric_helper`` 는 실내 탐사 공간 수치
계산기, ``vehicle_asset_optimizer`` 는 차량 텍스처 VRAM 예산과 익스플로전·
케이지 검증기로, 넷 다 표준 라이브러리만 사용합니다.
"""

__all__ = [
    "tripo_client",
    "tripo_pbr_generator",
    "texture_packer",
    "glb_texture_tools",
    "mcp_token_optimizer",
    "open_world_helper",
    "indoor_metric_helper",
    "vehicle_asset_optimizer",
]
