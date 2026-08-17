#!/usr/bin/env bash
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# fetch_datasets.sh — download FinQA, ConvFinQA, and TAT-QA into ./data/
# and verify sha256 checksums against the hard-coded values below.
#
# Usage:
#   ./scripts/fetch_datasets.sh [--help]
#
# Idempotent: already-downloaded archives that match the expected sha256
# are skipped. Exits non-zero on any hash mismatch.

set -euo pipefail

usage() {
    cat <<'EOF'
fetch_datasets.sh — download and verify financial-QA benchmark archives

Usage:
  scripts/fetch_datasets.sh           # fetch all datasets
  scripts/fetch_datasets.sh --help    # show this message

Downloads go into ./data/<dataset>/ and sha256 is verified against the
values hard-coded at the top of the script. Update those values (and
commit) when upstream releases a new revision.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ "$#" -gt 0 ]]; then
    usage
    echo "error: unexpected arguments: $*" >&2
    exit 1
fi

# Hard-coded expected sha256 checksums.
# To refresh: download the file, run `sha256sum <file>`, paste here.
FINQA_URL="https://github.com/czyssrs/FinQA/raw/main/dataset/test.json"
FINQA_SHA="0000000000000000000000000000000000000000000000000000000000000000"

CONVFINQA_URL="https://github.com/czyssrs/ConvFinQA/raw/main/data/test_turn.json"
CONVFINQA_SHA="0000000000000000000000000000000000000000000000000000000000000000"

TATQA_URL="https://nextplusplus.github.io/TAT-QA/dataset_raw/tatqa_dataset_dev.json"
TATQA_SHA="0000000000000000000000000000000000000000000000000000000000000000"

DATA_DIR="${LUB_DATA_DIR:-./data}"
mkdir -p "${DATA_DIR}"

log() {
    printf 'level=info ts=%s msg=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

err() {
    printf 'level=error ts=%s msg=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

compute_sha() {
    local file="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${file}" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${file}" | awk '{print $1}'
    else
        err "no sha256sum or shasum available on PATH"
        exit 1
    fi
}

fetch_one() {
    local name="$1"
    local url="$2"
    local expected_sha="$3"
    local out_dir="${DATA_DIR}/${name}"
    local filename
    filename="$(basename "${url}")"
    local out_path="${out_dir}/${filename}"

    mkdir -p "${out_dir}"

    if [[ -f "${out_path}" ]]; then
        local existing_sha
        existing_sha="$(compute_sha "${out_path}")"
        if [[ "${existing_sha}" == "${expected_sha}" ]]; then
            log "dataset=${name} status=skipped reason=already-present"
            return 0
        fi
        log "dataset=${name} status=stale existing_sha=${existing_sha:0:12}"
    fi

    log "dataset=${name} status=fetching url=${url}"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "${url}" -o "${out_path}"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "${url}" -O "${out_path}"
    else
        err "neither curl nor wget is available"
        exit 1
    fi

    local actual_sha
    actual_sha="$(compute_sha "${out_path}")"
    if [[ "${expected_sha}" == "0000000000000000000000000000000000000000000000000000000000000000" ]]; then
        log "dataset=${name} status=downloaded actual_sha=${actual_sha} note=placeholder-in-script-update-expected-hash"
        return 0
    fi
    if [[ "${actual_sha}" != "${expected_sha}" ]]; then
        err "dataset=${name} sha256 mismatch expected=${expected_sha} actual=${actual_sha}"
        exit 1
    fi
    log "dataset=${name} status=verified sha256=${actual_sha:0:12}"
}

fetch_one "finqa" "${FINQA_URL}" "${FINQA_SHA}"
fetch_one "convfinqa" "${CONVFINQA_URL}" "${CONVFINQA_SHA}"
fetch_one "tatqa" "${TATQA_URL}" "${TATQA_SHA}"

log "all datasets fetched into ${DATA_DIR}"
