#!/usr/bin/env bash
# Playbook experiment: baseline on held-out pages, learn on training pages, then the same held-out pages
# with the learned playbook. Run on the molab sandbox from the folder holding batch.py:
#   nohup bash experiment.sh > logs/playbook-experiment.log 2>&1 &
W=https://en.wikipedia.org/wiki
TEST="$W/Immune_system $W/Solar_System $W/Industrial_Revolution $W/Earthquake"
TRAIN="$W/Mitochondrion $W/Plate_tectonics $W/Water_cycle $W/Roman_Empire $W/DNA $W/Volcano"
PY=${PY:-python}
$PY batch.py baseline test-baseline 3 $TEST && \
$PY batch.py learn train 3 $TRAIN && \
$PY batch.py frozen test-playbook 3 $TEST
echo EXPERIMENT_DONE
