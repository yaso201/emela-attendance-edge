(() => {
    const methods = {
        authenticate: "attendance_edge.offline_auth.authenticate",
        context: "attendance_edge.student_app.get_student_context",
        submitQr: "attendance_edge.student_signature.submit_qr_signature",
        provisional: "attendance_edge.student_signature.provisional_checkin",
    };

    const state = {
        studentId: sessionStorage.getItem("present_lanem_student_id") || "",
        stream: null,
        scanning: false,
        lastSessionModule: "",
        torchOn: false,
    };

    const els = {
        hero: document.getElementById("student-hero"),
        authPanel: document.getElementById("student-auth-panel"),
        appPanel: document.getElementById("student-app-panel"),
        studentId: document.getElementById("student-id"),
        password: document.getElementById("student-password"),
        login: document.getElementById("student-login"),
        logout: document.getElementById("student-logout"),
        message: document.getElementById("student-message"),
        nameLabel: document.getElementById("student-name-label"),
        startScan: document.getElementById("start-scan"),
        video: document.getElementById("qr-video"),
        scannerTarget: document.getElementById("scanner-target"),
        qrPayload: document.getElementById("qr-payload"),
        submitPayload: document.getElementById("submit-payload"),
        refresh: document.getElementById("student-refresh"),
        sessions: document.getElementById("student-sessions"),
        successOverlay: document.getElementById("signature-success-overlay"),
        successCourse: document.getElementById("success-course-name"),
        successTime: document.getElementById("success-time"),
        offlineBanner: document.getElementById("offline-banner"),
        toggleTorch: document.getElementById("toggle-torch"),
        manualEntry: document.getElementById("manual-entry"),
    };

    const statusLabels = {
        Pending: "A venir",
        Open: "En cours",
        Closed: "Cloturee",
        Validated: "Presence validee",
        "Pending Validation": "En attente de validation",
        Rejected: "Rejetee",
        AttendanceCancelled: "Annulee",
        Leave: "Conge",
        "Not Signed": "Pas encore signe",
        already_signed: "Presence deja signee",
        outside_signature_network: "Hors reseau local",
        student_on_leave: "Conge detecte",
        session_not_open: "Seance non ouverte",
        "Session Already Closed": "Seance cloturee",
        invalid_qr: "QR invalide",
        expired_or_invalid_totp: "QR expire",
    };

    const errorMessages = {
        expired_or_invalid_totp: {
            cause: "Le QR change toutes les 30 secondes.",
            action: "Rescanne le QR affiche a l'ecran maintenant.",
            retry: true,
        },
        outside_signature_network: {
            cause: "Tu n'es pas connecte au wifi de l'etablissement.",
            action: "Connecte-toi au reseau wifi du campus et reessaie.",
            retry: true,
        },
        student_on_leave: {
            cause: "Un conge est enregistre pour cette seance.",
            action: "Si c'est une erreur, contacte ton enseignant.",
            retry: false,
        },
        session_not_open: {
            cause: "La seance n'est pas encore ouverte par l'enseignant.",
            action: "Attends que l'enseignant ouvre la seance et reessaie.",
            retry: true,
        },
        already_signed: {
            cause: "Ta presence est deja enregistree pour cette seance.",
            action: "",
            retry: false,
        },
        invalid_qr: {
            cause: "Le code scanne n'est pas un QR de presence valide.",
            action: "Verifie que tu scannes bien le QR affiche par l'enseignant.",
            retry: true,
        },
        "Session Already Closed": {
            cause: "La seance est terminee.",
            action: "Contacte ton enseignant si tu etais present.",
            retry: false,
        },
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

    function showMessage(text, type = "info", statusCode) {
        if (!text) {
            els.message.hidden = true;
            els.message.textContent = "";
            return;
        }
        els.message.hidden = false;
        els.message.dataset.state = type;

        // Rich error messages with cause + action + retry button
        const rich = statusCode && errorMessages[statusCode];
        if (rich && type === "error") {
            // Clear and build via safe DOM methods (all user text goes through escapeHtml/textContent)
            els.message.textContent = "";
            const title = document.createElement("strong");
            title.textContent = labelForStatus(statusCode);
            els.message.appendChild(title);
            if (rich.cause) {
                const cause = document.createElement("span");
                cause.className = "ae-alert__cause";
                cause.textContent = rich.cause;
                els.message.appendChild(cause);
            }
            if (rich.action) {
                const action = document.createElement("span");
                action.className = "ae-alert__action";
                action.textContent = rich.action;
                els.message.appendChild(action);
            }
            if (rich.retry) {
                const retryBtn = document.createElement("button");
                retryBtn.className = "ae-button ae-alert__retry";
                retryBtn.type = "button";
                retryBtn.textContent = "Reessayer";
                retryBtn.addEventListener("click", () => {
                    showMessage("", "info");
                    startScanner();
                });
                els.message.appendChild(retryBtn);
            }
            // F14-b — Show manual entry on any scan error
            els.manualEntry.hidden = false;
        } else {
            els.message.textContent = text;
        }
    }

    function setHeroCompact(compact) {
        if (els.hero) {
            els.hero.classList.toggle("ae-student-hero--compact", compact);
        }
    }

    function showSuccessOverlay(courseName) {
        const now = new Date();
        const time = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
        els.successCourse.textContent = courseName || "Seance";
        els.successTime.textContent = "Validee \u00b7 " + time;
        els.successOverlay.hidden = false;
        if (navigator.vibrate) {
            navigator.vibrate(200);
        }
        setTimeout(() => {
            els.successOverlay.hidden = true;
        }, 3000);
    }

    async function login() {
        const userId = (els.studentId.value || "").trim();
        const password = els.password.value || "";
        if (!userId || !password) {
            showMessage("Identifiant et mot de passe requis.", "error");
            return;
        }
        els.login.disabled = true;
        els.login.textContent = "Connexion...";
        try {
            showMessage("Connexion...", "info");
            const result = await call(methods.authenticate, {
                user_id: userId,
                password,
                actor_type: "student",
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error", result.status);
                return;
            }
            state.studentId = result.name;
            sessionStorage.setItem("present_lanem_student_id", state.studentId);
            els.password.value = "";
            await loadStudentContext();
        } catch (error) {
            showMessage(error.message, "error");
        } finally {
            els.login.disabled = false;
            els.login.textContent = "Entrer";
        }
    }

    async function loadStudentContext() {
        if (!state.studentId) {
            showAuth();
            return;
        }
        try {
            const result = await call(methods.context, {student_id: state.studentId});
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error", result.status);
                showAuth();
                return;
            }
            els.authPanel.hidden = true;
            els.appPanel.hidden = false;
            setHeroCompact(true);
            els.nameLabel.textContent = result.student.full_name || result.student.student_id;
            renderSessions(result.sessions || []);
            showMessage("", "info");
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function showAuth() {
        els.authPanel.hidden = false;
        els.appPanel.hidden = true;
        setHeroCompact(false);
    }

    function logout() {
        stopScanner();
        state.studentId = "";
        sessionStorage.removeItem("present_lanem_student_id");
        showAuth();
        showMessage("", "info");
    }

    async function startScanner() {
        if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            showMessage("Camera indisponible sur ce navigateur. Utilise la saisie manuelle ci-dessous.", "error");
            els.manualEntry.hidden = false;
            return;
        }
        try {
            state.stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}, audio: false});
            els.video.srcObject = state.stream;
            els.video.hidden = false;
            els.scannerTarget.hidden = true;
            state.scanning = true;
            showMessage("", "info");

            // B03 — Toggle torch if supported
            const track = state.stream.getVideoTracks()[0];
            if (track && track.getCapabilities && track.getCapabilities().torch) {
                els.toggleTorch.hidden = false;
            } else {
                els.toggleTorch.hidden = true;
            }

            requestAnimationFrame(scanLoop);
        } catch (error) {
            showMessage("L'acces a la camera a ete refuse. Va dans Reglages > Site > Camera > Autoriser, ou saisis le code manuellement ci-dessous.", "error");
            els.manualEntry.hidden = false;
        }
    }

    async function toggleTorch() {
        if (!state.stream) return;
        const track = state.stream.getVideoTracks()[0];
        if (!track) return;
        state.torchOn = !state.torchOn;
        try {
            await track.applyConstraints({advanced: [{torch: state.torchOn}]});
        } catch (e) {
            // Torch not supported, ignore
        }
    }

    async function scanLoop() {
        if (!state.scanning) {
            return;
        }
        try {
            const detector = new BarcodeDetector({formats: ["qr_code"]});
            const codes = await detector.detect(els.video);
            if (codes && codes.length) {
                // B03 — Visual feedback: flash green border on video
                els.video.classList.add("ae-scanner-detected");
                await submitQrPayload(codes[0].rawValue);
                stopScanner();
                return;
            }
        } catch (error) {
            showMessage("Scan interrompu.", "error");
            stopScanner();
            return;
        }
        requestAnimationFrame(scanLoop);
    }

    function stopScanner() {
        state.scanning = false;
        state.torchOn = false;
        els.toggleTorch.hidden = true;
        if (state.stream) {
            state.stream.getTracks().forEach((track) => track.stop());
            state.stream = null;
        }
        els.video.hidden = true;
        els.video.srcObject = null;
        els.video.classList.remove("ae-scanner-detected");
        els.scannerTarget.hidden = false;
    }

    async function submitQrPayload(rawPayload) {
        if (!state.studentId) {
            showAuth();
            return;
        }
        const payload = String(rawPayload || "").trim();
        if (!payload) {
            showMessage("QR vide.", "error");
            return;
        }
        try {
            showMessage("Validation...", "info");
            const result = await call(methods.submitQr, {
                student_id: state.studentId,
                qr_payload: payload,
                fingerprint: fingerprint(),
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error", result.status);
                await loadStudentContext();
                return;
            }
            showMessage("", "info");
            showSuccessOverlay(state.lastSessionModule);
            await loadStudentContext();
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    async function provisionalCheckin(attendanceSessionId, moduleName) {
        try {
            showMessage("Check-in...", "info");
            const result = await call(methods.provisional, {
                attendance_session_id: attendanceSessionId,
                student_id: state.studentId,
                fingerprint: fingerprint(),
            });
            if (!result.ok) {
                showMessage(labelForStatus(result.status), "error", result.status);
                return;
            }
            showMessage("", "info");
            showSuccessOverlay(moduleName);
            await loadStudentContext();
        } catch (error) {
            showMessage(error.message, "error");
        }
    }

    function renderSessions(sessions) {
        els.sessions.textContent = "";
        if (!sessions.length) {
            const empty = document.createElement("div");
            empty.className = "ae-muted";
            empty.textContent = "Aucune seance locale active.";
            els.sessions.appendChild(empty);
            return;
        }

        // Sort: Open first, then Pending, then rest
        const order = {Open: 0, Pending: 1};
        const sorted = sessions.slice().sort((a, b) => {
            return (order[a.session_status] ?? 2) - (order[b.session_status] ?? 2);
        });

        // Track active session module for success overlay
        const active = sorted.find((s) => s.session_status === "Open");
        if (active) {
            state.lastSessionModule = active.module_code || "Seance";
        }

        sorted.forEach((session) => {
            const row = document.createElement("div");
            row.className = "ae-student-session";
            if (session.session_status === "Open") {
                row.classList.add("ae-student-session--active");
            }

            const info = document.createElement("span");
            const name = document.createElement("strong");
            name.textContent = session.module_code || "Seance";
            const detail = document.createElement("small");
            detail.textContent = formatTime(session.planned_start) + "-" + formatTime(session.planned_end) + " \u00b7 " + (session.room || "Salle non definie");
            info.appendChild(name);
            info.appendChild(detail);

            const status = document.createElement("span");
            status.className = "ae-status";
            status.dataset.state = session.student_status || "";
            status.textContent = labelForStatus(session.student_status);

            const btn = document.createElement("button");
            btn.className = "ae-button";
            btn.type = "button";
            btn.textContent = "Check-in";
            btn.disabled = !session.can_provisional_checkin;
            btn.addEventListener("click", () => provisionalCheckin(session.attendance_session_id, session.module_code));

            row.appendChild(info);
            row.appendChild(status);
            row.appendChild(btn);
            els.sessions.appendChild(row);
        });
    }

    function fingerprint() {
        return {
            fingerprint: `${navigator.userAgent}|${screen.width}x${screen.height}|${Intl.DateTimeFormat().resolvedOptions().timeZone || ""}`,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
        };
    }

    function labelForStatus(status) {
        return statusLabels[status] || status || "Etat inconnu";
    }

    function formatTime(value) {
        const match = String(value || "").match(/(\d{2}):(\d{2})/);
        return match ? `${match[1]}:${match[2]}` : "--:--";
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function registerServiceWorker() {
        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.register("/present-lanem-sw.js", {scope: "/"}).catch(() => {});
        }
    }

    function boot() {
        els.studentId.value = state.studentId;
        els.login.addEventListener("click", login);
        els.logout.addEventListener("click", logout);
        els.startScan.addEventListener("click", startScanner);
        els.submitPayload.addEventListener("click", () => submitQrPayload(els.qrPayload.value));
        els.refresh.addEventListener("click", loadStudentContext);
        els.password.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                login();
            }
        });

        // B03 — Torch toggle
        els.toggleTorch.addEventListener("click", toggleTorch);

        // F13 — Offline banner
        window.addEventListener("online", () => { els.offlineBanner.hidden = true; });
        window.addEventListener("offline", () => { els.offlineBanner.hidden = false; });
        if (!navigator.onLine) {
            els.offlineBanner.hidden = false;
        }

        if (state.studentId) {
            loadStudentContext();
        } else {
            showAuth();
        }
        registerServiceWorker();
    }

    boot();
})();
