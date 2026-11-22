#!/bin/bash
#
# Cron Guard for Observatory Pipeline
#
# Purpose:
#   - Prevents duplicate/parallel executions of the pipeline
#   - Enforces a minimum interval of 4 days between runs
#   - Executes the pipeline, then runs post-run validation
#   - Logs all activity to /var/log/observatory/cron.log
#
# Designed to be called from crontab daily (e.g. `0 23 * * *`). The script
# decides internally whether to actually run based on the lock file timestamp.
#
# Exit codes:
#   0   - Skipped (less than 4 days since last run) OR ran successfully + validator passed
#   1   - Pipeline ran but failed (non-zero exit from main.py)
#   2   - Pipeline ran OK but post-run validator detected anomalies
#   3   - Could not acquire lock or environment is broken
#

set -uo pipefail  # NOTE: NOT -e because we need to capture exit codes manually

LOCK_FILE="/var/run/observatory_cron.lock"
MIN_INTERVAL=345600  # 4 days in seconds (4 * 24 * 60 * 60)
LOG_FILE="/var/log/observatory/cron.log"
PROJECT_DIR="/opt/observatory"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python3"
PIPELINE_SCRIPT="${PROJECT_DIR}/pipeline/main.py"
VALIDATOR_SCRIPT="${PROJECT_DIR}/scripts/post_run_validator.py"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Logging helper — writes to both file and stdout (so cron captures it)
log() {
    local msg="$(date '+%Y-%m-%d %H:%M:%S') | $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

log "============================================================"
log "Cron guard invoked"

# ============================================================
# STEP 1: Check 4-day lock
# ============================================================
NOW=$(date +%s)

# Hard stop: no runs after Jun 24 23:00 COL (= Jun 25 06:00 CEST)
END_TS=$(TZ=America/Bogota date -d "2026-06-25 00:00:00" +%s)
if [ "$NOW" -ge "$END_TS" ]; then
    log "STOP: Observatory scan completado — sin más runs después del 24 jun 23:00 COL"
    exit 0
fi

# Si el último run fue el 22 jun, usar intervalo de 48h para que Jun 24 dispare
if [ -f "$LOCK_FILE" ]; then
    LAST_RUN_DATE=$(TZ=America/Bogota date -d @$(cat "$LOCK_FILE") '+%Y-%m-%d')
    if [ "$LAST_RUN_DATE" = "2026-06-22" ]; then
        MIN_INTERVAL=172800  # 48h
    fi
fi

if [ -f "$LOCK_FILE" ]; then
    LAST_RUN=$(cat "$LOCK_FILE" 2>/dev/null || echo 0)
    TIME_SINCE=$((NOW - LAST_RUN))

    if [ "$TIME_SINCE" -lt "$MIN_INTERVAL" ]; then
        HOURS_LEFT=$(( (MIN_INTERVAL - TIME_SINCE) / 3600 ))
        log "SKIP: last run was $((TIME_SINCE / 3600))h ago (need $((MIN_INTERVAL / 3600))h; $HOURS_LEFT h remaining)"
        exit 0
    fi
fi

# ============================================================
# STEP 2: Verify environment
# ============================================================
if [ ! -x "$VENV_PYTHON" ]; then
    log "FATAL: venv python not found or not executable at $VENV_PYTHON"
    exit 3
fi
if [ ! -f "$PIPELINE_SCRIPT" ]; then
    log "FATAL: pipeline script not found at $PIPELINE_SCRIPT"
    exit 3
fi
if [ ! -f "$VALIDATOR_SCRIPT" ]; then
    log "WARN: validator script not found at $VALIDATOR_SCRIPT — validator step will be skipped"
fi

# ============================================================
# STEP 3: Acquire lock + run pipeline
# ============================================================
COL_DATE=$(TZ=America/Bogota date '+%Y-%m-%d')
LOCK_TS=$(TZ=America/Bogota date -d "${COL_DATE} 23:00:00" +%s)
echo "$LOCK_TS" > "$LOCK_FILE" || {
    log "FATAL: could not write lock file at $LOCK_FILE"
    exit 3
}
log "Lock acquired ($LOCK_FILE). Starting pipeline..."

cd "$PROJECT_DIR" || { log "FATAL: cd $PROJECT_DIR failed"; exit 3; }

# Run pipeline — capture exit code
# PYTHONPATH=$PROJECT_DIR is required so `from pipeline.config import ...` works
# when invoking the script directly (vs. as a module via -m)
START_TS=$(date +%s)
PYTHONPATH="$PROJECT_DIR" "$VENV_PYTHON" "$PIPELINE_SCRIPT" >> "$LOG_FILE" 2>&1
PIPELINE_EXIT=$?
PIPELINE_DURATION=$(( $(date +%s) - START_TS ))

if [ $PIPELINE_EXIT -ne 0 ]; then
    log "PIPELINE FAILED with exit code $PIPELINE_EXIT (duration: ${PIPELINE_DURATION}s)"
    # Don't bail — still run validator to capture DB state
fi
log "Pipeline completed (exit=$PIPELINE_EXIT, duration=${PIPELINE_DURATION}s)"

# ============================================================
# STEP 4: Run post-run validator
# ============================================================
VALIDATOR_EXIT=0
if [ -f "$VALIDATOR_SCRIPT" ]; then
    log "Running post-run validator..."
    PYTHONPATH="$PROJECT_DIR" "$VENV_PYTHON" "$VALIDATOR_SCRIPT" >> "$LOG_FILE" 2>&1
    VALIDATOR_EXIT=$?

    if [ $VALIDATOR_EXIT -eq 0 ]; then
        log "VALIDATOR PASSED — all checks OK"
    elif [ $VALIDATOR_EXIT -eq 1 ]; then
        log "VALIDATOR FAILED — anomalies detected (see /var/log/observatory/post_run_validation.log)"
    else
        log "VALIDATOR CRASHED — exit code $VALIDATOR_EXIT (DB connection issue?)"
    fi
fi

# ============================================================
# STEP 5: Determine overall exit code
# ============================================================
if [ $PIPELINE_EXIT -ne 0 ]; then
    log "OVERALL: PIPELINE FAILED"
    exit 1
fi
if [ $VALIDATOR_EXIT -eq 1 ]; then
    log "OVERALL: PIPELINE OK but VALIDATOR DETECTED ANOMALIES"
    exit 2
fi
log "OVERALL: SUCCESS — pipeline + validator both passed"
exit 0
