(function() {
            var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            if (!reduceMotion && 'IntersectionObserver' in window) {
                document.documentElement.classList.add('js-ready');
            }

                                    // Unified Navbar Controller with Adaptive Theme & Sticky Scroll
            var header = document.getElementById('mainHeader');
            var dropdown = document.getElementById('navDropdownSettori');
            var trigger = document.getElementById('settoriDropdownTrigger');
            var hamburger = document.getElementById('navHamburger');
            var overlay = document.getElementById('mobileOverlay');
            var accordionBtn = document.getElementById('mobileSettoriBtn');
            var accordionWrap = document.getElementById('mobileSettoriAccordion');
            var lightSections = document.querySelectorAll('[data-navbar-theme="light"]');

            if (header) {
                var updateNavbarState = function() {
                    var scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                    header.classList.toggle('is-scrolled', scrollY > 15);

                    if (lightSections.length > 0) {
                        var headerRect = header.getBoundingClientRect();
                        var headerMidY = headerRect.top + (headerRect.height / 2);
                        var isOverLight = false;

                        for (var i = 0; i < lightSections.length; i++) {
                            var secRect = lightSections[i].getBoundingClientRect();
                            if (secRect.top <= headerMidY && secRect.bottom >= headerMidY) {
                                isOverLight = true;
                                break;
                            }
                        }
                        header.classList.toggle('nav-theme-light', isOverLight);
                    }
                };

                window.addEventListener('scroll', updateNavbarState, { passive: true });
                window.addEventListener('resize', updateNavbarState, { passive: true });
                updateNavbarState();
            }

            if (dropdown && trigger) {
                var setDropdown = function(open) {
                    dropdown.classList.toggle('is-open', open);
                    trigger.setAttribute('aria-expanded', String(open));
                };

                trigger.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    setDropdown(!dropdown.classList.contains('is-open'));
                });

                document.addEventListener('click', function(e) {
                    if (!dropdown.contains(e.target)) {
                        setDropdown(false);
                    }
                });

                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape' && dropdown.classList.contains('is-open')) {
                        setDropdown(false);
                        trigger.focus();
                    }
                });

                dropdown.addEventListener('focusout', function() {
                    setTimeout(function() {
                        if (!dropdown.contains(document.activeElement)) {
                            setDropdown(false);
                        }
                    }, 10);
                });
            }

            if (hamburger && overlay) {
                var setNav = function(open) {
                    overlay.classList.toggle('open', open);
                    overlay.setAttribute('aria-hidden', String(!open));
                    hamburger.setAttribute('aria-expanded', String(open));
                    document.body.style.overflow = open ? 'hidden' : '';
                };

                hamburger.addEventListener('click', function(e) {
                    e.preventDefault();
                    setNav(!overlay.classList.contains('open'));
                });

                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape' && overlay.classList.contains('open')) {
                        setNav(false);
                    }
                });

                overlay.querySelectorAll('.mobile-link:not(.mobile-accordion-btn), .mobile-sublink, .btn-cta-primary, .btn-pill-cta').forEach(function(link) {
                    link.addEventListener('click', function() {
                        setNav(false);
                    });
                });
            }

            if (accordionBtn && accordionWrap) {
                accordionBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var isExpanded = accordionWrap.classList.toggle('is-expanded');
                    accordionBtn.setAttribute('aria-expanded', String(isExpanded));
                });
            }

        })();

            // 3. Ambient Mouse Spotlight on Bento Cards (Keplero / Lemni Micro-Interaction)
            var bentoCards = document.querySelectorAll('.bento-card');
            bentoCards.forEach(function(card) {
                card.addEventListener('mousemove', function(e) {
                    var rect = card.getBoundingClientRect();
                    var x = e.clientX - rect.left;
                    var y = e.clientY - rect.top;
                    card.style.setProperty('--mouse-x', x + 'px');
                    card.style.setProperty('--mouse-y', y + 'px');
                });
            });

            // 4. Interactive No-Show Action Demo
            var btnConfirm = document.getElementById('demoBtnConfirm');
            var btnCancel = document.getElementById('demoBtnCancel');
            var feedbackBox = document.getElementById('noshowFeedback');
            var feedbackText = document.getElementById('noshowFeedbackText');

            if (btnConfirm && btnCancel && feedbackBox && feedbackText) {
                btnConfirm.addEventListener('click', function() {
                    btnConfirm.classList.add('is-active-confirm');
                    btnCancel.classList.remove('is-active-cancel');
                    feedbackBox.classList.remove('is-cancelled');
                    feedbackText.textContent = "Presenza confermata dall'ospite · Sincronizzato con Google Calendar";
                });

                btnCancel.addEventListener('click', function() {
                    btnCancel.classList.add('is-active-cancel');
                    btnConfirm.classList.remove('is-active-confirm');
                    feedbackBox.classList.add('is-cancelled');
                    feedbackText.textContent = "Tavolo liberato con anticipo · Notificato per la lista d'attesa";
                });
            }

            // 5. Realistic Animated Chat Sequence with Replay
            var chatWidget = document.getElementById('chatPreviewWidget');
            var bTyping = document.getElementById('chatBubbleTyping');
            var b2 = document.getElementById('chatBubble2');
            var b3 = document.getElementById('chatBubble3');
            var b4 = document.getElementById('chatBubble4');
            var replayBtn = document.getElementById('chatReplayBtn');
            var chatTimers = [];

            function clearChatTimers() {
                chatTimers.forEach(function(t) { clearTimeout(t); });
                chatTimers = [];
            }

            function playChatSimulation() {
                clearChatTimers();
                if (!b2 || !b3 || !b4) return;

                if (bTyping) {
                    bTyping.style.display = 'none';
                    bTyping.style.opacity = '0';
                }
                [b2, b3, b4].forEach(function(b) {
                    b.style.opacity = '0';
                    b.style.transform = 'translateY(10px)';
                    b.style.transition = 'opacity 280ms cubic-bezier(0.16, 1, 0.3, 1), transform 280ms cubic-bezier(0.16, 1, 0.3, 1)';
                });

                chatTimers.push(setTimeout(function() {
                    if (bTyping) {
                        bTyping.style.display = 'inline-flex';
                        setTimeout(function() { bTyping.style.opacity = '1'; }, 20);
                    }
                }, 400));

                chatTimers.push(setTimeout(function() {
                    if (bTyping) bTyping.style.display = 'none';
                    b2.style.opacity = '1';
                    b2.style.transform = 'translateY(0)';
                }, 1300));

                chatTimers.push(setTimeout(function() {
                    b3.style.opacity = '1';
                    b3.style.transform = 'translateY(0)';
                }, 2100));

                chatTimers.push(setTimeout(function() {
                    b4.style.opacity = '1';
                    b4.style.transform = 'translateY(0)';
                }, 2900));
            }

            if (!reduceMotion && 'IntersectionObserver' in window && chatWidget && b2 && b3 && b4) {
                [b2, b3, b4].forEach(function(b) {
                    b.style.opacity = '0';
                    b.style.transform = 'translateY(10px)';
                });

                var hasAnimatedChat = false;
                var chatObserver = new IntersectionObserver(function(entries) {
                    entries.forEach(function(entry) {
                        if (entry.isIntersecting && !hasAnimatedChat) {
                            hasAnimatedChat = true;
                            playChatSimulation();
                            chatObserver.unobserve(chatWidget);
                        }
                    });
                }, { threshold: 0.25 });

                chatObserver.observe(chatWidget);

                if (replayBtn) {
                    replayBtn.addEventListener('click', function(e) {
                        e.preventDefault();
                        playChatSimulation();
                    });
                }
            }
        })();
