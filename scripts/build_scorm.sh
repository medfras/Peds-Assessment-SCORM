#!/usr/bin/env bash
set -euo pipefail

SCORM_CONFIG_FILE="${SCORM_CONFIG_FILE:-PEDS_ASSESSMENT/scorm_config.local.json}"
BUILD_DIR="${BUILD_DIR:-scorm_build}"
ZIP_FILE="${ZIP_FILE:-pfd_station1_scorm.zip}"
ROOT_DIR="$(pwd)"

if [[ ! -f "${SCORM_CONFIG_FILE}" ]]; then
  echo "Missing SCORM config: ${SCORM_CONFIG_FILE}" >&2
  echo "Copy PEDS_ASSESSMENT/scorm_config.example.json and set backend_base first." >&2
  exit 1
fi

case "${BUILD_DIR}" in
  /*) BUILD_PATH="${BUILD_DIR}" ;;
  *) BUILD_PATH="${ROOT_DIR}/${BUILD_DIR}" ;;
esac

case "${ZIP_FILE}" in
  /*) ZIP_PATH="${ZIP_FILE}" ;;
  *) ZIP_PATH="${ROOT_DIR}/${ZIP_FILE}" ;;
esac

rm -rf "${BUILD_PATH}"
mkdir -p "${BUILD_PATH}/js"

cp -R static/. "${BUILD_PATH}/"
cp imsmanifest.xml "${BUILD_PATH}/imsmanifest.xml"

{
  printf "window.SCORM_CONFIG = "
  tr -d '\r\n' < "${SCORM_CONFIG_FILE}"
  printf ";\n"
} > "${BUILD_PATH}/js/scorm_config.js"

# Moodle serves the ZIP root as the SCO root. Convert FastAPI /static/ paths
# inside the packaged files only; source files stay SaaS-safe. CSS URLs resolve
# relative to css/style.css, so they need to walk back to the package root.
LC_ALL=C LANG=C perl -0pi -e 's#/static/##g' \
  "${BUILD_PATH}/index.html" \
  "${BUILD_PATH}/js/app.js"

LC_ALL=C LANG=C perl -0pi -e 's#/static/#../#g' \
  "${BUILD_PATH}/css/style.css"

rm -f "${ZIP_PATH}"
(
  cd "${BUILD_PATH}"
  zip -qr "${ZIP_PATH}" . -x "*.DS_Store" -x "__MACOSX/*" -x "audio/lung sounds/LS.zip"
)

unzip -l "${ZIP_PATH}" | grep -E "imsmanifest.xml|index.html|js/scorm_config.js|js/scorm.js|js/scorm_adapter.js|js/app.js|css/style.css"
