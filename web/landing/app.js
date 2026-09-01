/* Melpis Landing Page — Lemni Architecture Controller (Vanilla JS, Zero Dependencies) */
(function () {
    'use strict';

    // Segnala JS attivo: il CSS nasconde .reveal/.stagger-* solo sotto html.js,
    // così il contenuto resta visibile se app.js non si carica o JS è disabilitato.
    document.documentElement.classList.add('js');

    /* ---------- Plausible Analytics ---------- */
    function trackEvent(name, props) {
        if (typeof window.plausible === 'function') {
            window.plausible(name, { props: props || {} });
        }
    }

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ---------- Mobile Menu Overlay ---------- */
    var hamburger = document.getElementById('navHamburger');
    var overlay = document.getElementById('mobileOverlay');

    function setNav(open) {
        if (!overlay || !hamburger) return;
        overlay.classList.toggle('open', open);
        overlay.setAttribute('aria-hidden', String(!open));
        hamburger.setAttribute('aria-expanded', String(open));
        document.body.style.overflow = open ? 'hidden' : '';
    }
    function closeNav() { setNav(false); }

    if (hamburger) {
        hamburger.addEventListener('click', function () {
            setNav(!overlay.classList.contains('open'));
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeNav();
        });
    }
    // Chiusura menu da link e CTA nell'overlay (sostituisce i vecchi onclick inline)
    if (overlay) {
        overlay.querySelectorAll('.mobile-link, .btn-pill-cta').forEach(function (el) {
            el.addEventListener('click', closeNav);
        });
    }

    /* ---------- Continuous Assembling & Dissolving Real Melpis Dashboard Loop ---------- */
    (function initDashboardAssemblyLoop() {
        var win = document.getElementById('heroDashWindow');
        var viewport = document.getElementById('heroDashViewport');
        var sidebar = document.getElementById('dashPieceSidebar');
        var topbar = document.getElementById('dashPieceTopbar');
        var stat1 = document.getElementById('dashStat1');
        var stat2 = document.getElementById('dashStat2');
        var stat3 = document.getElementById('dashStat3');
        var panels = document.getElementById('dashPiecePanels');
        var statVal1 = document.getElementById('statVal1');
        var statVal2 = document.getElementById('statVal2');
        var statVal3 = document.getElementById('statVal3');

        if (!win) return;

        function setFloatState(active) {
            if (viewport) viewport.classList.toggle('is-floating', active);
            win.classList.toggle('is-assembled', active);
            if (stat1) stat1.classList.toggle('float-a', active);
            if (stat2) stat2.classList.toggle('float-b', active);
            if (stat3) stat3.classList.toggle('float-c', active);
        }

        if (reduceMotion) {
            win.classList.remove('is-dissolving');
            [sidebar, topbar, stat1, stat2, stat3, panels].forEach(function (el) {
                if (el) el.classList.add('is-mounted');
            });
            if (statVal1) statVal1.textContent = '12';
            if (statVal2) statVal2.textContent = '9';
            if (statVal3) statVal3.textContent = '5';
            return;
        }

        var timelineTimeouts = [];

        function clearTimeline() {
            timelineTimeouts.forEach(function (t) { clearTimeout(t); });
            timelineTimeouts = [];
        }

        function countUp(el, target, duration) {
            if (!el) return;
            var startTime = null;
            function step(timestamp) {
                if (!startTime) startTime = timestamp;
                var progress = Math.min((timestamp - startTime) / duration, 1);
                var easeProgress = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.floor(easeProgress * target);
                if (progress < 1) {
                    window.requestAnimationFrame(step);
                } else {
                    el.textContent = target;
                }
            }
            window.requestAnimationFrame(step);
        }

        function runCycle() {
            clearTimeline();
            setFloatState(false);

            // 1. Reset all pieces instantly
            win.classList.remove('is-dissolving');
            [sidebar, topbar, stat1, stat2, stat3, panels].forEach(function (el) {
                if (el) el.classList.remove('is-mounted');
            });
            if (statVal1) statVal1.textContent = '0';
            if (statVal2) statVal2.textContent = '0';
            if (statVal3) statVal3.textContent = '0';

            // Step 1: Sidebar at 120ms
            timelineTimeouts.push(setTimeout(function () {
                if (sidebar) sidebar.classList.add('is-mounted');
            }, 120));

            // Step 2: Topbar at 420ms
            timelineTimeouts.push(setTimeout(function () {
                if (topbar) topbar.classList.add('is-mounted');
            }, 420));

            // Step 3: Stat Card 1 at 720ms
            timelineTimeouts.push(setTimeout(function () {
                if (stat1) stat1.classList.add('is-mounted');
                countUp(statVal1, 12, 900);
            }, 720));

            // Step 4: Stat Card 2 at 960ms
            timelineTimeouts.push(setTimeout(function () {
                if (stat2) stat2.classList.add('is-mounted');
                countUp(statVal2, 9, 900);
            }, 960));

            // Step 5: Stat Card 3 at 1200ms
            timelineTimeouts.push(setTimeout(function () {
                if (stat3) stat3.classList.add('is-mounted');
                countUp(statVal3, 5, 900);
            }, 1200));

            // Step 6: Bottom Panels at 1500ms + start float loop
            timelineTimeouts.push(setTimeout(function () {
                if (panels) panels.classList.add('is-mounted');
                setFloatState(true);
            }, 1500));

            // Step 7: Live micro-event at 3600ms (Stat 1 increments to 13 + subtle bump)
            timelineTimeouts.push(setTimeout(function () {
                if (statVal1 && stat1 && stat1.classList.contains('is-mounted')) {
                    statVal1.textContent = '13';
                    stat1.style.transform = 'translateY(-3px) scale(1.02)';
                    setTimeout(function () {
                        if (stat1) stat1.style.transform = '';
                    }, 350);
                }
            }, 3600));

            // Step 8: Dissolve out whole dashboard at 5800ms
            timelineTimeouts.push(setTimeout(function () {
                setFloatState(false);
                if (win) win.classList.add('is-dissolving');
            }, 5800));

            // Step 9: Loop back at 6700ms
            timelineTimeouts.push(setTimeout(runCycle, 6700));
        }

        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            setTimeout(runCycle, 150);
        } else {
            window.addEventListener('DOMContentLoaded', function () {
                setTimeout(runCycle, 150);
            });
        }
    })();

    /* ---------- Human-in-the-Loop Takeover Interactive Animation Demo ---------- */
    (function initHitlTakeoverDemo() {
        var windowEl = document.getElementById('hitlMockupWindow');
        var statusPill = document.getElementById('hitlStatusPill');
        var takeoverRibbon = document.getElementById('hitlTakeoverRibbon');
        var takeoverBtn = document.getElementById('hitlTakeoverBtn');
        var btnTxt = document.getElementById('hitlBtnTxt');
        var ribbonLabel = document.getElementById('hitlRibbonLabel');
        var threadTag = document.getElementById('hitlThreadTag');
        var virtualCursor = document.getElementById('hitlVirtualCursor');
        var cursorRipple = document.getElementById('hitlCursorRipple');
        var inputPlaceholder = document.getElementById('hitlInputPlaceholder');

        if (!windowEl || !takeoverBtn) return;

        if (reduceMotion) {
            windowEl.classList.add('is-takeover-active');
            if (statusPill) {
                statusPill.className = 'hitl-status-pill pill-human';
                statusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">Ripreso da te · Staff in linea</span>';
            }
            if (takeoverRibbon) takeoverRibbon.classList.add('is-taken');
            if (takeoverBtn) {
                takeoverBtn.classList.add('is-active');
                if (btnTxt) btnTxt.textContent = 'Controllo attivo';
            }
            if (ribbonLabel) ribbonLabel.textContent = 'Controllo Umano attivo';
            if (threadTag) threadTag.textContent = 'Preso in carico';
            if (inputPlaceholder) inputPlaceholder.textContent = 'Rispondi come Melpis Barbershop...';
            if (virtualCursor) virtualCursor.style.display = 'none';
            return;
        }

        var hitlTimeouts = [];

        function clearHitlTimeline() {
            hitlTimeouts.forEach(function (t) { clearTimeout(t); });
            hitlTimeouts = [];
        }

        function runHitlLoop() {
            clearHitlTimeline();

            // State 1: Reset to AI Mode
            windowEl.classList.remove('is-takeover-active');
            if (statusPill) {
                statusPill.className = 'hitl-status-pill pill-ai';
                statusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">Gestito dall\'AI</span>';
            }
            if (takeoverRibbon) takeoverRibbon.classList.remove('is-taken');
            if (takeoverBtn) {
                takeoverBtn.classList.remove('is-active');
                if (btnTxt) btnTxt.textContent = 'Prendi controllo';
            }
            if (ribbonLabel) ribbonLabel.textContent = 'Controllo AI attivo';
            if (threadTag) threadTag.textContent = '— in corso';
            if (inputPlaceholder) inputPlaceholder.textContent = 'AI in ascolto attivo...';
            
            if (virtualCursor) {
                virtualCursor.style.opacity = '0';
                virtualCursor.style.transform = 'translate(180px, 200px)';
            }
            if (cursorRipple) cursorRipple.classList.remove('pulse');

            // State 2: Cursor appears (at 1.2s)
            hitlTimeouts.push(setTimeout(function () {
                if (virtualCursor) {
                    virtualCursor.style.opacity = '0.95';
                }
            }, 1200));

            // State 3: Cursor moves to Takeover Button (at 1.7s)
            hitlTimeouts.push(setTimeout(function () {
                if (virtualCursor && takeoverBtn) {
                    var btnRect = takeoverBtn.getBoundingClientRect();
                    var winRect = windowEl.getBoundingClientRect();
                    var relX = btnRect.left - winRect.left + btnRect.width / 2;
                    var relY = btnRect.top - winRect.top + btnRect.height / 2;
                    virtualCursor.style.transform = 'translate(' + relX + 'px, ' + relY + 'px)';
                }
            }, 1700));

            // State 4: Simulated Click (at 2.8s)
            hitlTimeouts.push(setTimeout(function () {
                if (cursorRipple) {
                    cursorRipple.classList.remove('pulse');
                    void cursorRipple.offsetWidth; // trigger reflow
                    cursorRipple.classList.add('pulse');
                }
                if (takeoverBtn) {
                    takeoverBtn.style.transform = 'scale(0.92)';
                    setTimeout(function () {
                        if (takeoverBtn) takeoverBtn.style.transform = '';
                    }, 200);
                }
            }, 2800));

            // State 5: Takeover Active Transition (at 3.1s)
            hitlTimeouts.push(setTimeout(function () {
                windowEl.classList.add('is-takeover-active');
                if (statusPill) {
                    statusPill.className = 'hitl-status-pill pill-human';
                    statusPill.innerHTML = '<span class="pill-dot"></span><span class="pill-text">Ripreso da te · Staff in linea</span>';
                }
                if (takeoverRibbon) takeoverRibbon.classList.add('is-taken');
                if (takeoverBtn) {
                    takeoverBtn.classList.add('is-active');
                    if (btnTxt) btnTxt.textContent = 'Controllo attivo';
                }
                if (ribbonLabel) ribbonLabel.textContent = 'Controllo Umano attivo';
                if (threadTag) threadTag.textContent = '— preso in carico';
                if (inputPlaceholder) inputPlaceholder.textContent = 'Rispondi come Melpis Barbershop...';
                if (virtualCursor) virtualCursor.style.opacity = '0';
            }, 3100));

            // State 6: Loop back after hold (at 7.8s)
            hitlTimeouts.push(setTimeout(runHitlLoop, 7800));
        }

        // Trigger when section comes into view (IntersectionObserver)
        if ('IntersectionObserver' in window) {
            var hitlObserver = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        runHitlLoop();
                    } else {
                        clearHitlTimeline();
                    }
                });
            }, { threshold: 0.15 });
            hitlObserver.observe(windowEl);
        } else {
            setTimeout(runHitlLoop, 1000);
        }
    })();

    /* ---------- Scroll Reveal (IntersectionObserver) ---------- */
    if (reduceMotion) {
        document.querySelectorAll('.reveal').forEach(function (el) {
            el.classList.add('visible');
        });
    } else if ('IntersectionObserver' in window) {
        var revObs = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    revObs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

        document.querySelectorAll('.reveal:not(.visible)').forEach(function (el) {
            revObs.observe(el);
        });
    }

    /* ---------- Sticky Slide-Over Sync (pin offsets & hook heights) ---------- */
    /* Il vincolo sticky è il content box del genitore: lo spazio di aggancio è
       uno spacer ::after dentro .pin-wrap (vedi style.css), non un padding.
       Qui si misurano le altezze reali per (a) far pinnare le sezioni solo quando
       il loro bordo inferiore raggiunge il fondo della viewport — così nessun
       contenuto viene coperto prima di essere letto — e (b) limitare l'hook di
       pin-wrap-2 all'altezza di pricing, così nessuna banda resta scoperta.
       Nessuno scroll listener, solo resize/ResizeObserver. */
    (function initSlideOverSync() {
        var features = document.querySelector('.features-split-section');
        var hitl = document.querySelector('.hitl-section');
        var pricing = document.querySelector('.pricing-section');
        var faq = document.querySelector('.faq-section');
        var finalCta = document.querySelector('.final-cta-section');
        if (!features || !hitl || !pricing || !faq || !finalCta || !('ResizeObserver' in window)) return;

        var desktop = window.matchMedia('(min-width: 961px)');

        function sync() {
            if (!desktop.matches) return;
            var vh = window.innerHeight;
            document.documentElement.style.setProperty('--slide-pin-1', (vh - features.offsetHeight) + 'px');
            document.documentElement.style.setProperty('--slide-pin-2', (vh - hitl.offsetHeight) + 'px');
            document.documentElement.style.setProperty('--slide-pin-3', (vh - faq.offsetHeight) + 'px');
            document.documentElement.style.setProperty('--slide-hook-2', Math.min(vh + 120, pricing.offsetHeight) + 'px');
            // hook-3 non deve superare l'altezza della CTA: lo spacer resta tutto
            // coperto e il footer non viene mai sovrapposto
            document.documentElement.style.setProperty('--slide-hook-3', Math.min(vh + 120, finalCta.offsetHeight) + 'px');
        }

        var ro = new ResizeObserver(function () { sync(); });
        ro.observe(features);
        ro.observe(hitl);
        ro.observe(pricing);
        ro.observe(faq);
        ro.observe(finalCta);
        window.addEventListener('resize', sync, { passive: true });
        sync();
    })();

    /* ---------- High-Performance Progressive Narrative Spine Drawing ---------- */
    (function initNarrativeSpine() {
        var section = document.querySelector('.narrative-journey-section');
        var activePath = document.querySelector('.narrative-path-active');
        var glowPath = document.querySelector('.narrative-path-glow');
        var nodes = document.querySelectorAll('.narrative-node');
        if (!section || !activePath) return;

        // 1. Calculate path length dynamically
        var pathLength = 0;
        try {
            pathLength = activePath.getTotalLength();
        } catch (e) {
            pathLength = 1750;
        }
        if (!pathLength || isNaN(pathLength) || pathLength <= 0) {
            pathLength = 1750;
        }

        // Set initial stroke-dasharray and stroke-dashoffset (unvisited / invisible)
        activePath.style.strokeDasharray = pathLength;
        activePath.style.strokeDashoffset = pathLength;
        if (glowPath) {
            glowPath.style.strokeDasharray = pathLength;
            glowPath.style.strokeDashoffset = pathLength;
        }

        if (reduceMotion) {
            activePath.style.strokeDashoffset = '0';
            if (glowPath) glowPath.style.strokeDashoffset = '0';
            nodes.forEach(function (n) { n.classList.add('node-active'); });
            return;
        }

        var maxProgress = 0;

        function setPathProgress(progress) {
            if (progress < 0) progress = 0;
            if (progress > 1) progress = 1;
            var offset = pathLength * (1 - progress);
            activePath.style.strokeDashoffset = offset;
            if (glowPath) glowPath.style.strokeDashoffset = offset;
        }

        function advancePath(node) {
            var wp = parseFloat(node.getAttribute('data-waypoint') || '0');
            if (isNaN(wp)) wp = 0;
            if (wp > maxProgress) {
                maxProgress = wp;
                setPathProgress(maxProgress);
            }
        }

        // Node activation + path draw via IntersectionObserver (no scroll listener)
        if ('IntersectionObserver' in window) {
            var nodeObs = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('node-active');
                        advancePath(entry.target);
                        nodeObs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.18, rootMargin: '0px 0px -20px 0px' });

            nodes.forEach(function (node) {
                nodeObs.observe(node);
            });
        } else {
            nodes.forEach(function (n) {
                n.classList.add('node-active');
                advancePath(n);
            });
        }

        window.addEventListener('resize', function () {
            try {
                var len = activePath.getTotalLength();
                if (len && !isNaN(len) && len > 0) {
                    pathLength = len;
                    activePath.style.strokeDasharray = pathLength;
                    if (glowPath) glowPath.style.strokeDasharray = pathLength;
                    setPathProgress(maxProgress);
                }
            } catch (e) {}
        }, { passive: true });
    })();

    /* ---------- Interactive Sector Rules Switcher (Satellite 3) ---------- */
    (function initSectorRulesSwitcher() {
        var tabs = document.querySelectorAll('.r-tab[data-sector]');
        var container = document.getElementById('rulesMiniItems');
        if (!tabs.length || !container) return;

        var sectorData = {
            ristoranti: [
                { label: 'Gestione coperti e intolleranze', on: true },
                { label: 'Anticipo prenotazione e slot', on: true },
                { label: 'Promemoria automatico no-show', on: true }
            ],
            saloni: [
                { label: 'Durata trattamenti e pieghe', on: true },
                { label: 'Preferenza operatore/stilista', on: true },
                { label: 'Richiesta acconto per no-show', on: true }
            ],
            medici: [
                { label: 'Fail-Closed clinico per urgenze', on: true },
                { label: 'Triage prima visita / controllo', on: true },
                { label: 'Orari reperibilità segreteria', on: true }
            ],
            hotel: [
                { label: 'Check-in/out e orari colazione', on: true },
                { label: 'Politica cancellazione diretta', on: true },
                { label: 'Richieste extra (culla, animali)', on: true }
            ]
        };

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                var sector = tab.getAttribute('data-sector');
                if (!sector || !sectorData[sector]) return;

                tabs.forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');

                // Smooth micro cross-fade
                container.style.opacity = '0';
                setTimeout(function () {
                    var items = sectorData[sector];
                    var html = '';
                    items.forEach(function (item) {
                        html += '<div class="r-item"><span>' + item.label + '</span> <span class="r-toggle ' + (item.on ? 'on' : '') + '"></span></div>';
                    });
                    container.innerHTML = html;
                    container.style.opacity = '1';
                }, 150);
            });
        });
    })();

    /* ---------- Billing Toggle (Mensile / Annuale -20%) ---------- */
    function setBilling(period) {
        var btnMonthly = document.getElementById('btnMonthly');
        var btnAnnual = document.getElementById('btnAnnual');
        if (!btnMonthly || !btnAnnual) return;

        var isAnnual = (period === 'annual');
        btnMonthly.classList.toggle('active', !isAnnual);
        btnAnnual.classList.toggle('active', isAnnual);

        document.querySelectorAll('.p-amount').forEach(function (el) {
            var val = isAnnual ? el.getAttribute('data-annual') : el.getAttribute('data-monthly');
            if (val) {
                el.style.transform = 'scale(1.1)';
                setTimeout(function () {
                    el.textContent = val;
                    el.style.transform = 'scale(1)';
                }, 100);
            }
        });

        trackEvent('Billing_Toggle_Click', { period: period });
    }

    var btnMonthlyEl = document.getElementById('btnMonthly');
    var btnAnnualEl = document.getElementById('btnAnnual');
    if (btnMonthlyEl) btnMonthlyEl.addEventListener('click', function () { setBilling('monthly'); });
    if (btnAnnualEl) btnAnnualEl.addEventListener('click', function () { setBilling('annual'); });

    /* ---------- Signup Modal / Quick Start ---------- */
    var modal = document.getElementById('signupModal');
    var modalClose = document.getElementById('modalClose');

    function openModal() {
        if (!modal) return;
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        var firstInput = document.getElementById('regEmail');
        if (firstInput) setTimeout(function () { firstInput.focus(); }, 100);
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }

    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeModal();
        });
    }

    document.querySelectorAll('[data-signup]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var location = btn.getAttribute('data-track-location') || 'general';
            var plan = btn.getAttribute('data-plan') || '';
            trackEvent('Signup_Button_Click', { location: location, plan: plan });
            openModal();
        });
    });

    function handleSignupSubmit(e) {
        e.preventDefault();
        var form = document.getElementById('signupForm');
        if (!form) return;
        var email = form.email.value.trim();
        var vertical = form.vertical.value;
        trackEvent('Signup_Form_Submit', { vertical: vertical });

        // Redirect to onboarding with parameters
        window.location.href = '/registrati/?email=' + encodeURIComponent(email) + '&settore=' + encodeURIComponent(vertical);
    }

    var signupForm = document.getElementById('signupForm');
    if (signupForm) signupForm.addEventListener('submit', handleSignupSubmit);

    /* ---------- Lemni Quality Split Blocks: Staggered Entrance & Living Motion Loops ---------- */
    (function initLemniSplitBlocks() {
        var splitBlocks = document.querySelectorAll('.split-block-wrap, .integrations-micro-cta');
        if (!splitBlocks.length) return;

        // 1. Staggered Scroll Entrance Observer
        if ('IntersectionObserver' in window) {
            var splitObs = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-visible');
                        splitObs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.10, rootMargin: '0px 0px -30px 0px' });

            splitBlocks.forEach(function (block) {
                splitObs.observe(block);
            });
        } else {
            splitBlocks.forEach(function (b) { b.classList.add('is-visible'); });
        }

        // 2. Knowledge Base Upload Loop
        var kbProgressBar = document.getElementById('kbProgressBar');
        var kbFileName = document.getElementById('kbFileName');
        var kbFileBadge = document.getElementById('kbFileBadge');
        var kbProgressStatus = document.getElementById('kbProgressStatus');
        var kbProgressPercent = document.getElementById('kbProgressPercent');

        var kbFiles = [
            'Menu_e_Allergeni_2026.pdf',
            'Listino_Trattamenti_e_Prezzi.pdf',
            'Regolamento_Prenotazioni_e_Orari.pdf'
        ];
        var kbFileIndex = 0;

        function runKbUploadCycle() {
            if (!kbProgressBar || reduceMotion) return;
            var currentFile = kbFiles[kbFileIndex % kbFiles.length];
            kbFileIndex++;

            if (kbFileName) kbFileName.textContent = currentFile;
            if (kbFileBadge) {
                kbFileBadge.textContent = 'in caricamento';
                kbFileBadge.style.background = 'transparent';
                kbFileBadge.style.color = '#64748B';
            }
            if (kbProgressStatus) kbProgressStatus.textContent = 'Caricamento in corso...';
            if (kbProgressPercent) kbProgressPercent.textContent = '15%';
            kbProgressBar.style.width = '15%';

            // Step 1: Upload progress to 55%
            setTimeout(function () {
                if (!kbProgressBar) return;
                kbProgressBar.style.width = '55%';
                if (kbProgressPercent) kbProgressPercent.textContent = '55%';
                if (kbProgressStatus) kbProgressStatus.textContent = 'Estrazione vettoriale RAG...';
                if (kbFileBadge) kbFileBadge.textContent = 'indicizzazione';
            }, 1200);

            // Step 2: Progress to 88%
            setTimeout(function () {
                if (!kbProgressBar) return;
                kbProgressBar.style.width = '88%';
                if (kbProgressPercent) kbProgressPercent.textContent = '88%';
                if (kbProgressStatus) kbProgressStatus.textContent = 'Validazione guardrail e limiti...';
                if (kbFileBadge) kbFileBadge.textContent = 'validazione';
            }, 2400);

            // Step 3: Complete 100%
            setTimeout(function () {
                if (!kbProgressBar) return;
                kbProgressBar.style.width = '100%';
                if (kbProgressPercent) kbProgressPercent.textContent = '100%';
                if (kbProgressStatus) kbProgressStatus.textContent = 'Pronto & sincronizzato';
                if (kbFileBadge) {
                    kbFileBadge.textContent = 'sincronizzato';
                    kbFileBadge.style.background = 'transparent';
                    kbFileBadge.style.color = '#15803D';
                }
            }, 3600);

            // Reset and loop next file
            setTimeout(runKbUploadCycle, 7500);
        }

        // Start upload loop
        if (!reduceMotion) {
            setTimeout(runKbUploadCycle, 800);
        }

        // 3. Automazioni: Live Calendar Insertion & Review Typing Loop
        var syncBlock = document.querySelector('.sync-block-wrap');
        var toastBanner = document.getElementById('syncToastBanner');
        var incomingSlot = document.getElementById('incomingSlotCard');
        var typingParagraph = document.getElementById('aiTypingParagraph');
        var typingCursor = document.getElementById('typingCursor');

        var reviewReplyText = "Grazie Laura! Siamo felicissimi che abbiate trascorso una bellissima serata. Vi aspettiamo presto!";
        var typingTimer = null;
        var hasStartedSync = false;

        function typeWriter(text, i, callback) {
            if (!typingParagraph) return;
            if (i < text.length) {
                typingParagraph.textContent += text.charAt(i);
                typingTimer = setTimeout(function () {
                    typeWriter(text, i + 1, callback);
                }, 30 + Math.random() * 20);
            } else if (callback) {
                setTimeout(callback, 3500);
            }
        }

        function runSyncSequence() {
            if (!syncBlock || reduceMotion) return;

            // Step 1: Toast & Slot Animation
            if (toastBanner) {
                toastBanner.style.opacity = '0';
                toastBanner.style.transform = 'translateY(-6px)';
                setTimeout(function () {
                    toastBanner.style.opacity = '1';
                    toastBanner.style.transform = 'translateY(0)';
                }, 400);
            }

            if (incomingSlot) {
                incomingSlot.style.opacity = '0';
                incomingSlot.style.transform = 'translateY(-8px)';
                setTimeout(function () {
                    incomingSlot.style.opacity = '1';
                    incomingSlot.style.transform = 'translateY(0)';
                }, 900);
            }

            // Step 2: Review typing stream
            if (typingParagraph) {
                typingParagraph.textContent = '';
                if (typingCursor) typingCursor.style.display = 'inline-block';
                setTimeout(function () {
                    typeWriter(reviewReplyText, 0, function () {
                        // After holding, restart sequence smoothly
                        setTimeout(runSyncSequence, 4000);
                    });
                }, 1400);
            }
        }

        // Trigger sync sequence when block enters viewport
        if ('IntersectionObserver' in window && syncBlock && !reduceMotion) {
            var syncObs = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting && !hasStartedSync) {
                        hasStartedSync = true;
                        runSyncSequence();
                    }
                });
            }, { threshold: 0.15 });
            syncObs.observe(syncBlock);
        } else if (!reduceMotion) {
            runSyncSequence();
        }
    })();

})();
