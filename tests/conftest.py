import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def cache_file(hass, tmp_path):
    """정류장 이름 캐시 파일을 임시 폴더에 두고 경로를 돌려준다."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path / "daejeon_bus_stop_names.json"


@pytest.fixture(autouse=True)
def _isolated_config_dir(hass, tmp_path):
    # 모든 테스트에서 캐시 파일이 저장소 폴더에 생기지 않도록
    hass.config.config_dir = str(tmp_path)
