/**
 * Melpis — Documentation Interactive Controller (docs.js)
 * High-performance, zero dependencies, client-side live search,
 * scroll-spy TOC, mobile navigation, and code copy.
 */
(function () {
    'use strict';

    function initDocs() {
        var searchInput = document.getElementById('docsSearchInput');
        var searchDropdown = document.getElementById('docsSearchDropdown');
        var mobileToggle = document.getElementById('docsMobileToggle');
        var sidebarNav = document.getElementById('docsSidebarNav');

        /* ── 1. REAL-TIME LIVE SEARCH ── */
        if (searchInput && searchDropdown && window.MELPIS_DOCS_DATA) {
            var articles = window.MELPIS_DOCS_DATA.articles || [];

            var emptyMsgs = {
                it: 'Nessun articolo trovato per questa ricerca.',
                en: 'No articles found matching this query.',
                es: 'No se encontraron artículos para esta búsqueda.',
                fr: 'Aucun article trouvé pour cette recherche.',
                de: 'Keine Artikel für diese Suchanfrage gefunden.'
            };
            var emptyText = emptyMsgs[document.documentElement.lang || 'it'] || emptyMsgs.it;

            function renderResults(matches) {
                if (!matches.length) {
                    searchDropdown.innerHTML = '<div class="docs-search-empty">' + emptyText + '</div>';
                    searchDropdown.classList.add('is-open');
                    return;
                }

                var html = '';
                var max = Math.min(matches.length, 6);
                for (var i = 0; i < max; i++) {
                    var a = matches[i];
                    html += '<a href="' + a.path + '" class="docs-search-result-item">' +
                        '<span class="docs-search-item-cat">' + a.categoryName + '</span>' +
                        '<div class="docs-search-item-title">' + a.title + '</div>' +
                        '<div class="docs-search-item-desc">' + a.description + '</div>' +
                    '</a>';
                }
                searchDropdown.innerHTML = html;
                searchDropdown.classList.add('is-open');
            }

            searchInput.addEventListener('input', function (e) {
                var q = (e.target.value || '').trim().toLowerCase();
                if (q.length < 2) {
                    searchDropdown.innerHTML = '';
                    searchDropdown.classList.remove('is-open');
                    return;
                }

                var tokens = q.split(/\s+/).filter(Boolean);
                var matches = articles.filter(function (art) {
                    var haystack = (art.title + ' ' + art.description + ' ' + (art.keywords ? art.keywords.join(' ') : '') + ' ' + art.categoryName).toLowerCase();
                    return tokens.every(function (tok) {
                        return haystack.indexOf(tok) !== -1;
                    });
                });

                renderResults(matches);
            });

            // Keyboard navigation & global shortcut (Ctrl+K or /)
            document.addEventListener('keydown', function (e) {
                if ((e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') ||
                    ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
                    e.preventDefault();
                    searchInput.focus();
                } else if (e.key === 'Escape' && searchDropdown.classList.contains('is-open')) {
                    searchDropdown.classList.remove('is-open');
                }
            });

            // Close search dropdown on click outside
            document.addEventListener('click', function (e) {
                if (!searchInput.contains(e.target) && !searchDropdown.contains(e.target)) {
                    searchDropdown.classList.remove('is-open');
                }
            });
        }

        /* ── 2. MOBILE SIDEBAR TOGGLE ── */
        if (mobileToggle && sidebarNav) {
            mobileToggle.addEventListener('click', function () {
                var isOpen = sidebarNav.classList.toggle('is-mobile-open');
                mobileToggle.setAttribute('aria-expanded', String(isOpen));
                var spanText = mobileToggle.querySelector('span');
                if (spanText) {
                    spanText.textContent = isOpen ? 'Chiudi indice articoli' : 'Mostra indice articoli';
                }
            });
        }

        /* ── 3. CODE SNIPPET COPY ── */
        var copyBtns = document.querySelectorAll('.docs-copy-btn, .docs-code-copy-btn');
        copyBtns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var card = btn.closest('.docs-code-card') || btn.closest('.docs-code-block');
                if (!card) return;
                var codeEl = card.querySelector('code') || card.querySelector('pre');
                if (!codeEl) return;
                var text = codeEl.innerText || codeEl.textContent;

                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(function () {
                        var orig = btn.innerHTML;
                        btn.innerHTML = '<span>✓ Copiato!</span>';
                        setTimeout(function () {
                            btn.innerHTML = orig;
                        }, 2000);
                    });
                }
            });
        });

        /* ── 4. SCROLL-SPY ON-PAGE TOC ── */
        var tocLinks = document.querySelectorAll('.docs-toc-link');
        if (tocLinks.length > 0 && 'IntersectionObserver' in window) {
            var headings = document.querySelectorAll('.docs-prose h2, .docs-prose h3');
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        var id = entry.target.getAttribute('id');
                        if (!id) return;
                        tocLinks.forEach(function (link) {
                            if (link.getAttribute('href') === '#' + id) {
                                link.classList.add('is-active');
                            } else {
                                link.classList.remove('is-active');
                            }
                        });
                    }
                });
            }, { rootMargin: '0px 0px -65% 0px' });

            headings.forEach(function (h) {
                observer.observe(h);
            });
        }

        /* ── 5. FEEDBACK VOTING ── */
        var voteBtns = document.querySelectorAll('.docs-btn-vote');
        voteBtns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var box = btn.closest('.docs-feedback-box');
                if (!box) return;
                var actions = box.querySelector('.docs-feedback-actions');
                var thanks = box.querySelector('.docs-feedback-thankyou');
                if (actions) actions.setAttribute('hidden', 'true');
                if (thanks) thanks.removeAttribute('hidden');
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDocs);
    } else {
        initDocs();
    }
})();
