"""대시보드 카드(daejeon-bus-card) 자동 등록.

www/daejeon-bus-card.js 를 /daejeon_bus/daejeon-bus-card.js 로 서빙하고 프런트엔드에
모듈로 추가한다. 사용자가 리소스를 따로 등록하거나 HACS 카드를 설치할 필요가 없다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = Path(__file__).parent / "www" / "daejeon-bus-card.js"
CARD_URL = f"/{DOMAIN}/daejeon-bus-card.js"
DATA_CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def async_register_card(hass: HomeAssistant) -> bool:
    """카드 JS 등록. http/frontend 가 없는 환경(테스트 등)에서는 건너뛴다."""
    if hass.data.get(DATA_CARD_REGISTERED):
        return True
    if getattr(hass, "http", None) is None or "frontend" not in hass.config.components:
        _LOGGER.debug("http/frontend 가 없어 대시보드 카드를 등록하지 않습니다")
        return False

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    # 파일이 바뀌면 브라우저 캐시를 무효화하도록 수정 시각을 붙인다
    mtime = await hass.async_add_executor_job(lambda: int(CARD_FILE.stat().st_mtime))
    add_extra_js_url(hass, f"{CARD_URL}?v={mtime}")
    hass.data[DATA_CARD_REGISTERED] = True
    _LOGGER.debug("대시보드 카드 등록: %s", CARD_URL)
    return True
