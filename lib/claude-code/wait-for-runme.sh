#!/bin/bash
# Blocks until a RUNME-<name>/RUNNING-<name> marker in ~/claude resolves into
# DONE-<name> or CANCELLED-<name>, then prints the outcome and exits.
#
# Meant to be launched with run_in_background right after creating a RUNME-*
# marker, so the background-task notification reports completion instead of
# requiring a manual check back.
#
# Usage: wait-for-runme.sh <name.sh>   (with or without a RUNME-/RUNNING- prefix)

set -u
DIR="$HOME/claude"
name="$1"
name="${name#RUNME-}"
name="${name#RUNNING-}"
name="${name#DONE-}"
name="${name#CANCELLED-}"

while true; do
    if [[ -e "$DIR/DONE-$name" ]]; then
        echo "DONE: $name"
        exit 0
    fi
    if [[ -e "$DIR/CANCELLED-$name" ]]; then
        echo "CANCELLED: $name"
        exit 1
    fi
    sleep 2
done
