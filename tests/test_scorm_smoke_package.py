from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scorm_smoke" / "imsmanifest.xml"
PROD_MANIFEST = ROOT / "imsmanifest.xml"
INDEX = ROOT / "scorm_smoke" / "index.html"
BUILD_SCRIPT = ROOT / "scripts" / "build_scorm_smoke.sh"
PROD_BUILD_SCRIPT = ROOT / "scripts" / "build_scorm.sh"
SCORM_JS = ROOT / "static" / "js" / "scorm.js"
SCORM_ADAPTER_JS = ROOT / "static" / "js" / "scorm_adapter.js"
APP_JS = ROOT / "static" / "js" / "app.js"


def test_smoke_manifest_is_scorm_12_single_sco():
    tree = ET.parse(MANIFEST)
    ns = {
        "imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
        "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
    }

    root = tree.getroot()
    assert root.tag.endswith("manifest")
    assert root.findtext("imscp:metadata/imscp:schema", namespaces=ns) == "ADL SCORM"
    assert root.findtext("imscp:metadata/imscp:schemaversion", namespaces=ns) == "1.2"

    resources = root.findall("imscp:resources/imscp:resource", namespaces=ns)
    assert len(resources) == 1
    resource = resources[0]
    assert resource.attrib["href"] == "index.html"
    assert resource.attrib[f"{{{ns['adlcp']}}}scormtype"] == "sco"

    files = {node.attrib["href"] for node in resource.findall("imscp:file", namespaces=ns)}
    assert files == {"index.html", "scorm_config.js", "js/scorm.js"}
    assert all("\\" not in path for path in files)


def test_production_manifest_is_scorm_12_single_sco():
    tree = ET.parse(PROD_MANIFEST)
    ns = {
        "imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
        "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
    }

    root = tree.getroot()
    assert root.attrib["identifier"] == "com.rescuetrails.pfd.station1"
    assert root.findtext("imscp:metadata/imscp:schema", namespaces=ns) == "ADL SCORM"
    assert root.findtext("imscp:metadata/imscp:schemaversion", namespaces=ns) == "1.2"

    resources = root.findall("imscp:resources/imscp:resource", namespaces=ns)
    assert len(resources) == 1
    resource = resources[0]
    assert resource.attrib["href"] == "index.html"
    assert resource.attrib[f"{{{ns['adlcp']}}}scormtype"] == "sco"

    files = {node.attrib["href"] for node in resource.findall("imscp:file", namespaces=ns)}
    required = {
        "index.html",
        "js/scorm_config.js",
        "js/scorm.js",
        "js/scorm_adapter.js",
        "js/app.js",
        "css/style.css",
    }
    assert required <= files
    assert all("\\" not in path for path in files)
    assert not any(path.startswith("http") or path.startswith("/static/") for path in files)


def test_smoke_index_uses_local_scorm_assets_not_remote_launch():
    html = INDEX.read_text()
    assert 'src="scorm_config.js"' in html
    assert 'src="js/scorm.js"' in html
    assert "window.open" not in html
    assert "iframe" not in html.lower()
    assert not re.search(r"https?://", html)


def test_full_index_contains_scorm_station_shell_and_runtime_scripts():
    html = (ROOT / "static" / "index.html").read_text()
    assert "scorm-preboot" in html
    assert 'id="screen-scorm-station1"' in html
    assert 'id="scorm-map0-nodes"' in html
    assert 'id="scorm-pm1-nodes"' in html
    assert 'id="scorm-pt1-nodes"' in html
    assert 'id="scorm-map3-nodes"' in html
    assert 'id="scorm-optional-nodes"' in html
    assert 'src="/static/js/scorm_config.js' in html
    assert 'src="/static/js/scorm.js' in html
    assert 'src="/static/js/scorm_adapter.js' in html
    assert html.index('src="/static/js/scorm_config.js') < html.index('src="/static/js/scorm.js')
    assert html.index('src="/static/js/scorm.js') < html.index('src="/static/js/scorm_adapter.js')
    assert html.index('src="/static/js/scorm_adapter.js') < html.index('src="/static/js/app.js')


def test_scorm_station_shell_uses_map_assets_and_positioned_nodes():
    app_js = APP_JS.read_text()
    css = (ROOT / "static" / "css" / "style.css").read_text()
    assert "MAP0-park.jpeg" in css
    assert "PM1-school_dropoff.jpeg" in css
    assert "PT1-skate_park.jpeg" in css
    assert "cpr_mannequin.jpeg" in css
    assert "--node-x" in css
    assert "--node-y" in css
    assert 'x: 28, y: 50' in app_js
    assert 'x: 52, y: 58' in app_js


def test_smoke_build_script_generates_js_config_and_root_zip():
    script = BUILD_SCRIPT.read_text()
    assert "SCORM_CONFIG_FILE" in script
    assert "window.SCORM_CONFIG = " in script
    assert "cp scorm_smoke/imsmanifest.xml" in script
    assert "cp static/js/scorm.js" in script
    assert "zip -qr" in script


def test_production_build_script_packages_full_static_tree_for_moodle():
    script = PROD_BUILD_SCRIPT.read_text()
    assert "SCORM_CONFIG_FILE" in script
    assert "window.SCORM_CONFIG = " in script
    assert "cp -R static/." in script
    assert "cp imsmanifest.xml" in script
    assert "js/scorm_config.js" in script
    assert "s#/static/##g" in script
    assert "zip -qr" in script


def test_scorm_runtime_uses_bearer_token_not_cross_origin_cookies():
    scorm_js = SCORM_JS.read_text()
    assert 'headers["Authorization"] = `Bearer ${_token}`' in scorm_js
    assert 'credentials: "omit"' in scorm_js
    assert "isLmsLaunch" in scorm_js
    assert "getAccessToken" in scorm_js
    assert "getAttemptId" in scorm_js


def test_app_bootstrap_has_scorm_launch_branch_and_bearer_bridge():
    app_js = APP_JS.read_text()
    assert "window.SCORM_CONFIG" in app_js
    assert "function _isScormLaunch()" in app_js
    assert "function _showScormLaunchError" in app_js
    assert "function _activateScormAndEnter()" in app_js
    assert "headers.Authorization = `Bearer ${scormToken}`" in app_js
    assert "_activateScormAndEnter().catch" in app_js
    assert "RescueTrails.scorm" not in app_js


def test_scorm_launch_errors_do_not_show_login_screen():
    app_js = APP_JS.read_text()
    start = app_js.find("if (_isScormLaunch())")
    assert start != -1
    block = app_js[start:start + 360]
    assert 'showScreen("scorm-station1")' in block
    assert "_showScormLaunchError(err);" in block
    assert 'showScreen("login")' not in block


def test_scorm_minigame_exits_return_to_station_shell():
    app_js = APP_JS.read_text()
    assert "function _returnToScormStation1()" in app_js
    for fn_name in (
        "_exitPatGameToMap",
        "_exitSortGameToMap",
        "_exitGcsToMap",
        "_exitVitalsToMap",
        "_exitLsmToMap",
        "_exitCprBlsSequenceToMap",
    ):
        start = app_js.find(f"function {fn_name}")
        assert start != -1, f"{fn_name} missing"
        block = app_js[start:start + 260]
        assert "if (_returnToScormStation1()) return;" in block, (
            f"{fn_name} must return to scorm-station1 in SCORM mode"
        )


def test_scorm_debrief_close_returns_to_station_shell():
    app_js = APP_JS.read_text()
    start = app_js.find('el("btn-new-session").addEventListener("click"')
    assert start != -1
    block = app_js[start:start + 650]
    assert "resetSessionState();" in block
    assert "if (_returnToScormStation1()) return;" in block
    assert block.index("resetSessionState();") < block.index("if (_returnToScormStation1()) return;")


def test_scorm_debrief_next_action_button_is_suppressed():
    app_js = APP_JS.read_text()
    start = app_js.find('const nextActionBtn = el("btn-debrief-next-action");')
    assert start != -1
    block = app_js[start:start + 900]
    assert "state.scormEnabled" in block
    assert "nextActionBtn.onclick = null;" in block
    assert 'nextActionBtn.classList.add("hidden");' in block


def test_scorm_adapter_keeps_app_decoupled_from_runtime_wrapper():
    adapter_js = SCORM_ADAPTER_JS.read_text()
    assert "window.RescueTrails.scorm" in adapter_js
    assert "window.RescueTrails.scormAdapter" in adapter_js
    assert "isLmsLaunch" in adapter_js
    assert "getAccessToken" in adapter_js
    assert "submitNodeResult" in adapter_js
    assert "getAttemptSummary" in adapter_js
    assert "finish" in adapter_js
