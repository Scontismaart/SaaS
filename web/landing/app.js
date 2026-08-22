/* Melpis landing — vanilla JS, zero dipendenze */
(function () {
    'use strict';

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ---------- API base: same-origin in produzione, override per sviluppo ---------- */
    var API_BASE = (window.MELPIS_API_BASE || '').replace(/\/$/, '');

    /* ---------- Menu mobile ---------- */
    var hamburger = document.getElementById('hamburger');
    var overlay = document.getElementById('navOverlay');

    function setNav(open) {
        overlay.classList.toggle('open', open);
        overlay.setAttribute('aria-hidden', String(!open));
        hamburger.classList.toggle('open', open);
        hamburger.setAttribute('aria-expanded', String(open));
        hamburger.setAttribute('aria-label', open ? 'Chiudi menu' : 'Apri menu');
        document.body.style.overflow = open ? 'hidden' : '';
    }
    function closeNav() { setNav(false); }

    if (hamburger && overlay) {
        hamburger.addEventListener('click', function () {
            setNav(!overlay.classList.contains('open'));
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeNav();
        });
    }
    window.closeNav = closeNav;

    /* ---------- Navbar shadow ---------- */
    var pill = document.getElementById('navbarPill');
    if (pill) {
        var sentinel = document.createElement('div');
        sentinel.style.cssText = 'position:absolute;top:0;left:0;width:1px;height:1px;';
        document.body.prepend(sentinel);
        new IntersectionObserver(function (entries) {
            pill.classList.toggle('scrolled', !entries[0].isIntersecting);
        }).observe(sentinel);
    }

    /* ---------- Scroll reveal ---------- */
    if (reduceMotion) {
        document.querySelectorAll('.reveal').forEach(function (el) {
            el.classList.add('visible');
        });
    } else {
        var revObs = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    revObs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
        document.querySelectorAll('.reveal:not(.visible)').forEach(function (el) {
            revObs.observe(el);
        });
    }

    /* ---------- Scroll progress (fallback senza animation-timeline) ---------- */
    (function () {
        var el = document.getElementById('scrollProgress');
        if (!el || CSS.supports('animation-timeline: scroll()')) return;
        var ticking = false;
        var update = function () {
            var h = document.documentElement;
            var max = h.scrollHeight - h.clientHeight;
            el.style.transform = 'scaleX(' + (max > 0 ? h.scrollTop / max : 0) + ')';
            ticking = false;
        };
        document.addEventListener('scroll', function () {
            if (!ticking) { requestAnimationFrame(update); ticking = true; }
        }, { passive: true });
        update();
    })();

    /* ---------- Spotlight hover ---------- */
    if (window.matchMedia('(hover: hover)').matches) {
        document.querySelectorAll('.spotlight').forEach(function (card) {
            card.addEventListener('mousemove', function (e) {
                var rect = card.getBoundingClientRect();
                card.style.setProperty('--mx', (e.clientX - rect.left) + 'px');
                card.style.setProperty('--my', (e.clientY - rect.top) + 'px');
            });
        });
    }

    /* ---------- Tilt telefono ---------- */
    (function () {
        if (reduceMotion || !window.matchMedia('(hover: hover)').matches) return;
        var container = document.getElementById('phoneContainer');
        var frame = document.getElementById('phoneFrame');
        var reflection = document.getElementById('screenReflection');
        if (!container || !frame) return;
        var base = 'rotateY(-22deg) rotateX(10deg) rotateZ(-2deg)';
        var ticking = false;

        container.addEventListener('mousemove', function (e) {
            if (!ticking) {
                requestAnimationFrame(function () {
                    var r = container.getBoundingClientRect();
                    var px = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
                    var py = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
                    frame.style.transition = 'none';
                    frame.style.transform =
                        'rotateY(' + (px * 20).toFixed(1) + 'deg)' +
                        ' rotateX(' + (-py * 12).toFixed(1) + 'deg)' +
                        ' rotateZ(' + (-px * py * 4).toFixed(1) + 'deg)';
                    if (reflection) {
                        reflection.style.background = 'linear-gradient(' +
                            (125 + px * 12).toFixed(0) + 'deg, rgba(255,255,255,0.07) 0%, transparent 40%)';
                    }
                    ticking = false;
                });
                ticking = true;
            }
        });
        container.addEventListener('mouseleave', function () {
            frame.style.transition = 'transform 0.6s cubic-bezier(0.2, 0.8, 0.2, 1)';
            frame.style.transform = base;
            if (reflection) reflection.style.background = '';
        });
    })();

    /* ---------- Bottoni magnetici ---------- */
    if (!reduceMotion && window.matchMedia('(hover: hover)').matches) {
        document.querySelectorAll('.magnetic').forEach(function (el) {
            el.addEventListener('mousemove', function (e) {
                var r = el.getBoundingClientRect();
                var x = (e.clientX - (r.left + r.width / 2)) * 0.18;
                var y = (e.clientY - (r.top + r.height / 2)) * 0.18;
                el.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)';
            });
            el.addEventListener('mouseleave', function () { el.style.transform = ''; });
        });
    }

    /* ---------- Toggle prezzi ---------- */
    (function () {
        var toggle = document.getElementById('pricingToggle');
        if (!toggle) return;
        var labelM = document.getElementById('labelMonthly');
        var labelY = document.getElementById('labelYearly');
        var yearly = false;

        toggle.addEventListener('click', function () {
            yearly = !yearly;
            toggle.setAttribute('aria-checked', String(yearly));
            document.querySelectorAll('.price-value').forEach(function (el) {
                el.textContent = yearly ? el.dataset.yearly : el.dataset.monthly;
            });
            document.querySelectorAll('.price-period').forEach(function (el) {
                el.textContent = yearly ? '/mese' : '/mese';
            });
            document.querySelectorAll('.yearly-note').forEach(function (el) {
                el.classList.toggle('hidden', !yearly);
            });
            labelM.classList.toggle('active', !yearly);
            labelY.classList.toggle('active', yearly);
        });
    })();

    /* ---------- Accordion FAQ accessibile ---------- */
    document.querySelectorAll('.faq-q').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var expanded = btn.getAttribute('aria-expanded') === 'true';
            document.querySelectorAll('.faq-q[aria-expanded="true"]').forEach(function (other) {
                other.setAttribute('aria-expanded', 'false');
                var ans = other.parentElement.querySelector('.faq-answer');
                ans.classList.remove('open');
                setTimeout(function () { ans.hidden = true; }, 450);
            });
            var answer = btn.parentElement.querySelector('.faq-answer');
            if (!expanded) {
                btn.setAttribute('aria-expanded', 'true');
                answer.hidden = false;
                requestAnimationFrame(function () { answer.classList.add('open'); });
            }
        });
    });

    /* ---------- Modal signup ---------- */
    var modal = document.getElementById('signupModal');
    var lastFocused = null;

    function openModal(plan) {
        lastFocused = document.activeElement;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        var nome = document.getElementById('su-nome');
        var btns = document.querySelectorAll('[data-signup][data-plan]');
        btns.forEach(function (b) { b.dataset.plan = plan || b.dataset.plan; });
        setTimeout(function () { nome.focus(); }, 60);
        document.addEventListener('keydown', onModalKeydown);
    }

    function closeModal() {
        modal.hidden = true;
        document.body.style.overflow = '';
        document.removeEventListener('keydown', onModalKeydown);
        if (lastFocused) lastFocused.focus();
    }

    function onModalKeydown(e) {
        if (e.key === 'Escape') { closeModal(); return; }
        if (e.key !== 'Tab') return;
        var focusables = modal.querySelectorAll(
            'button:not([disabled]), input, a[href]'
        );
        var list = Array.prototype.filter.call(focusables, function (el) {
            return el.offsetParent !== null;
        });
        if (!list.length) return;
        var first = list[0], last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        }
    }

    document.querySelectorAll('[data-signup]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            closeNav();
            openModal(btn.dataset.plan);
        });
    });
    document.querySelectorAll('[data-modal-close]').forEach(function (el) {
        el.addEventListener('click', closeModal);
    });
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeModal();
        });
    }

    // Apertura via URL: miosito.it/#prova (link "registrati" dalla dashboard)
    if (modal && window.location.hash === '#prova') {
        openModal();
    }

    /* ---------- Submit registrazione ---------- */
    var form = document.getElementById('signupForm');
    var errBox = document.getElementById('signupError');
    var okBox = document.getElementById('signupSuccess');
    var submitBtn = document.getElementById('signupSubmit');

    function showError(msg) {
        errBox.textContent = msg;
        errBox.hidden = false;
        okBox.hidden = true;
    }

    if (form) {
        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            errBox.hidden = true;

            var nomeAttivita = document.getElementById('su-nome').value.trim();
            var email = document.getElementById('su-email').value.trim();
            var password = document.getElementById('su-password').value;
            var termini = document.getElementById('su-termini').checked;

            if (!nomeAttivita) { showError('Inserisci il nome della tua attività.'); return; }
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { showError('Inserisci un indirizzo email valido.'); return; }
            if (password.length < 8) { showError('La password deve avere almeno 8 caratteri.'); return; }
            if (!termini) { showError('Per continuare devi accettare Privacy Policy e Termini di Servizio.'); return; }

            submitBtn.disabled = true;
            submitBtn.firstChild.textContent = 'Creazione in corso… ';

            try {
                var resp = await fetch(API_BASE + '/api/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({
                        email: email,
                        password: password,
                        nome_attivita: nomeAttivita
                    })
                });
                var data = await resp.json().catch(function () { return {}; });

                if (resp.ok && data.ok) {
                    if (data.email_verified) {
                        // Sessione attiva (email auto-confirm): via al pannello
                        window.location.href = '/app/';
                        return;
                    }
                    // Verifica email richiesta
                    form.reset();
                    okBox.hidden = false;
                    errBox.hidden = true;
                } else if (resp.status === 409) {
                    showError(data.detail || 'Risulti già registrato con questa email: prova ad accedere.');
                } else if (resp.status === 429) {
                    showError(data.detail || 'Troppi tentativi. Riprova più tardi.');
                } else {
                    showError(data.detail || 'Registrazione non riuscita. Riprova tra poco.');
                }
            } catch (networkErr) {
                showError('Connessione non riuscita. Controlla la rete e riprova.');
            } finally {
                submitBtn.disabled = false;
                submitBtn.firstChild.textContent = 'Crea il mio assistente ';
            }
        });
    }
})();
