(function() {
        var header = document.getElementById('mainHeader');
        var dropdown = document.getElementById('navDropdownSettori');
        var trigger = document.getElementById('settoriDropdownTrigger');
        var hamburger = document.getElementById('navHamburger');
        var overlay = document.getElementById('mobileOverlay');
        var accordionBtn = document.getElementById('mobileSettoriBtn');
        var accordionWrap = document.getElementById('mobileSettoriAccordion');

        if (header) {
            var updateScrollState = function() {
                var isScrolled = (window.pageYOffset || document.documentElement.scrollTop || 0) > 15;
                header.classList.toggle('is-scrolled', isScrolled);
            };
            window.addEventListener('scroll', updateScrollState, { passive: true });
            updateScrollState();
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
