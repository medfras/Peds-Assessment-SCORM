#!/usr/bin/env bash
set -euo pipefail

SCORM_CONFIG_FILE="${SCORM_CONFIG_FILE:-PEDS_ASSESSMENT/scorm_config.local.json}"
BUILD_DIR="${BUILD_DIR:-scorm_smoke_build}"
ZIP_FILE="${ZIP_FILE:-pfd_station1_scorm_smoke.zip}"
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

cp scorm_smoke/index.html "${BUILD_PATH}/index.html"
cp scorm_smoke/imsmanifest.xml "${BUILD_PATH}/imsmanifest.xml"
cp static/js/scorm.js "${BUILD_PATH}/js/scorm.js"

{
  printf "window.SCORM_CONFIG = "
  tr -d '\r\n' < "${SCORM_CONFIG_FILE}"
  printf ";\n"
} > "${BUILD_PATH}/scorm_config.js"

rm -f "${ZIP_PATH}"
(
  cd "${BUILD_PATH}"
  zip -qr "${ZIP_PATH}" . -x "*.DS_Store" -x "__MACOSX/*"
)

unzip -l "${ZIP_PATH}" | grep -E "imsmanifest.xml|index.html|js/scorm.js|scorm_config.js"
