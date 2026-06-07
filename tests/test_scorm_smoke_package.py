from __future__ import annotations

import json
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
    assert "s#/static/#../#g" in script
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
    assert "function _hideScormLaunchStatus()" in app_js
    assert "function _releaseScormPreboot()" in app_js
    assert "function _enterScormMapExperience()" in app_js
    assert "function _activateScormAndEnter()" in app_js
    assert "headers.Authorization = `Bearer ${scormToken}`" in app_js
    assert "_activateScormAndEnter().catch" in app_js
    assert "RescueTrails.scorm" not in app_js


def test_scorm_launch_enters_orientation_until_complete_then_home():
    app_js = APP_JS.read_text()
    start = app_js.find("function _enterScormMapExperience()")
    assert start != -1
    end = app_js.find("function _enterScormOrientationMap", start)
    assert end != -1
    block = app_js[start:end]
    assert "_releaseScormPreboot();" in block
    assert "_station1IsComplete()" in block
    assert '_setScormUiState({ location: "home", map: "map_0", orientationComplete: true });' in block
    assert "buildMenu();" in block
    assert 'showScreen("menu");' in block
    assert "_enterScormOrientationMap();" in block
    assert "_enterScormPedsMap(uiState.map" not in block
    assert 'showCategoryScreen("pediatrics")' not in block
    assert 'showScreen("scorm-station1")' not in block


def test_scorm_home_sidebars_hide_account_controls_and_use_trails_copy():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = APP_JS.read_text()

    assert 'id="btn-menu-history" title="History"' in html
    assert 'id="category-menu-history" title="History"' in html
    assert 'id="btn-account-settings" class="hidden hv2-nav-item"' in html
    assert 'id="btn-menu-logout" class="hidden hv2-nav-item hv2-nav-item--danger"' in html
    assert 'id="category-account-settings" class="hidden hv2-nav-item"' in html
    assert 'id="category-menu-logout" class="hidden hv2-nav-item hv2-nav-item--danger"' in html
    assert 'el("category-menu-history")?.addEventListener("click"' in app_js
    assert "if (state.scormEnabled) return;" in app_js
    assert "const retakeButton = state.scormEnabled" in app_js
    assert "Trails, unlock progress, and available maps." in app_js
    assert "Trails To / From Current" in app_js
    assert "No connected trails from this map." in app_js
    assert "Paths To / From Current" not in app_js


def test_scorm_history_back_respects_incomplete_orientation_gate():
    app_js = APP_JS.read_text()
    start = app_js.find('el("btn-history-back").addEventListener("click"')
    assert start != -1
    block = app_js[start:start + 650]

    gate = 'if (state.scormEnabled && !_station1IsComplete())'
    assert gate in block
    assert "_enterScormOrientationMap();" in block
    assert "function _openHistoryScreen(returnTarget = \"menu\")" in app_js
    assert 'el("btn-menu-history").addEventListener("click", () => _openHistoryScreen("menu"));' in app_js
    assert 'el("category-menu-history")?.addEventListener("click", () => _openHistoryScreen("category"));' in app_js
    assert block.index(gate) < block.index('showScreen("menu");')


def test_leaderboard_modal_uses_solid_light_shell():
    html = (ROOT / "static" / "index.html").read_text()
    css = (ROOT / "static" / "css" / "style.css").read_text()

    assert 'id="modal-leaderboard" class="hidden fixed inset-0 bg-black/45' in html
    assert "leaderboard-modal-shell bg-white border border-gray-200 rounded-2xl" in html
    assert "leaderboard-modal-header px-5 py-4 border-b border-gray-200 bg-stone-50" in html
    assert "leaderboard-modal-body flex-1 min-h-0 overflow-y-auto bg-stone-50" in html
    assert "#modal-leaderboard .leaderboard-modal-shell" in css
    assert "#modal-leaderboard .lb-ticker-strip" in css
    assert "#modal-leaderboard #btn-leaderboard-refresh" in css
    assert "menu-modal-shell rounded-2xl w-full max-w-sm" not in html


def test_scorm_runtime_uses_compact_sim_and_localizes_backend_static_assets():
    app_js = APP_JS.read_text()
    css = (ROOT / "static" / "css" / "style.css").read_text()
    orientation = json.loads((ROOT / "app" / "scenarios" / "orientation_01.json").read_text())
    assert "function _scormAssetUrl(url)" in app_js
    assert 'const staticPrefix = `/${"static"}/`;' in app_js
    assert "_scormAssetUrl(s.scene.image || s.patient.image || \"\")" in app_js
    assert "_scormAssetUrl(arrivalImage)" in app_js
    assert "function _isScormEmbeddedFrame()" in app_js
    assert "window.self !== window.top" in app_js
    mobile_start = app_js.find("function _isSimMobileTarget()")
    assert mobile_start != -1
    mobile_end = app_js.find("function _isHv2MobileTarget()", mobile_start)
    assert mobile_end != -1
    mobile_block = app_js[mobile_start:mobile_end]
    assert "if (_isScormEmbeddedFrame()) return compact;" in mobile_block
    assert "if (_isScormEmbeddedFrame()) return true;" not in mobile_block
    assert "state.scormEnabled || document.documentElement.classList.contains(\"scorm-runtime\")" not in mobile_block
    assert "function _getScormUiState()" in app_js
    assert "function _setScormUiState(ui)" in app_js
    assert 'el("btn-category-home")?.classList.toggle("hidden", districtId === "other");' in app_js
    assert "state.scormEnabled && !_scormPedsMapAllowed" not in app_js
    assert ".scorm-runtime #screen-sim.sim-mobile-active" in css
    assert ".scorm-runtime #screen-sim.sim-mobile-active .sim-panel-left .tab-content" in css
    assert ".scorm-runtime #btn-voice-input" not in css
    assert ".scorm-runtime #tour-tip" in css
    assert 'if (_returnToScormStation1()) return;' in app_js
    assert '_tourDone();' in app_js
    jake_tts = orientation["personas"]["jake"]["tts"]
    assert orientation["personas"]["jake"]["sex"] == "male"
    assert jake_tts["gender"] == "male"
    assert jake_tts["voice_role"] == "patient"
    assert (ROOT / "static" / "img" / "district-map-1600.jpg").exists()
    assert (ROOT / "static" / "img" / "district-map.jpg").exists()


def test_scorm_station1_wrapup_requires_full_orientation_sequence():
    app_js = APP_JS.read_text()
    assert "function _station1StorageScope()" in app_js
    assert 'window.RescueTrails?.["scormAdapter"]?.getAttemptId?.()' in app_js
    assert "const scopePart = scope ? `scorm:${scope}:` : \"\";" in app_js
    assert "function _station1RequirementsState(history = null)" in app_js
    assert "const ready = introSeen && completed && cprComplete && challengesSeen;" in app_js
    assert "function _station1ScormOrientationComplete()" in app_js
    assert "_getScormUiState()?.orientationComplete === true" in app_js
    assert "if (_station1ScormOrientationComplete()) return true;" in app_js
    assert "return !!state.orientationCompletedAt && !!req.ready;" in app_js
    assert 'if (state.scormEnabled) _setScormUiState({ location: "home", map: "map_0", orientationComplete: true });' in app_js
    assert "return completedIds.has(STATION1_CPR_SCENARIO_ID);" in app_js
    assert "const completionLocked = !introSeen || !completed || !cprComplete || !challengesSeen;" in app_js
    complete_start = app_js.find("async function _completeStation1FromWrapupNode()")
    assert complete_start != -1
    complete_block = app_js[complete_start:complete_start + 500]
    assert "const requirements = _station1RequirementsState();" in complete_block
    assert "if (!requirements.ready)" in complete_block
    sidebar_start = app_js.find("function _renderStation1Sidebar")
    assert sidebar_start != -1
    sidebar_block = app_js[sidebar_start:sidebar_start + 900]
    assert "{ label: \"Challenges Briefing\", done: challengesSeen }" in sidebar_block
    assert "_station1ChallengesSeen()" not in sidebar_block


def test_pediatric_district_is_blocked_until_station1_complete():
    app_js = APP_JS.read_text()
    show_start = app_js.find("function showCategoryScreen(categoryKey)")
    assert show_start != -1
    show_block = app_js[show_start:show_start + 1100]
    assert 'if (districtId === "pediatrics")' in show_block
    assert "!_station1IsComplete()" in show_block
    assert "Complete Station 1 before entering Pediatric Community Response." in show_block
    assert '_categoryView = { mode: "district", districtId: "station_1" };' in show_block
    assert "_renderStation1Map();" in show_block

    enter_start = app_js.find("function _enterScormPedsMap")
    assert enter_start != -1
    enter_block = app_js[enter_start:enter_start + 260]
    assert "if (!_station1IsComplete())" in enter_block
    assert "_enterScormOrientationMap();" in enter_block

    home_start = app_js.find('el("btn-category-home")?.addEventListener("click"')
    assert home_start != -1
    home_block = app_js[home_start:home_start + 260]
    assert "state.scormEnabled && !_station1IsComplete()" in home_block
    assert "_enterScormOrientationMap();" in home_block


def test_scorm_launch_errors_do_not_show_login_screen():
    app_js = APP_JS.read_text()
    start = app_js.find("if (_isScormLaunch())")
    assert start != -1
    block = app_js[start:start + 360]
    assert 'document.documentElement.classList.add("scorm-preboot");' in block
    assert "_showScormLaunchError(err);" in block
    assert 'showScreen("login")' not in block


def test_scorm_minigame_exits_return_to_production_map():
    app_js = APP_JS.read_text()
    assert "function _returnToScormStation1()" in app_js
    start = app_js.find("function _returnToScormStation1()")
    block = app_js[start:start + 650]
    assert "_renderStation1Map();" in block
    assert "_renderPediatricsJourney({ preserveTrail: true });" in block
    assert 'showScreen("scorm-station1")' not in block
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
            f"{fn_name} must return to the production map in SCORM mode"
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
    assert "getUiState" in adapter_js
    assert "setUiState" in adapter_js


def test_scorm_suspend_data_preserves_ui_location_for_resume():
    scorm_js = SCORM_JS.read_text()
    assert '"ui": { "location": "orientation" | "home" | "peds", "map": "map_0" | "pm1" | "pt1", "orientationComplete": true }' in scorm_js
    assert "let _uiState = null;" in scorm_js
    assert "function _sanitizeUiState(ui)" in scorm_js
    assert 'ui.location === "home"' in scorm_js
    assert "ui.orientationComplete === true" in scorm_js
    assert "mirror.ui = _uiState" in scorm_js
    assert "function getUiState()" in scorm_js
    assert "function setUiState(ui)" in scorm_js
    assert "pfd_station1_scorm_pass" in scorm_js
    assert "training_time_done" in scorm_js


def test_scorm_pass_requirements_render_in_active_challenges_modal():
    app_js = APP_JS.read_text()
    assert "function _scormPassChallengeForDisplay()" in app_js
    assert "scorm-peds-ce-challenge" in app_js
    assert "Pediatric Medical scenarios" in app_js
    assert "Pediatric Trauma scenarios" in app_js
    assert "Training time" in app_js
    assert "950 XP" in app_js
    assert "custom_items" in app_js
    assert "function _activeChallengesForDisplay()" in app_js
    assert "_activeChallengesForDisplay().find" in app_js
