"""대시보드 카드(daejeon-bus-card) 자동 등록.

www/daejeon-bus-card.js 를 /daejeon_bus/daejeon-bus-card.js 로 서빙하고 프런트엔드에
모듈로 추가한다. 사용자가 리소스를 따로 등록하거나 HACS 카드를 설치할 필요가 없다.

두 가지 방법으로 함께 등록한다.
1. 프런트엔드 extra module (HA 첫 화면 HTML 에 포함)
2. 대시보드 리소스 (저장소 모드일 때). 대시보드를 열 때마다 불러오므로, 브라우저가
   예전 첫 화면을 캐시해 1번이 빠진 경우에도 카드가 로드된다.

frontend 가 아직 준비되지 않았으면 HA 시작 완료 후 다시 시도한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = Path(__file__).parent / "www" / "daejeon-bus-card.js"
CARD_URL = f"/{DOMAIN}/daejeon-bus-card.js"
DATA_STATIC = f"{DOMAIN}_card_static"
DATA_CARD_REGISTERED = f"{DOMAIN}_card_registered"
DATA_RETRY = f"{DOMAIN}_card_retry"


def _frontend_ready(hass: HomeAssistant) -> bool:
    try:
        from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
    except ImportError:  # frontend 패키지가 없는 환경
        return False
    return DATA_EXTRA_MODULE_URL in hass.data


async def async_register_card(hass: HomeAssistant) -> bool:
    """카드 JS 등록. 이미 등록했으면 아무것도 하지 않는다."""
    if hass.data.get(DATA_CARD_REGISTERED):
        return True

    # 1) 파일 서빙 (http 만 있으면 가능)
    if not hass.data.get(DATA_STATIC) and getattr(hass, "http", None) is not None:
        from homeassistant.components.http import StaticPathConfig

        # 주소에 버전(?v=수정 시각)이 붙으므로 브라우저 캐시를 써도 업데이트가 반영된다
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=True)]
        )
        hass.data[DATA_STATIC] = True

    # 2) 프런트엔드에 모듈로 추가 (frontend 준비 후)
    if hass.data.get(DATA_STATIC) and _frontend_ready(hass):
        from homeassistant.components.frontend import add_extra_js_url

        # 파일이 바뀌면 브라우저 캐시를 무효화하도록 수정 시각을 붙인다
        mtime = await hass.async_add_executor_job(lambda: int(CARD_FILE.stat().st_mtime))
        url = f"{CARD_URL}?v={mtime}"
        add_extra_js_url(hass, url)
        await _async_sync_lovelace_resource(hass, url)
        hass.data[DATA_CARD_REGISTERED] = True
        _LOGGER.info("대전 버스 대시보드 카드를 등록했습니다: %s", url)
        return True

    # 아직 준비 안 됨: HA 시작 완료 후 한 번 더 시도
    if getattr(hass, "http", None) is not None and not hass.data.get(DATA_RETRY):
        hass.data[DATA_RETRY] = True

        async def _retry(_event: Event) -> None:
            if not await async_register_card(hass):
                _LOGGER.warning(
                    "대전 버스 대시보드 카드를 자동 등록하지 못했습니다. 대시보드 → 리소스에 "
                    "%s (JavaScript 모듈)을 직접 추가하세요.",
                    CARD_URL,
                )

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _retry)
    _LOGGER.debug("프런트엔드가 아직 준비되지 않아 카드 등록을 미룹니다")
    return False


def _resource_collection(hass: HomeAssistant):
    """저장소 모드 대시보드 리소스 컬렉션 (YAML 모드거나 없으면 None)."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import ResourceStorageCollection
    except ImportError:
        return None
    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    return resources if isinstance(resources, ResourceStorageCollection) else None


async def _async_sync_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """대시보드 리소스에 카드 등록 (있으면 버전만 갱신)."""
    resources = _resource_collection(hass)
    if resources is None:
        return
    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == CARD_URL:
                if item["url"] != url:
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                return
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("대시보드 리소스에 대전 버스 카드를 추가했습니다: %s", url)
    except Exception as err:  # noqa: BLE001 - 리소스 등록 실패해도 extra module 로 동작
        _LOGGER.debug("대시보드 리소스 등록 실패: %s", err)


async def async_remove_lovelace_resource(hass: HomeAssistant) -> None:
    """통합구성요소를 모두 지울 때 대시보드 리소스도 정리."""
    resources = _resource_collection(hass)
    if resources is None:
        return
    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for item in list(resources.async_items()):
            if str(item.get("url", "")).split("?")[0] == CARD_URL:
                await resources.async_delete_item(item["id"])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("대시보드 리소스 삭제 실패: %s", err)
