#!/bin/bash
# Builds the panel and all helpers (stripped, version info embedded).
set -e
cd "$(dirname "$0")"
go vet ./...
go build -ldflags="-s -w" -o gopanel .
for d in helpers/*/; do
	n=$(basename "$d")
	go build -ldflags="-s -w" -o "helpers/$n/$n" "./helpers/$n"
done
./gopanel version
