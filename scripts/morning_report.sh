#!/bin/bash
# Morning report for Observatory Cron
# Run via: ssh root@VPS /opt/observatory/scripts/morning_report.sh

set -uo pipefail

LOCK_FILE="/var/run/observatory_cron.lock"
CRON_LOG="/var/log/observatory/cron.log"
VALIDATOR_LOG="/var/log/observatory/post_run_validation.log"
ENV_FILE="/opt/observatory/.env"

# Load .env for Supabase credentials (best effort)
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE" 2>/dev/null || true; set +a
fi

# Track if any alert was triggered
ALERT=0

# --- Welcome banner (server motd intentionally not duplicated) ---
echo "═══════════════════════════════════════════════"
echo "  REPORTE DEL CRON OBSERVATORY"
echo "═══════════════════════════════════════════════"
echo ""
echo "📅 Fecha/hora del servidor: $(date)"
echo "📅 Fecha/hora Colombia:     $(TZ=America/Bogota date)"
echo ""

# --- 1. Estado del cron service (NUEVO) ---
echo "━━━ 1. Estado del servicio cron ━━━"
CRON_STATE=$(systemctl is-active cron 2>/dev/null || echo "unknown")
CRON_SINCE=$(systemctl show cron --property=ActiveEnterTimestamp --value 2>/dev/null)
if [ "$CRON_STATE" = "active" ]; then
    echo "  ✓ cron.service está ACTIVO (desde: $CRON_SINCE)"
else
    echo "  🔴 CRITICAL: cron.service NO está activo (estado: $CRON_STATE)"
    echo "     → Ejecuta: systemctl start cron"
    ALERT=1
fi
echo ""

# --- 2. ¿El cron corrió anoche? ---
echo "━━━ 2. ¿El cron corrió en el último ciclo? ━━━"
if [ -f "$LOCK_FILE" ]; then
    LOCK_TS=$(cat "$LOCK_FILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    AGE_SEC=$((NOW - LOCK_TS))
    AGE_HOURS=$((AGE_SEC / 3600))
    AGE_DAYS=$((AGE_SEC / 86400))
    LOCK_DATE=$(date -d "@$LOCK_TS" "+%Y-%m-%d %H:%M:%S %Z")
    LOCK_DATE_COL=$(TZ=America/Bogota date -d "@$LOCK_TS" "+%Y-%m-%d %H:%M:%S %Z")
    echo "  Última ejecución: $LOCK_DATE"
    echo "  Última ejecución: $LOCK_DATE_COL (hora Colombia)"
    echo "  Hace: ${AGE_HOURS}h (${AGE_DAYS} días)"
    if [ "$AGE_DAYS" -gt 4 ]; then
        echo "  🔴 STALE: lock tiene más de 4 días — el cron debería haber re-ejecutado"
        ALERT=1
    elif [ "$AGE_DAYS" -ge 4 ]; then
        echo "  ⏳ Próxima ejecución debería ocurrir hoy (lock = 4d, intervalo mínimo cumplido)"
    else
        echo "  ✓ Dentro del intervalo normal de 4 días"
    fi
else
    echo "  🔴 CRITICAL: NO hay lock file en $LOCK_FILE"
    echo "     → El cron NUNCA ha ejecutado o el lock fue borrado"
    echo "     → Verifica: crontab -l y systemctl status cron"
    ALERT=1
fi
echo ""

# --- 3. Último resultado del cron (de cron.log) ---
echo "━━━ 3. Último resultado del cron ━━━"
if [ -s "$CRON_LOG" ]; then
    LAST_OVERALL=$(grep "^.*OVERALL:" "$CRON_LOG" 2>/dev/null | tail -1)
    if [ -n "$LAST_OVERALL" ]; then
        echo "  $LAST_OVERALL"
    else
        echo "  ⚠ No se encontró línea OVERALL en el log"
    fi
    LAST_INVOKE=$(grep "Cron guard invoked" "$CRON_LOG" 2>/dev/null | tail -1)
    echo "  Última invocación: ${LAST_INVOKE:-(ninguna)}"
else
    echo "  ⚠ $CRON_LOG vacío o no existe (¿rotado?)"
fi
echo ""

# --- 4. Resumen del último pipeline ---
echo "━━━ 4. Resumen del último pipeline ━━━"
if [ -s "$CRON_LOG" ]; then
    PIPE_COMPLETED=$(grep "Pipeline completed" "$CRON_LOG" 2>/dev/null | tail -1)
    if [ -n "$PIPE_COMPLETED" ]; then
        echo "  $PIPE_COMPLETED"
    else
        echo "  (sin línea Pipeline completed en log)"
    fi
else
    echo "  (sin datos de pipeline en log)"
fi
echo ""

# --- 5. ¿Hubo errores? ---
echo "━━━ 5. ¿Hubo errores recientes? ━━━"
if [ -s "$CRON_LOG" ]; then
    # Exclude false positives: "0 errors", "errors: 0", "no errors", "Skills extraction complete", etc.
    ERR_COUNT=$(grep -iE "error|fatal|fail|exception" "$CRON_LOG" 2>/dev/null \
        | grep -ivE "0 errors|errors:\s*0|no errors|0 failed|failed/skipped|Skills extraction complete|UNIQUE constraint|BATCH RETURN" \
        | wc -l)
    if [ "$ERR_COUNT" -gt 0 ]; then
        echo "  ⚠ $ERR_COUNT líneas con error/fail/exception (excluyendo falsos positivos)"
        echo "  Últimas 3:"
        grep -iE "error|fatal|fail|exception" "$CRON_LOG" 2>/dev/null \
            | grep -ivE "0 errors|errors:\s*0|no errors|0 failed|failed/skipped|Skills extraction complete|UNIQUE constraint|BATCH RETURN" \
            | tail -3 | sed "s/^/    /"
        ALERT=1
    else
        echo "  ✓ Sin errores reportados"
    fi
else
    echo "  (sin log para revisar)"
fi
echo ""

# --- 6. Estado actual de la BD ---
echo "━━━ 6. Estado actual de la BD ━━━"
PYTHON_BIN="/opt/observatory/venv/bin/python3"
if [ -n "${SUPABASE_URL:-}" ] && [ -n "${SUPABASE_ANON_KEY:-}" ]; then
    # Counts via HEAD requests with Prefer: count=exact
    TOTAL=$(curl -s -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "Prefer: count=exact" -H "Range: 0-0" "${SUPABASE_URL}/rest/v1/vacantes?select=id" -I 2>/dev/null | grep -i "content-range:" | sed -E "s/.*\/([0-9]+).*/\1/" | tr -d "\r\n")
    SKILLS=$(curl -s -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "Prefer: count=exact" -H "Range: 0-0" "${SUPABASE_URL}/rest/v1/job_skills?select=id" -I 2>/dev/null | grep -i "content-range:" | sed -E "s/.*\/([0-9]+).*/\1/" | tr -d "\r\n")
    # Sin clasificar: usar columna 'classification' (pipeline marca 'completed' aquí); role_family es campo derivado
    UNCLASSIFIED=$(curl -s -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "Prefer: count=exact" -H "Range: 0-0" "${SUPABASE_URL}/rest/v1/vacantes?select=id&classification=is.null" -I 2>/dev/null | grep -i "content-range:" | sed -E "s/.*\/([0-9]+).*/\1/" | tr -d "\r\n")

    # Pendientes de skills: vacancies sin entradas en job_skills (set difference, paginado para evitar bug 1000-row)
    PENDING_SKILLS="?"
    if [ -x "$PYTHON_BIN" ]; then
        PENDING_SKILLS=$("$PYTHON_BIN" -c "
import os, sys
try:
    from supabase import create_client
    c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'])
    def all_ids(table, col):
        ids = set(); start = 0
        while True:
            page = c.table(table).select(col).range(start, start+999).execute().data
            if not page: break
            ids.update(r[col] for r in page)
            if len(page) < 1000: break
            start += 1000
        return ids
    v_ids = all_ids('vacantes', 'id')
    s_ids = all_ids('job_skills', 'vacancy_id')
    print(len(v_ids - s_ids))
except Exception as e:
    print('?', file=sys.stderr); print('?')
" 2>/dev/null)
    fi

    printf "  Vacancies totales:        %s\n" "${TOTAL:-?}"
    printf "  Skills extraídos:         %s\n" "${SKILLS:-?}"
    printf "  Vacancies sin clasificar: %s   (classification IS NULL)\n" "${UNCLASSIFIED:-?}"
    printf "  Pendientes de skills:     %s   (sin entradas en job_skills)\n" "${PENDING_SKILLS:-?}"
else
    echo "  ⚠ Credenciales Supabase no encontradas en .env — sección omitida"
fi
echo ""

# --- 7. ¿Post-run validator pasó? ---
echo "━━━ 7. ¿Post-run validator pasó? ━━━"
if [ -s "$VALIDATOR_LOG" ]; then
    LAST_VAL=$(tail -10 "$VALIDATOR_LOG" 2>/dev/null | grep -iE "passed|failed|anomaly|ok" | tail -1)
    echo "  ${LAST_VAL:-(sin línea conclusiva)}"
else
    echo "  (sin log de validator o vacío)"
fi
echo ""

# --- Resumen final ---
echo "═══════════════════════════════════════════════"
if [ "$ALERT" -eq 0 ]; then
    echo "  [OK] Todos los chequeos pasaron"
else
    echo "  [🚨 ALERTA] Revisa las secciones marcadas con 🔴 arriba"
fi
echo "═══════════════════════════════════════════════"
