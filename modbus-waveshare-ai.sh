#!/usr/bin/env bash
# @brief		Run the Waveshare Modbus AI 8CH management tool
# @author		Helge Klug
# @copyright	Copyright (c) 2026 Helge Klug
# @file			modbus-waveshare-ai.sh
# @details		Starts the Python tool and passes all command-line arguments through unchanged.

set -euo pipefail

scriptDir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$scriptDir/modbus-waveshare-ai.py" "$@"
