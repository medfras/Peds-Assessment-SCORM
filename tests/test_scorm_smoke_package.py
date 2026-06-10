from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scorm_smoke" / "imsmanifest.xml"
PROD_MANIFEST = ROOT / "imsmanifest.xml"
INDEX = ROOT / "scorm_smoke" / "index.html"
BUILD_SCRIPT = ROOT / "scripts" / "build_scorm_smoke.sh"
PROD_BUILD_SCRIPT = ROOT / "scripts" / "build_scorm.sh"
SCORM_JS = ROOT / "static" / "js" / "scorm.js"
SCORM_ADAPTER_JS = ROOT / "static" / "js" / "scorm_adapter.js"
APP_JS = ROOT / "static" / "js" / "app.js"
STYLE_CSS = ROOT / "static" / "css" / "style.css"


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


def test_pilot_referenced_patient_game_assets_exist():
    croup = json.loads((ROOT / "app/scenarios/pediatric/medical/peds_croup_01.json").read_text())
    croup_image = croup["patient"]["image"]
    assert croup_image
    assert (ROOT / croup_image).exists()

    lsm_cards = json.loads((ROOT / "static/data/games/lsm/cards.json").read_text())
    missing_audio = []
    for card in lsm_cards:
        audio_url = card.get("audio_url") or ""
        if not audio_url.startswith("/static/"):
            continue
        path = unquote(audio_url.split("?", 1)[0]).removeprefix("/static/")
        if not (ROOT / "static" / path).exists():
            missing_audio.append(f"{card.get('id')}: {audio_url}")
    assert missing_audio == []

    dev_sort = json.loads((ROOT / "static/data/games/sorting/peds_dev_milestones.json").read_text())
    missing_images = []
    for bucket in dev_sort.get("buckets", []):
        image_url = bucket.get("image") or ""
        if not image_url.startswith("/static/"):
            continue
        path = unquote(image_url.split("?", 1)[0]).removeprefix("/static/")
        if not (ROOT / "static" / path).exists():
            missing_images.append(f"{bucket.get('id')}: {image_url}")
    assert missing_images == []


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
    assert "find \"${BUILD_PATH}/data\"" in script
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


def test_scorm_resume_state_is_stored_before_home_map_first_render():
    app_js = APP_JS.read_text()
    start = app_js.find("async function _activateAndEnter")
    assert start != -1
    block = app_js[start:start + 2600]
    assert "const isScormEntry = !!options.scormResumeState;" in block
    assert "if (isScormEntry) _storeScormResumeState(options.scormResumeState);" in block
    assert block.index("if (isScormEntry) _storeScormResumeState(options.scormResumeState);") < block.index("buildMenu();")


def test_scorm_launch_defaults_to_home_district_map():
    app_js = APP_JS.read_text()
    start = app_js.find("function _enterScormMapExperience()")
    assert start != -1
    end = app_js.find("function _enterScormOrientationMap", start)
    assert end != -1
    block = app_js[start:end]
    assert "_releaseScormPreboot();" in block
    assert "_station1IsComplete()" in block
    assert '_setScormUiState({ location: "home", map: "map_0", orientationComplete: _station1IsComplete() });' in block
    assert "buildMenu();" in block
    assert 'showScreen("menu");' in block
    assert "_enterScormOrientationMap();" not in block
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


def test_scorm_runtime_trims_saas_auth_and_agency_controls():
    app_js = APP_JS.read_text()

    assert "function _applyScormSaasUiTrim()" in app_js
    trim_start = app_js.find("function _applyScormSaasUiTrim()")
    assert trim_start != -1
    trim_block = app_js[trim_start:trim_start + 900]
    for control_id in [
        "btn-account-settings",
        "btn-menu-logout",
        "category-account-settings",
        "category-menu-logout",
        "btn-switch-agency",
        "screen-login",
        "modal-agency-picker",
        "modal-edit-profile",
    ]:
        assert control_id in trim_block

    show_start = app_js.find("function showScreen(name)")
    assert show_start != -1
    show_block = app_js[show_start:show_start + 450]
    assert 'if (_isScormRuntimeUi() && name === "login") name = "menu";' in show_block
    assert "_applyScormSaasUiTrim();" in show_block

    picker_start = app_js.find("function _showAgencyPicker")
    assert picker_start != -1
    picker_block = app_js[picker_start:picker_start + 250]
    assert "if (_isScormRuntimeUi())" in picker_block
    assert 'hide("modal-agency-picker");' in picker_block

    logout_start = app_js.find('el("btn-menu-logout").addEventListener("click"')
    assert logout_start != -1
    logout_block = app_js[logout_start:logout_start + 260]
    assert "if (_isScormRuntimeUi())" in logout_block
    assert "_clearAuth();" in logout_block


def test_scorm_history_back_returns_incomplete_learner_to_home_map():
    app_js = APP_JS.read_text()
    start = app_js.find('el("btn-history-back").addEventListener("click"')
    assert start != -1
    block = app_js[start:start + 650]

    gate = 'if (state.scormEnabled && !_station1IsComplete())'
    assert gate in block
    assert "_enterScormOrientationMap();" not in block
    assert "buildMenu();" in block
    assert "function _openHistoryScreen(returnTarget = \"menu\")" in app_js
    assert 'el("btn-menu-history").addEventListener("click", () => _openHistoryScreen("menu"));' in app_js
    assert 'el("category-menu-history")?.addEventListener("click", () => _openHistoryScreen("category"));' in app_js
    assert block.index(gate) < block.index('showScreen("menu");')


def test_scorm_auxiliary_back_buttons_return_incomplete_learner_to_home_map():
    app_js = APP_JS.read_text()
    for anchor in (
        'el("btn-progress-back")?.addEventListener("click"',
        'el("btn-notebook-back")?.addEventListener("click"',
        'el("btn-notebook-start")?.addEventListener("click"',
    ):
        start = app_js.find(anchor)
        assert start != -1
        block = app_js[start:start + 650]
        gate = 'if (state.scormEnabled && !_station1IsComplete())'
        assert gate in block
        assert "_enterScormOrientationMap();" not in block
        assert "buildMenu();" in block
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
    assert 'value.startsWith("static/")' in app_js
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
    assert "function _scenarioHistoryEntryPassed(entry)" in app_js
    assert "const pct = _assessmentPctFromEntry(entry);" in app_js
    assert "return pct !== null && pct >= 70;" in app_js
    assert "const completedIds = new Set(scopedHistory.map(h => h.scenarioId));" in app_js
    assert "const persistedComplete = _station1PersistedComplete();" in app_js
    assert "const introSeen = persistedComplete || _station1IntroSeen();" in app_js
    assert 'const completed = persistedComplete || completedIds.has("orientation_01");' in app_js
    assert "const cprComplete = persistedComplete || _station1CprDrillComplete();" in app_js
    assert "const challengesSeen = persistedComplete || (cprComplete && _station1ChallengesSeen());" in app_js
    assert "const ready = introSeen && completed && cprComplete && challengesSeen;" in app_js
    assert "function _station1ScormOrientationComplete()" in app_js
    assert "_getScormUiState()?.orientationComplete === true && !!state.orientationCompletedAt" in app_js
    assert "function _station1PersistedComplete()" in app_js
    assert "if (_station1PersistedComplete()) return true;" in app_js
    assert "return !!state.orientationCompletedAt && !!req.ready;" in app_js
    assert 'if (state.scormEnabled) _setScormUiState({ location: "home", map: "map_0", orientationComplete: true });' in app_js
    assert "return completedIds.has(STATION1_CPR_SCENARIO_ID)" not in app_js
    assert "function _station1CprDrillBestScore()" in app_js
    assert "_station1CprDrillBestScore() >= 70" in app_js
    assert "Number(scores.cpr_bls_concepts || 0)" in app_js
    assert "Number(scores.game_bls || 0)" not in app_js
    assert '{ nodeId: "game_bls", appId: "cpr_bls_concepts"' in app_js
    assert "const completionLocked = !introSeen || !completed || !cprComplete || !challengesSeen;" in app_js
    complete_start = app_js.find("async function _completeStation1FromWrapupNode()")
    assert complete_start != -1
    complete_block = app_js[complete_start:complete_start + 1400]
    assert "const requirements = _station1RequirementsState();" in complete_block
    assert "if (!requirements.ready)" in complete_block
    assert "await _loadProgressFromServer().catch(() => {});" in complete_block
    assert "_refreshGamificationChrome();" in complete_block
    assert "await _refreshScormSummary().catch(() => {});" in complete_block
    assert "_refreshScormChallengeDisplays();" in complete_block
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
    assert "buildMenu();" in enter_block
    assert 'showScreen("menu");' in enter_block

    home_start = app_js.find('el("btn-category-home")?.addEventListener("click"')
    assert home_start != -1
    home_block = app_js[home_start:home_start + 260]
    assert "state.scormEnabled && !_station1IsComplete()" not in home_block
    assert "_enterScormOrientationMap();" not in home_block
    assert "buildMenu();" in home_block
    assert 'showScreen("menu");' in home_block


def test_training_center_drills_are_map_unlock_gated():
    app_js = APP_JS.read_text()

    assert "const PEDS_MAP_DEV_UNLOCKED = false;" in app_js
    assert "function _buildAccessibleTrainingCenterMaps()" in app_js
    build_start = app_js.find("function _buildAccessibleTrainingCenterMaps()")
    assert build_start != -1
    build_block = app_js[build_start:build_start + 900]
    assert 'const accessible = new Set(["station_1"]);' in build_block
    assert "if (!_station1IsComplete()) return accessible;" in build_block
    assert 'accessible.add("map_0");' in build_block
    assert "_computeMapUnlockState(passedIds, MAP_TOPOLOGY, pedsMapCompleted)" in build_block

    filter_start = app_js.find("function _trainingCenterDrillMapUnlocked")
    assert filter_start != -1
    filter_block = app_js[filter_start:filter_start + 260]
    assert "if (!mapId) return _station1IsComplete();" in filter_block
    assert "return !!accessibleMaps?.has?.(mapId);" in filter_block
    assert "catalog.filter(g => _trainingCenterDrillMapUnlocked(g, accessibleMaps))" in app_js
    assert "fullCatalog.filter(g => _trainingCenterDrillMapUnlocked(g, accessibleMaps))" in app_js
    assert "unlockedIds.has(g.type) || !g.mapId || accessibleMaps.has(g.mapId)" not in app_js


def test_locked_pediatric_maps_do_not_render_from_stale_state():
    app_js = APP_JS.read_text()
    render_start = app_js.find("function _renderPedsMap(mapId = null)")
    assert render_start != -1
    render_block = app_js[render_start:render_start + 1800]

    assert "const currentUnlock = unlockState?.get(currentMapId);" in render_block
    assert "const currentLocked = state.scormEnabled" in render_block
    assert "!_scormPedsMapAllowed(currentMapId) || !_scormMapRouteUnlocked(currentMapId)" in render_block
    assert 'currentMapId !== "map_0" && !currentUnlock?.unlocked && !currentUnlock?.partial' in render_block
    assert 'currentMapId = "map_0";' in render_block
    assert "_savePedsJourneyState();" in render_block


def test_district_map_station_nodes_match_pilot_layout():
    app_js = APP_JS.read_text()
    css = (ROOT / "static" / "css" / "style.css").read_text()

    assert '{ id: "station_1"' in app_js
    assert 'mapNode: { x: 595, y: 165, label: "Station 1", plannedText: "Start here" }' in app_js
    assert '{ id: "station_2"' in app_js
    assert 'title: "Station 2"' in app_js
    assert 'mapNode: { x: 90, y: 165, label: "Station 2", plannedText: "Planned" }' in app_js
    assert '{ id: "station_3"' in app_js
    assert 'title: "Station 3"' in app_js
    assert 'mapNode: { x: 470, y: 400, label: "Station 3", plannedText: "Planned" }' in app_js

    render_start = app_js.find("function _genDistrictMapSVG(history)")
    assert render_start != -1
    render_block = app_js[render_start:render_start + 1600]
    assert 'const active = d.status === "active";' in render_block
    assert '${active ? \' role="button" tabindex="0"\' : ""}' in render_block
    assert 'nodeLabel = d.mapNode.label || d.title' in render_block
    assert 'class="hv2-station-node-mask"' in render_block
    assert 'zone.classList.contains("locked")) return;' in app_js
    assert ".hv2-station-node-mask" in css
    assert "fill: #f8fafc;" in css


def test_scorm_launch_errors_do_not_show_login_screen():
    app_js = APP_JS.read_text()
    start = app_js.find("if (_isScormLaunch())")
    assert start != -1
    block = app_js[start:start + 360]
    assert 'document.documentElement.classList.add("scorm-preboot");' in block
    assert "_showScormLaunchError(err);" in block
    assert 'showScreen("login")' not in block


def test_scorm_auth_expiry_does_not_redirect_to_saas_login():
    app_js = APP_JS.read_text()
    assert "function _handleScormAuthExpired()" in app_js
    assert "Moodle session expired. Exit and relaunch the activity to continue syncing progress." in app_js

    auth_start = app_js.find("async function authFetch")
    assert auth_start != -1
    auth_block = app_js[auth_start:auth_start + 1700]
    assert "if (_handleScormAuthExpired()) return res;" in auth_block

    scenario_start = app_js.find("async function startScenarioWithOptions")
    assert scenario_start != -1
    scenario_block = app_js[scenario_start:scenario_start + 4500]
    assert "if (_handleScormAuthExpired()) return false;" in scenario_block


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


def test_scorm_leave_confirm_returns_to_production_map():
    app_js = APP_JS.read_text()
    start = app_js.find('el("btn-leave-confirm").addEventListener("click"')
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
    assert "getDuplicateLaunchWarning" in adapter_js
    assert "submitNodeResult" in adapter_js
    assert "getAttemptSummary" in adapter_js
    assert "finish" in adapter_js
    assert "getUiState" in adapter_js
    assert "setUiState" in adapter_js


def test_scorm_runtime_tracks_duplicate_launch_without_learner_toast():
    scorm_js = SCORM_JS.read_text()
    app_js = APP_JS.read_text()

    assert "launch_id:       _launchId" in scorm_js
    assert "launch-heartbeat" in scorm_js
    assert "launch-close" in scorm_js
    assert "navigator.sendBeacon" in scorm_js
    assert 'window.addEventListener("pagehide", _notifyLaunchClosed)' in scorm_js
    assert "rt:scormDuplicateLaunch" in scorm_js
    assert "getDuplicateLaunchWarning" in scorm_js
    assert "function _showScormDuplicateLaunchWarning" in app_js
    warning_idx = app_js.find("function _showScormDuplicateLaunchWarning")
    assert warning_idx != -1
    warning_block = app_js[warning_idx:warning_idx + 450]
    assert "showToast" not in warning_block
    assert "suppressed for learner" in warning_block
    assert 'window.addEventListener("rt:scormDuplicateLaunch"' in app_js


def test_scorm_suspend_data_preserves_ui_location_for_resume():
    scorm_js = SCORM_JS.read_text()
    app_js = APP_JS.read_text()
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
    start = app_js.find("function _setScormUiState")
    assert start != -1
    block = app_js[start:start + 500]
    assert "next.orientationComplete === true && !state.orientationCompletedAt" in block
    assert "next.orientationComplete = false;" in block


def test_scorm_pass_requirements_render_in_active_challenges_modal():
    app_js = APP_JS.read_text()
    scorm_js = SCORM_JS.read_text()
    assert "function _scormPassChallengeForDisplay()" in app_js
    assert "scorm-peds-ce-challenge" in app_js
    assert "Pediatric Medical scenarios" in app_js
    assert "Pediatric Trauma scenarios" in app_js
    assert "Training time" in app_js
    assert "const ceMinutes = Math.min(Math.floor(ceSeconds / 60), 60);" in app_js
    assert "1 hour logged from orientation, drills, and scenarios" in app_js
    assert "remaining" in app_js
    assert "Number(ce.xp_required || 1200)" in app_js
    assert 'title: isPfdPassChallenge ? "Pediatric Patient Assessment"' in app_js
    assert "xp_required: xpRequired" in app_js
    assert "Earn at least ${xpRequired} XP" in app_js
    assert "custom_items" in app_js
    assert "function _activeChallengesForDisplay()" in app_js
    assert "_activeChallengesForDisplay().find" in app_js
    assert "const xpOk = isPfdPassChallenge ? xp >= xpRequired : !!ce.xp_ok;" in app_js
    assert "complete: isPfdPassChallenge ? passComplete : !!ce.complete" in app_js
    assert "const progressDone = pm1Done + pt1Done + (timeDone ? 1 : 0) + (xpOk ? 1 : 0);" in app_js
    assert "const progressTotal = pm1Required + pt1Required + 2;" in app_js
    assert "scenarios_total: progressTotal" in app_js
    assert "scenarios_completed: progressDone" in app_js
    assert "const xpOk = isPfdPassChallenge ? xp >= xpRequired : !!cc.xp_ok;" in scorm_js
    assert "complete:            isPfdPassChallenge ? passComplete : !!cc.complete" in scorm_js
    assert "function _summaryPassGate(summary)" in scorm_js
    assert "const ceComplete = _summaryPassGate(summary);" in scorm_js


def test_frontend_awards_refresh_gamification_chrome_without_waiting_for_navigation():
    app_js = APP_JS.read_text()
    assert "function _applyGamificationAward(" in app_js
    assert "_loadProgressFromServer(options = {})" in app_js
    assert "if (minXp !== null) _progressCache.xp = Math.max(Number(_progressCache.xp || 0), minXp);" in app_js
    assert "_applyGamificationAward({ xpEarned });" in app_js
    assert "_applyGamificationAward({ xpEarned: Number(data.xp_earned || 0) });" in app_js
    assert "_applyGamificationAward({ xpEarned: xp, newBadges: badges });" in app_js
    assert "_refreshGamificationChrome();" in app_js


def test_scorm_production_peds_maps_use_backend_node_state():
    app_js = APP_JS.read_text()
    assert "function _scormNodeCompleteByNodeId" in app_js
    assert "function _scormAppComplete" in app_js
    assert "function _scormScenarioLocked" in app_js
    assert "function _scormVisibleMapScenarioProgress" in app_js
    assert "function _scormPedsSidebarProgress" in app_js
    assert "function _scormMapRouteUnlocked" in app_js
    assert '_SCORM_PM1_UNLOCK_SCENARIO_ID = "peds_diabetic_emergency_01"' in app_js
    assert '_SCORM_PT1_UNLOCK_SCENARIO_ID = "peds_trauma_01_soft_tissue"' in app_js
    assert 'if (id === "map_0")' in app_js
    assert 'if (id === "pm1")' in app_js
    assert 'if (id === "pt1")' in app_js
    assert "complete: pm1Unlocked && pt1Unlocked, pct" in app_js
    assert 'const groupKey = mapIdText === "map_0" ? "map0" : mapIdText;' in app_js
    assert 'const scormNodes = (_SCORM_NODE_GROUPS[groupKey] || []).filter(node => node.type === "scenario");' in app_js
    assert "const completed = scenarios.filter(s => _scormAppComplete(s.appId || s.id)).length;" in app_js
    assert "pct: total ? Math.round((completed / total) * 100) : 100" in app_js
    assert "complete: progress.complete, pct: progress.pct" in app_js

    render_start = app_js.find("function _renderPedsMap(mapId")
    assert render_start != -1
    render_block = app_js[render_start:render_start + 14000]
    assert "Object.entries(_SCORM_NODE_BY_APP_ID)" in render_block
    assert "completedIds.add(appId);" in render_block
    assert "const { passedIds: _passedIds, pedsMapCompleted: _pedsMapCompleted } = _pedsMapCompletionSets();" in render_block
    assert "_scormMapRouteUnlocked(exit.to)" in render_block
    assert "const scormLocked = !isPh && _scormScenarioLocked(s.id, currentMapId);" in render_block
    assert "Complete the Map 0 route scenario to unlock" in render_block
    assert "completedGameIds.has(completionId) || _scormAppComplete(completionId)" in render_block

    trail_start = app_js.find('if (state.scormEnabled) {\n      const pm1Locked = !_scormMapRouteUnlocked("pm1");')
    assert trail_start != -1
    trail_block = app_js[trail_start:trail_start + 1400]
    assert 'const pm1Locked = !_scormMapRouteUnlocked("pm1");' in trail_block
    assert 'const pt1Locked = !_scormMapRouteUnlocked("pt1");' in trail_block
    assert 'data-peds-nav="pm1" ${pm1Locked ? "disabled" : ""}' in trail_block
    assert 'data-peds-nav="pt1" ${pt1Locked ? "disabled" : ""}' in trail_block

    sidebar_start = app_js.find("function _renderPedsMapSidebar")
    assert sidebar_start != -1
    sidebar_block = app_js[sidebar_start:sidebar_start + 3600]
    assert "PEDS_MAP_DATA.filter(m => _scormPedsMapAllowed(m.id))" in sidebar_block
    assert "_scormPedsSidebarProgress(m.id)" in sidebar_block
    assert "_scormPedsSidebarProgress(mapId)" in sidebar_block


def test_lung_sound_results_modal_is_viewport_bounded():
    css = STYLE_CSS.read_text()
    assert "#screen-lsm-game #lsm-results" in css
    block_start = css.index("#screen-lsm-game #lsm-results")
    block = css[block_start:css.index(".mg-result-grid", block_start)]
    assert "top: 1rem;" in block
    assert "bottom: 1rem;" in block
    assert "max-height: none;" in block
    assert "translateX(-50%)" in block


def test_scorm_pediatric_district_progress_counts_pilot_calls_only():
    app_js = APP_JS.read_text()

    completion_sets_start = app_js.find("function _pedsMapCompletionSets")
    assert completion_sets_start != -1
    completion_sets_block = app_js[completion_sets_start:completion_sets_start + 1000]
    assert "const passedIds = _scenarioPassedHistorySet();" in completion_sets_block

    passed_start = app_js.find("function _scenarioPassedHistorySet")
    assert passed_start != -1
    passed_block = app_js[passed_start:passed_start + 1000]
    assert "Object.entries(_SCORM_NODE_BY_APP_ID)" in passed_block
    assert "passedIds.add(appId);" in passed_block

    scorm_counts_start = app_js.find("function _scormPediatricDistrictActivityCounts")
    assert scorm_counts_start != -1
    scorm_counts_block = app_js[scorm_counts_start:scorm_counts_start + 500]
    assert ".filter(m => _scormPedsMapAllowed(m.id))" in scorm_counts_block
    assert ".map(m => m.id)" in scorm_counts_block
    assert "return _pedsMapActivityCounts(mapIds, _scenarioPassedHistorySet());" in scorm_counts_block

    counts_start = app_js.find("function _districtActivityCounts")
    assert counts_start != -1
    counts_block = app_js[counts_start:counts_start + 1000]
    assert 'if (state.scormEnabled && districtId === "pediatrics")' in counts_block
    assert "return _scormPediatricDistrictActivityCounts();" in counts_block
    assert "const { passedIds, pedsMapCompleted } = _pedsMapCompletionSets();" in counts_block
    assert '.filter(m => !state.scormEnabled || _scormPedsMapAllowed(m.id))' in counts_block
    assert "return _pedsMapActivityCounts(mapIds, passedIds);" in counts_block

    progress_start = app_js.find("function _districtProgress")
    assert progress_start != -1
    progress_block = app_js[progress_start:progress_start + 700]
    assert "const total = counts.callsTotal;" in progress_block
    assert "const done = counts.callsComplete;" in progress_block
    assert 'state.scormEnabled && districtId === "pediatrics"' in progress_block
    assert "Math.round((done / total) * 100)" in progress_block
    assert "counts.drillsTotal" not in progress_block
    assert "counts.drillsComplete" not in progress_block

    svg_start = app_js.find("function _genDistrictMapSVG(history)")
    assert svg_start != -1
    svg_block = app_js[svg_start:svg_start + 1800]
    assert "const progress  = _districtProgress(d.id);" in svg_block
    assert "history.some(h => h.scenarioId === s.id)" not in svg_block


def test_intervention_response_applies_authoritative_vitals_snapshot():
    app_js = APP_JS.read_text()
    assert "function _applyCurrentVitalsSnapshot(vitals = {})" in app_js

    apply_start = app_js.find("async function applyInterventionAndRecord")
    assert apply_start != -1
    apply_block = app_js[apply_start:apply_start + 2200]
    assert "data?.vitals && typeof data.vitals === \"object\"" in apply_block
    assert "_applyCurrentVitalsSnapshot(data.vitals);" in apply_block

    ws_start = app_js.find("async function startVitalsWs")
    assert ws_start != -1
    ws_block = app_js[ws_start:ws_start + 2200]
    assert "_applyCurrentVitalsSnapshot(data.vitals);" in ws_block


def test_scenario_launch_preloads_scene_images_before_display():
    app_js = APP_JS.read_text()
    assert "const _scenarioImagePreloads = new Map();" in app_js
    assert "function _preloadScenarioImages(scenario = {})" in app_js
    assert "_preloadImage(sceneImage || patientImage, { priority: \"high\" });" in app_js

    prefetch_start = app_js.find("function _prefetchScenarioData")
    assert prefetch_start != -1
    prefetch_block = app_js[prefetch_start:prefetch_start + 1200]
    assert "if (data) _preloadScenarioImages(data);" in prefetch_block

    launch_start = app_js.find("async function startScenarioWithOptions")
    assert launch_start != -1
    launch_block = app_js[launch_start:launch_start + 2600]
    assert "_preloadScenarioImages(scenarioData);" in launch_block
    assert launch_block.index("_preloadScenarioImages(scenarioData);") < launch_block.index('const warning = _scenarioJurisdictionWarning(scenarioData);')

    sim_start = app_js.find("function startSim")
    assert sim_start != -1
    sim_block = app_js[sim_start:sim_start + 3600]
    assert 'el("pt-photo").loading = "eager";' in sim_block
    arrival_start = app_js.find('const arrImg = el("arrival-image");', sim_start)
    assert arrival_start != -1
    arrival_block = app_js[arrival_start:arrival_start + 700]
    assert 'arrImg.loading = "eager";' in arrival_block


def test_pediatric_maps_do_not_render_fog_of_war_overlay():
    app_js = APP_JS.read_text()
    css = STYLE_CSS.read_text()
    combined = f"{app_js}\n{css}"
    assert "peds-fog" not in combined
    assert "trail-map-btn--fog" not in combined
    assert "peds-fog-patch" not in combined
