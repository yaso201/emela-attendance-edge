(() => {
    const methods = {
        console: "attendance_edge.teacher_console.get_teacher_console",
        detail: "attendance_edge.teacher_console.get_attendance_session",
        open: "attendance_edge.teacher_console.open_attendance_session",
        manualMark: "attendance_edge.teacher_console.manual_mark_student",
    };

    const state = {
        teacherId: "",
        pin: "",
        sessions: [],
        selectedSessionId: "",
        refreshTimer: null,
        rosterPollTimer: null,
        currentRoster: [],
        rosterFilter: "all",
        rosterSearch: "",
        previousMetrics: null,
        undoTimer: null,
        undoPendingStudentId: null,
    };

    const els = {
        teacherId: document.getElementById("teacher-id"),
        pinDigits: Array.from(document.querySelectorAll(".ae-pin-digit")),
        pinToggle: document.getElementById("pin-toggle"),
        load: document.getElementById("teacher-load"),
        refresh: document.getElementById("teacher-refresh"),
        message: document.getElementById("teacher-message"),
        syncPill: document.getElementById("teacher-sync-pill"),
        sessions: document.getElementById("teacher-sessions"),
        empty: document.getElementById("teacher-empty"),
        detail: document.getElementById("teacher-session-detail"),
        statusLabel: document.getElementById("session-status-label"),
        title: document.getElementById("session-title"),
        meta: document.getElementById("session-meta"),
        open: document.getElementById("open-session"),
        metricValidated: document.getElementById("metric-validated"),
        metricPending: document.getElementById("metric-pending"),
        metricRemaining: document.getElementById("metric-remaining"),
        metricLeave: document.getElementById("metric-leave"),
        qrFrame: document.getElementById("qr-frame"),
        qrFallback: document.getElementById("qr-fallback"),
        qrRefreshLabel: document.getElementById("qr-refresh-label"),
        qrFullscreenBtn: document.getElementById("qr-fullscreen"),
        qrFullscreenOverlay: document.getElementById("qr-fullscreen-overlay"),
        qrFullscreenSvg: document.getElementById("qr-fullscreen-svg"),
        qrFsValidated: document.getElementById("qr-fs-validated"),
        qrFsRemaining: document.getElementById("qr-fs-remaining"),
        qrFullscreenClose: document.getElementById("qr-fullscreen-close"),
        rosterSearch: document.getElementById("roster-search"),
        rosterFilters: document.getElementById("roster-filters"),
        filterCountRemaining: document.getElementById("filter-count-remaining"),
        filterCountPending: document.getElementById("filter-count-pending"),
        filterCountValidated: document.getElementById("filter-count-validated"),
        rosterCount: document.getElementById("roster-count"),
        roster: document.getElementById("roster-list"),
        sidebarToggle: document.getElementById("sidebar-toggle"),
        sidebar: document.getElementById("session-sidebar"),
        drawerBackdrop: document.getElementById("drawer-backdrop"),
        pendingCta: document.getElementById("pending-cta"),
        pendingCtaMeta: document.getElementById("pending-cta-meta"),
        pendingCtaOpen: document.getElementById("pending-cta-open"),
        sessionHeaderNormal: document.getElementById("session-header-normal"),
        sessionContent: document.getElementById("session-content"),
    };

    const statusLabels = {
        Pending: "A ouvrir",
        Open: "En cours",
        Closed: "Cloturee",
        SessionCancelled: "Annulee",
        Incident: "Incident",
        Validated: "Valide",
        "Pending Validation": "En attente de validation",
        Rejected: "Rejete",
        Leave: "Conge",
        "Not Signed": "Absent",
    };

    function csrfToken() {
        return (window.attendanceEdge && window.attendanceEdge.csrfToken) || window.csrf_token || "";
    }

    async function call(method, args) {
        const response = await fetch(`/api/method/${method}`, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-Frappe-CSRF-Token": csrfToken(),
            },
            body: JSON.stringify(args || {}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.exc) {
            throw new Error(data._server_messages || data.exception || "Erreur locale");
        }
        return data.message || data;
    }

    function showMessage(text, type = "info") {
        if (!text) {
            els.message.hidden = true;
            els.message.textContent = "";
            return;
        }
        els.message.hidden = false;
        els.message.dataset.state = type;
        els.message.textContent = text;
    }

    function credentials() {
        state.teacherId = (els.teacherId.value || "").trim();
        state.pin = els.pinDigits.map((d) => d.value).join("").trim();
        if (state.teacherId) {
            localStorage.setItem("attendance_edge_teacher_id", state.teacherId);
        }
        return {teacher_id: state.teacherId, pin: state.pin};
    }

    async function loadConsole({silent = false} = {}) {
        const auth = credentials();
        if (!auth.teacher_id || !auth.pin) {
            showMessage("Identifiant et PIN requis.", "error");
            return;
        }
        try {
            if (!silent) {
                showMessage("Chargement...", "info");
            }
            const result = await call(methods.console, auth);
            if (!result.ok) {
                showMessage(labelForStatus(result.auth_status || result.status), "error");
                return;
            }
            state.sessions = result.sessions || [];
            renderSync(result.sync);
            renderSessions();
            showMessage("", "info");
            if (state.selectedSessionId) {
                await loadSession(state.selectedSessionId, {silent: true});
            } else {
                // F07 — Auto-select current session
                const autoSession = findCurrentSession();
                if (autoSession) {
                    await loadSession(autoSession.attendance_session_id);
                }
            }
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function renderSync(sync) {
        const ok = sync && sync.ok;
        els.syncPill.dataset.state = ok ? "ok" : "warn";
        if (!sync) {
            els.syncPill.textContent = "Connexion serveur";
            return;
        }
        const pending = Number(sync.pending_count || 0);
        if (ok && pending === 0) {
            els.syncPill.textContent = "Connecte";
        } else if (ok) {
            els.syncPill.textContent = "Connecte \u00b7 " + pending + " en file";
        } else {
            els.syncPill.textContent = pending + " en attente d'envoi";
            els.syncPill.title = pending + " signatures en file. Reessai automatique. Aucune action requise.";
        }
    }

    function renderSessions() {
        els.sessions.textContent = "";
        if (!state.sessions.length) {
            const empty = document.createElement("div");
            empty.className = "ae-muted";
            empty.textContent = "Aucune seance locale aujourd'hui.";
            els.sessions.appendChild(empty);
            return;
        }
        const current = findCurrentSession();
        state.sessions.forEach((session) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ae-session-card";
            button.dataset.sessionId = session.attendance_session_id;
            button.setAttribute("aria-current", String(session.attendance_session_id === state.selectedSessionId));

            const info = document.createElement("span");
            const name = document.createElement("strong");
            name.textContent = session.module_code || "Seance";
            const detail = document.createElement("small");
            detail.textContent = timeRange(session) + " \u00b7 " + (session.room || "Salle non definie");
            info.appendChild(name);
            info.appendChild(detail);

            // F07-b — badge MAINTENANT
            if (current && current.attendance_session_id === session.attendance_session_id) {
                const badge = document.createElement("span");
                badge.className = "ae-badge-now";
                badge.textContent = "MAINTENANT";
                info.appendChild(badge);
            }

            const status = document.createElement("span");
            status.className = "ae-status";
            status.dataset.state = session.status || "";
            status.textContent = labelForStatus(session.status);

            button.appendChild(info);
            button.appendChild(status);
            button.addEventListener("click", () => loadSession(session.attendance_session_id));
            els.sessions.appendChild(button);
        });
    }

    async function loadSession(attendanceSessionId, {silent = false} = {}) {
        state.selectedSessionId = attendanceSessionId;
        closeDrawer();
        renderSessions();
        try {
            if (!silent) {
                showMessage("Ouverture de la seance...", "info");
            }
            const result = await call(methods.detail, {
                attendance_session_id: attendanceSessionId,
                ...credentials(),
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.auth_status || result.status), "error");
                return;
            }
            renderSessionDetail(result.session);
            showMessage("", "info");
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function renderSessionDetail(session) {
        els.empty.hidden = true;
        els.detail.hidden = false;

        // F10 — Pending CTA mode vs normal mode
        const isPending = session.status === "Pending";
        els.pendingCta.hidden = !isPending;
        els.sessionHeaderNormal.hidden = isPending;
        els.sessionContent.hidden = isPending;

        if (isPending) {
            const rosterCount = (session.roster || []).length;
            els.pendingCtaMeta.textContent = timeRange(session) + " \u00b7 " + rosterCount + " etudiants attendus";
            els.pendingCtaOpen.dataset.sessionId = session.attendance_session_id;
        }

        els.statusLabel.textContent = labelForStatus(session.status);
        els.title.textContent = session.module_code || "Seance";
        els.meta.textContent = timeRange(session) + " \u00b7 " + (session.student_group || "Groupe non defini") + " \u00b7 " + (session.room || "Salle non definie");
        els.open.hidden = session.status !== "Pending";
        els.open.dataset.sessionId = session.attendance_session_id;

        // F02 — show/hide fullscreen button
        els.qrFullscreenBtn.hidden = session.status !== "Open";

        const summary = session.summary || {};
        const newValidated = summary.validated || 0;

        // F05-b — animate metric bump
        if (state.previousMetrics && newValidated > (state.previousMetrics.validated || 0)) {
            els.metricValidated.classList.add("ae-metric--bump");
            setTimeout(() => els.metricValidated.classList.remove("ae-metric--bump"), 500);
        }
        state.previousMetrics = {validated: newValidated};

        els.metricValidated.textContent = String(newValidated);
        els.metricPending.textContent = String(summary.pending || 0);
        els.metricPending.style.color = "var(--color-warning-700)";
        els.metricRemaining.textContent = String(summary.remaining || 0);
        els.metricRemaining.style.color = "var(--color-error-700)";
        els.metricLeave.textContent = String(summary.leave || 0);
        els.metricLeave.style.color = "var(--color-info-700)";

        // F02 — update fullscreen bar
        updateFullscreenBar(summary);

        renderQr(session.qr_frame);
        renderRoster(session.roster || []);
        scheduleQrRefresh(session);
    }

    function updateFullscreenBar(summary) {
        if (els.qrFsValidated) {
            els.qrFsValidated.textContent = (summary.validated || 0) + " valides";
        }
        if (els.qrFsRemaining) {
            els.qrFsRemaining.textContent = (summary.remaining || 0) + " restants";
        }
    }

    function renderQr(frame) {
        if (!frame) {
            els.qrFrame.textContent = "";
            const placeholder = document.createElement("div");
            placeholder.className = "ae-muted";
            placeholder.textContent = "QR disponible apres ouverture.";
            els.qrFrame.appendChild(placeholder);
            els.qrFallback.hidden = true;
            els.qrRefreshLabel.textContent = "";
            return;
        }
        // QR SVG comes from trusted server (Frappe backend TOTP generation)
        els.qrFrame.textContent = "";
        if (frame.qr_svg) {
            // SVG from trusted backend — safe to render
            const svgContainer = document.createRange().createContextualFragment(frame.qr_svg);
            els.qrFrame.appendChild(svgContainer);

            // F02 — sync to fullscreen if visible
            if (!els.qrFullscreenOverlay.hidden) {
                els.qrFullscreenSvg.textContent = "";
                const fsSvg = document.createRange().createContextualFragment(frame.qr_svg);
                els.qrFullscreenSvg.appendChild(fsSvg);
            }
        } else {
            const noQr = document.createElement("div");
            noQr.className = "ae-muted";
            noQr.textContent = "QR indisponible.";
            els.qrFrame.appendChild(noQr);
        }
        els.qrFallback.hidden = false;
        els.qrFallback.textContent = frame.payload_json || "";
        els.qrRefreshLabel.textContent = frame.refresh_seconds ? frame.refresh_seconds + "s" : "";
    }

    function renderRoster(roster) {
        // Track previous statuses for highlight animation
        const prevStatuses = {};
        state.currentRoster.forEach((s) => { prevStatuses[s.student_id] = s.status; });

        state.currentRoster = roster;
        updateFilterCounts(roster);
        els.rosterCount.textContent = roster.length + " etudiants";

        filterAndRenderRoster(prevStatuses);
    }

    function filterAndRenderRoster(prevStatuses) {
        prevStatuses = prevStatuses || {};
        const query = state.rosterSearch.toLowerCase();
        const filter = state.rosterFilter;

        const filtered = state.currentRoster.filter((student) => {
            // Text search
            if (query) {
                const name = (student.student_name || "").toLowerCase();
                const id = (student.student_id || "").toLowerCase();
                if (!name.includes(query) && !id.includes(query)) return false;
            }
            // Status filter
            if (filter === "remaining") return student.status === "Not Signed";
            if (filter === "pending") return student.status === "Pending Validation";
            if (filter === "validated") return student.status === "Validated";
            return true;
        });

        els.roster.textContent = "";
        filtered.forEach((student) => {
            const row = document.createElement("div");
            row.className = "ae-roster-row";

            // F05-b — highlight newly validated
            if (student.status === "Validated" && prevStatuses[student.student_id] && prevStatuses[student.student_id] !== "Validated") {
                row.classList.add("ae-roster-row--highlight");
                setTimeout(() => row.classList.remove("ae-roster-row--highlight"), 2000);
            }

            const canMark = student.status !== "Validated" && student.status !== "Leave";

            const info = document.createElement("span");
            const name = document.createElement("strong");
            name.textContent = student.student_name || student.student_id;
            const id = document.createElement("small");
            id.textContent = student.student_id;
            info.appendChild(name);
            info.appendChild(id);

            const status = document.createElement("span");
            status.className = "ae-status";
            status.dataset.state = student.status || "";
            status.textContent = labelForStatus(student.status);

            const btn = document.createElement("button");
            btn.className = "ae-button";
            btn.type = "button";
            btn.textContent = "Valider";
            btn.disabled = !canMark;
            btn.addEventListener("click", () => manualMark(student.student_id));

            row.appendChild(info);
            row.appendChild(status);
            row.appendChild(btn);
            els.roster.appendChild(row);
        });
    }

    function updateFilterCounts(roster) {
        let remaining = 0, pending = 0, validated = 0;
        roster.forEach((s) => {
            if (s.status === "Not Signed") remaining++;
            else if (s.status === "Pending Validation") pending++;
            else if (s.status === "Validated") validated++;
        });
        els.filterCountRemaining.textContent = String(remaining);
        els.filterCountPending.textContent = String(pending);
        els.filterCountValidated.textContent = String(validated);
    }

    async function openSelectedSession() {
        const attendanceSessionId = els.open.dataset.sessionId || els.pendingCtaOpen.dataset.sessionId || state.selectedSessionId;
        if (!attendanceSessionId) {
            return;
        }
        try {
            showMessage("Ouverture...", "info");
            const result = await call(methods.open, {
                attendance_session_id: attendanceSessionId,
                ...credentials(),
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error");
                return;
            }
            renderSessionDetail(result.session);
            await loadConsole({silent: true});
            showMessage("Seance ouverte.", "success");
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function manualMark(studentId) {
        if (!state.selectedSessionId) {
            return;
        }
        // B05 — Undo 3s: show toast, delay actual API call
        if (state.undoTimer) {
            clearTimeout(state.undoTimer);
            state.undoTimer = null;
        }
        state.undoPendingStudentId = studentId;

        // Build undo message with cancel button
        els.message.hidden = false;
        els.message.dataset.state = "success";
        els.message.textContent = "";
        const msg = document.createElement("span");
        msg.textContent = "Valide \u2014 ";
        const undoBtn = document.createElement("button");
        undoBtn.className = "ae-button ae-alert__retry";
        undoBtn.type = "button";
        undoBtn.textContent = "Annuler (3s)";
        undoBtn.addEventListener("click", () => {
            clearTimeout(state.undoTimer);
            state.undoTimer = null;
            state.undoPendingStudentId = null;
            showMessage("Validation annulee.", "info");
        });
        els.message.appendChild(msg);
        els.message.appendChild(undoBtn);

        state.undoTimer = setTimeout(() => {
            state.undoTimer = null;
            state.undoPendingStudentId = null;
            executeManualMark(studentId);
        }, 3000);
    }

    async function executeManualMark(studentId) {
        try {
            const result = await call(methods.manualMark, {
                attendance_session_id: state.selectedSessionId,
                student_id: studentId,
                attendance_state: "Validated",
                ...credentials(),
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error");
                return;
            }
            renderSessionDetail(result.session);
            showMessage("Presence validee.", "success");
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function scheduleQrRefresh(session) {
        if (state.refreshTimer) {
            window.clearTimeout(state.refreshTimer);
            state.refreshTimer = null;
        }
        if (state.rosterPollTimer) {
            window.clearTimeout(state.rosterPollTimer);
            state.rosterPollTimer = null;
        }
        if (!session || session.status !== "Open") {
            return;
        }
        // QR TOTP refresh at server-defined interval
        const seconds = Number((session.qr_frame && session.qr_frame.refresh_seconds) || 30);
        state.refreshTimer = window.setTimeout(() => {
            loadSession(session.attendance_session_id, {silent: true});
        }, Math.max(10, seconds) * 1000);

        // F05-a — roster poll every 5s for real-time feedback
        state.rosterPollTimer = window.setTimeout(() => {
            loadSession(session.attendance_session_id, {silent: true});
        }, 5000);
    }

    // F02 — QR fullscreen
    function showQrFullscreen() {
        const svgSource = els.qrFrame.querySelector("svg");
        els.qrFullscreenSvg.textContent = "";
        if (svgSource) {
            els.qrFullscreenSvg.appendChild(svgSource.cloneNode(true));
        }
        els.qrFullscreenOverlay.hidden = false;
    }

    function hideQrFullscreen() {
        els.qrFullscreenOverlay.hidden = true;
    }

    // F07 — find session whose time window includes now
    function findCurrentSession() {
        const now = new Date();
        for (const session of state.sessions) {
            const start = parseSessionTime(session.planned_start, -15);
            const end = parseSessionTime(session.planned_end, 15);
            if (start && end && now >= start && now <= end) {
                return session;
            }
        }
        return null;
    }

    function parseSessionTime(value, offsetMinutes) {
        if (!value) return null;
        const match = String(value).match(/(\d{2}):(\d{2})/);
        if (!match) return null;
        const d = new Date();
        d.setHours(parseInt(match[1], 10), parseInt(match[2], 10), 0, 0);
        if (offsetMinutes) d.setMinutes(d.getMinutes() + offsetMinutes);
        return d;
    }

    function timeRange(session) {
        return `${formatTime(session.planned_start)}-${formatTime(session.planned_end)}`;
    }

    function formatTime(value) {
        if (!value) {
            return "--:--";
        }
        const match = String(value).match(/(\d{2}):(\d{2})/);
        return match ? `${match[1]}:${match[2]}` : String(value);
    }

    function labelForStatus(status) {
        return statusLabels[status] || status || "Etat inconnu";
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // F08 — Drawer open/close
    function openDrawer() {
        els.sidebar.classList.add("ae-drawer--open");
        els.drawerBackdrop.hidden = false;
    }

    function closeDrawer() {
        els.sidebar.classList.remove("ae-drawer--open");
        els.drawerBackdrop.hidden = true;
    }

    function boot() {
        els.teacherId.value = localStorage.getItem("attendance_edge_teacher_id") || "";
        els.load.addEventListener("click", () => loadConsole());
        els.refresh.addEventListener("click", () => loadConsole());
        els.open.addEventListener("click", openSelectedSession);

        // F09 — PIN 6 cases: auto-focus next, backspace prev, Enter on last
        els.pinDigits.forEach((digit, i) => {
            digit.addEventListener("input", () => {
                if (digit.value.length === 1 && i < els.pinDigits.length - 1) {
                    els.pinDigits[i + 1].focus();
                }
            });
            digit.addEventListener("keydown", (event) => {
                if (event.key === "Backspace" && !digit.value && i > 0) {
                    els.pinDigits[i - 1].focus();
                }
                if (event.key === "Enter") {
                    loadConsole();
                }
            });
        });

        // F09 — PIN show/hide toggle
        els.pinToggle.addEventListener("click", () => {
            const isHidden = els.pinDigits[0].type === "password";
            els.pinDigits.forEach((d) => { d.type = isHidden ? "text" : "password"; });
        });

        // F02 — QR fullscreen
        els.qrFullscreenBtn.addEventListener("click", showQrFullscreen);
        els.qrFullscreenClose.addEventListener("click", hideQrFullscreen);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !els.qrFullscreenOverlay.hidden) {
                hideQrFullscreen();
            }
        });

        // F03 — Roster search
        els.rosterSearch.addEventListener("input", () => {
            state.rosterSearch = els.rosterSearch.value;
            filterAndRenderRoster();
        });

        // F03 — Roster status filters
        els.rosterFilters.addEventListener("click", (event) => {
            const chip = event.target.closest(".ae-filter-chip");
            if (!chip) return;
            state.rosterFilter = chip.dataset.filter || "all";
            els.rosterFilters.querySelectorAll(".ae-filter-chip").forEach((c) => {
                c.classList.toggle("ae-filter-chip--active", c === chip);
            });
            filterAndRenderRoster();
        });

        // F08 — Drawer toggle
        els.sidebarToggle.addEventListener("click", openDrawer);
        els.drawerBackdrop.addEventListener("click", closeDrawer);

        // F10 — Pending CTA open button
        els.pendingCtaOpen.addEventListener("click", openSelectedSession);
    }

    boot();
})();
