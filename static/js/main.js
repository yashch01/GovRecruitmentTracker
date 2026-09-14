/**
 * GovRecruitmentTracker — Frontend Architecture
 * Features:
 *   - Instant Dark/Light Theme Switching (LocalStorage persisted, zero FOUC)
 *   - Slide-over Tracking Drawer (AJAX status/notes updater without reload)
 *   - AJAX Quick Actions (Single-job Calendar Sync & Telegram Alert)
 *   - Toast Notification Dispatcher
 *   - Mobile Menu Handler
 */

(function () {
    "use strict";

    // ── 1. Theme Management ──────────────────────────────────────────────────
    function initTheme() {
        const toggleBtn = document.getElementById("themeToggleBtn");
        const themeIcon = document.getElementById("themeIcon");

        function updateIcon(theme) {
            if (themeIcon) {
                themeIcon.textContent = theme === "dark" ? "🌙" : "☀️";
            }
        }

        const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
        updateIcon(currentTheme);

        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                const active = document.documentElement.getAttribute("data-theme") || "dark";
                const next = active === "dark" ? "light" : "dark";
                document.documentElement.setAttribute("data-theme", next);
                localStorage.setItem("grt-theme", next);
                updateIcon(next);
            });
        }
    }

    // ── 2. Toast System ──────────────────────────────────────────────────────
    function showToast(message, type = "info", duration = 4000) {
        let container = document.getElementById("toast-container");
        if (!container) {
            container = document.createElement("div");
            container.id = "toast-container";
            document.body.appendChild(container);
        }

        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;

        const icons = {
            success: "✅",
            error: "❌",
            info: "ℹ️",
            warning: "⚠️",
        };
        const icon = icons[type] || "ℹ️";

        toast.innerHTML = `<span>${icon}</span><span style="flex-grow:1">${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = "toastFadeOut 0.25s forwards";
            setTimeout(() => toast.remove(), 250);
        }, duration);
    }

    // Expose showToast globally
    window.showToast = showToast;

    // ── 3. Slide-over Tracking Drawer ────────────────────────────────────────
    let activeJobId = null;

    function initDrawer() {
        const backdrop = document.getElementById("jobDrawerBackdrop");
        const panel = document.getElementById("jobDrawerPanel");
        const closeBtn = document.getElementById("closeDrawerBtn");
        const form = document.getElementById("jobDrawerForm");

        if (!backdrop || !panel) return;

        window.openJobDrawer = async function (jobId) {
            activeJobId = jobId;
            try {
                const res = await fetch(`/api/jobs/${jobId}`, {
                    headers: { Accept: "application/json" },
                });
                if (!res.ok) throw new Error("Could not load job details");
                const data = await res.json();
                const job = data.job;

                // Populate drawer form fields
                document.getElementById("drawerJobId").value = job.id;
                document.getElementById("drawerJobTitle").textContent = `${job.organization} — ${job.title}`;
                document.getElementById("drawerStatus").value = job.user_status || job.application_status || "Not Applied";
                document.getElementById("drawerNotes").value = job.notes || "";
                document.getElementById("drawerRegNum").value = job.registration_number || "";
                document.getElementById("drawerRollNum").value = job.roll_number || "";
                document.getElementById("drawerDeadline").textContent = job.last_date || "Refer Notice";
                document.getElementById("drawerExamDate").textContent = job.exam_date || "TBA";

                // Open panel
                backdrop.classList.add("active");
                panel.classList.add("active");
                document.body.style.overflow = "hidden";
            } catch (err) {
                showToast(`Error opening drawer: ${err.message}`, "error");
            }
        };

        window.closeJobDrawer = function () {
            backdrop.classList.remove("active");
            panel.classList.remove("active");
            document.body.style.overflow = "";
            activeJobId = null;
        };

        if (closeBtn) {
            closeBtn.addEventListener("click", window.closeJobDrawer);
        }
        backdrop.addEventListener("click", window.closeJobDrawer);

        // Escape key closes drawer
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && panel.classList.contains("active")) {
                window.closeJobDrawer();
            }
        });

        // AJAX Form Submit
        if (form) {
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                if (!activeJobId) return;

                const submitBtn = form.querySelector("button[type='submit']");
                const originalText = submitBtn.textContent;
                submitBtn.disabled = true;
                submitBtn.textContent = "Saving...";

                const payload = {
                    user_status: document.getElementById("drawerStatus").value,
                    notes: document.getElementById("drawerNotes").value,
                    registration_number: document.getElementById("drawerRegNum").value,
                    roll_number: document.getElementById("drawerRollNum").value,
                };

                try {
                    const res = await fetch(`/api/jobs/${activeJobId}/status`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Accept: "application/json",
                        },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.message || "Save failed");

                    // Update DOM element for this job if present on page
                    updateJobCardInDOM(activeJobId, payload.user_status, payload.notes);

                    showToast("Application tracking updated successfully!", "success");
                    window.closeJobDrawer();
                } catch (err) {
                    showToast(`Failed to update status: ${err.message}`, "error");
                } finally {
                    submitBtn.disabled = false;
                    submitBtn.textContent = originalText;
                }
            });
        }
    }

    function updateJobCardInDOM(jobId, newStatus, newNotes) {
        // Update status badge on card if exists
        const statusBadge = document.querySelector(`[data-job-status-badge="${jobId}"]`);
        if (statusBadge) {
            statusBadge.textContent = newStatus;
        }
        // Update status select if present
        const statusSelect = document.querySelector(`[data-job-status-select="${jobId}"]`);
        if (statusSelect) {
            statusSelect.value = newStatus;
        }
    }

    // ── 4. Quick Actions (Calendar Sync & Telegram) ──────────────────────────
    window.syncJobToCalendar = async function (jobId, btnEl) {
        const originalText = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = "<span>⏳</span> <span>Syncing...</span>";

        try {
            const res = await fetch(`/jobs/${jobId}/sync-calendar`, {
                method: "POST",
                headers: { Accept: "application/json" },
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Sync failed");

            btnEl.className = "btn btn-xs btn-success";
            btnEl.innerHTML = "<span>✓</span> <span>Synced</span>";
            showToast(`Job #${jobId} synced with Google Calendar!`, "success");
        } catch (err) {
            btnEl.disabled = false;
            btnEl.innerHTML = originalText;
            showToast(`Calendar sync error: ${err.message}`, "error");
        }
    };

    window.sendJobTelegramAlert = async function (jobId, btnEl) {
        const originalText = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = "<span>✈️</span> <span>Sending...</span>";

        try {
            const res = await fetch(`/jobs/${jobId}/notify-telegram`, {
                method: "POST",
                headers: { Accept: "application/json" },
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Failed");

            btnEl.disabled = false;
            btnEl.innerHTML = originalText;
            showToast("Telegram alert dispatched!", "success");
        } catch (err) {
            btnEl.disabled = false;
            btnEl.innerHTML = originalText;
            showToast(`Telegram alert error: ${err.message}`, "error");
        }
    };

    // ── 5. View Switcher (Table vs Card on Desktop) ──────────────────────────
    function initViewSwitcher() {
        const tableBtn = document.getElementById("viewTableBtn");
        const cardsBtn = document.getElementById("viewCardsBtn");
        const tableView = document.getElementById("desktopTableView");
        const cardsView = document.getElementById("jobsCardsView");

        if (!tableBtn || !cardsBtn || !tableView || !cardsView) return;

        const savedView = localStorage.getItem("grt-view-mode") || "table";
        applyView(savedView);

        tableBtn.addEventListener("click", () => applyView("table"));
        cardsBtn.addEventListener("click", () => applyView("cards"));

        function applyView(mode) {
            localStorage.setItem("grt-view-mode", mode);
            if (mode === "cards") {
                tableView.style.display = "none";
                cardsView.classList.remove("desktop-only");
                cardsBtn.classList.add("btn-primary");
                cardsBtn.classList.remove("btn-outline");
                tableBtn.classList.remove("btn-primary");
                tableBtn.classList.add("btn-outline");
            } else {
                tableView.style.display = "block";
                cardsView.classList.add("desktop-only");
                tableBtn.classList.add("btn-primary");
                tableBtn.classList.remove("btn-outline");
                cardsBtn.classList.remove("btn-primary");
                cardsBtn.classList.add("btn-outline");
            }
        }
    }

    // ── 6. Mobile Navbar Toggle ──────────────────────────────────────────────
    function initMobileMenu() {
        const menuBtn = document.getElementById("mobileMenuBtn");
        const menu = document.getElementById("mobileMenu");
        if (!menuBtn || !menu) return;

        menuBtn.addEventListener("click", () => {
            menu.classList.toggle("hidden");
        });
    }

    // ── 7. Table Header Column Sorting ───────────────────────────────────────
    function parseDeadline(dateStr) {
        if (!dateStr) return 0;
        const dmy = dateStr.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
        if (dmy) {
            return new Date(parseInt(dmy[3], 10), parseInt(dmy[2], 10) - 1, parseInt(dmy[1], 10)).getTime();
        }
        const iso = Date.parse(dateStr);
        return isNaN(iso) ? 0 : iso;
    }

    function initTableSort() {
        const table = document.getElementById("jobsTable");
        if (!table) return;
        const headers = table.querySelectorAll("th.sortable");
        let currentSort = { col: null, dir: "asc" };

        headers.forEach((th) => {
            th.addEventListener("click", () => {
                const col = th.getAttribute("data-sort");
                const newDir = (currentSort.col === col && currentSort.dir === "asc") ? "desc" : "asc";
                currentSort = { col, dir: newDir };

                headers.forEach((h) => {
                    h.classList.remove("sorted-asc", "sorted-desc");
                    const ind = h.querySelector(".sort-indicator");
                    if (ind) ind.textContent = "⇅";
                });

                th.classList.add(newDir === "asc" ? "sorted-asc" : "sorted-desc");
                const indicator = th.querySelector(".sort-indicator");
                if (indicator) indicator.textContent = newDir === "asc" ? "▲" : "▼";

                const tbody = table.querySelector("tbody");
                if (!tbody) return;
                const rows = Array.from(tbody.querySelectorAll("tr.job-row"));

                rows.sort((a, b) => {
                    const valA = a.getAttribute(`data-${col}`) || "";
                    const valB = b.getAttribute(`data-${col}`) || "";

                    if (col === "deadline") {
                        const timeA = parseDeadline(valA);
                        const timeB = parseDeadline(valB);
                        return newDir === "asc" ? (timeA - timeB) : (timeB - timeA);
                    }

                    return newDir === "asc"
                        ? valA.localeCompare(valB, undefined, { numeric: true })
                        : valB.localeCompare(valA, undefined, { numeric: true });
                });

                rows.forEach((r) => tbody.appendChild(r));
            });
        });
    }

    // ── 8. Instant Live Search Filtering ─────────────────────────────────────
    function initDynamicFilters() {
        const searchInput = document.querySelector("input[name='search']");
        const countSpan = document.querySelector("span strong.text-main");
        if (!searchInput) return;

        let debounceTimer;
        searchInput.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                const query = searchInput.value.trim().toLowerCase();
                const tableRows = document.querySelectorAll(".job-row");
                const jobCards = document.querySelectorAll(".job-card");
                let visibleCount = 0;

                const filterItem = (el) => {
                    const text = el.textContent.toLowerCase();
                    const matches = !query || text.includes(query);
                    el.style.display = matches ? "" : "none";
                    return matches;
                };

                tableRows.forEach((r) => {
                    if (filterItem(r)) visibleCount++;
                });

                jobCards.forEach((c) => filterItem(c));

                if (countSpan && query) {
                    countSpan.textContent = `${visibleCount}`;
                }
            }, 120);
        });
    }

    // Initialize all modules on DOMContentLoaded
    document.addEventListener("DOMContentLoaded", () => {
        initTheme();
        initDrawer();
        initViewSwitcher();
        initMobileMenu();
        initTableSort();
        initDynamicFilters();
    });
})();
