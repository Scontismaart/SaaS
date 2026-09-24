/**
 * Melpis — Client-Side i18n Controller & Localization Engine
 * Seamless integration with i18next, native Intl APIs, and DOM data-i18n bindings.
 */
(function (global) {
  'use strict';

  var SUPPORTED_LANGS = ['it', 'en', 'es', 'fr', 'de'];
  var DEFAULT_LANG = 'it';
  var STORAGE_KEY = 'melpis_lang';
  var COOKIE_NAME = 'melpis_lang';
  var BUNDLE_VERSION = 'pr38-dashboard-language';

  var LOCALE_MAP = {
    it: 'it-IT',
    en: 'en-GB',
    es: 'es-ES',
    fr: 'fr-FR',
    de: 'de-DE',
    pseudo: 'qps-ploc'
  };

  var loadedBundles = {};
  var currentLang = DEFAULT_LANG;
  var isInitialized = false;

  // Pseudo-localization transformer for dev/layout stress-testing
  var PSEUDO_MAP = {
    a: 'àà', e: 'éé', i: 'îî', o: 'ôô', u: 'ûû',
    A: 'ÀÀ', E: 'ÉÉ', I: 'ÎÎ', O: 'ÔÔ', U: 'ÛÛ',
    c: 'ç', d: 'đ', n: 'ñ', s: 'š', z: 'ž'
  };

  function toPseudo(text) {
    if (typeof text !== 'string') return text;
    var transformed = text.replace(/[aeiouAEIOUcdnz]/g, function (ch) {
      return PSEUDO_MAP[ch] || ch;
    });
    return '[' + transformed + ' !!!]';
  }

  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
  }

  function setCookie(name, value, days) {
    var expires = '';
    if (days) {
      var date = new Date();
      date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
      expires = '; expires=' + date.toUTCString();
    }
    document.cookie = name + '=' + encodeURIComponent(value) + '; path=/; SameSite=Lax' + expires;
  }

  function detectLanguage() {
    // 1. Explicit override from URL query (for testing/debug)
    var urlParams = new URLSearchParams(window.location.search);
    var langParam = urlParams.get('lang');
    if (langParam === 'pseudo') return 'pseudo';
    if (langParam && SUPPORTED_LANGS.indexOf(langParam.toLowerCase()) !== -1) {
      return langParam.toLowerCase();
    }

    // 2. Saved preference in localStorage
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'pseudo') return 'pseudo';
      if (saved && SUPPORTED_LANGS.indexOf(saved.toLowerCase()) !== -1) {
        return saved.toLowerCase();
      }
    } catch (e) {
      // localStorage may fail in restricted iframes or privacy modes
    }

    // 3. Saved cookie
    var cookieLang = getCookie(COOKIE_NAME);
    if (cookieLang && SUPPORTED_LANGS.indexOf(cookieLang.toLowerCase()) !== -1) {
      return cookieLang.toLowerCase();
    }

    // 4. Browser navigator.language
    var navLang = (navigator.language || navigator.userLanguage || '').toLowerCase().split('-')[0];
    if (SUPPORTED_LANGS.indexOf(navLang) !== -1) {
      return navLang;
    }

    // 5. Default fallback
    return DEFAULT_LANG;
  }

  function loadNamespace(lang, ns) {
    var targetLang = (lang === 'pseudo') ? 'it' : lang;
    if (loadedBundles[targetLang] && loadedBundles[targetLang][ns]) {
      return Promise.resolve(loadedBundles[targetLang][ns]);
    }

    var basePath = '/locales/' + targetLang + '/' + ns + '.json?v=' + BUNDLE_VERSION;
    return fetch(basePath)
      .then(function (res) {
        if (!res.ok) throw new Error('Cannot fetch ' + basePath + ' (' + res.status + ')');
        return res.json();
      })
      .then(function (data) {
        if (!loadedBundles[targetLang]) loadedBundles[targetLang] = {};
        loadedBundles[targetLang][ns] = data;

        if (global.i18next && global.i18next.isInitialized) {
          global.i18next.addResourceBundle(targetLang, ns, data, true, true);
        }
        return data;
      })
      .catch(function (err) {
        console.warn('[MelpisI18n] Failed loading ' + basePath, err);
        return {};
      });
  }

  function loadAllNamespaces(lang, namespaces) {
    var promises = namespaces.map(function (ns) {
      return loadNamespace(lang, ns);
    });
    return Promise.all(promises);
  }

  function parseKey(key) {
    if (!key) return { ns: 'common', path: '' };
    var parts = key.split(':');
    if (parts.length > 1) {
      return { ns: parts[0], path: parts[1] };
    }
    var dotIdx = key.indexOf('.');
    if (dotIdx !== -1) {
      var prefix = key.substring(0, dotIdx);
      if (['common', 'dashboard', 'inbox', 'settings', 'errors', 'pricing', 'auth'].indexOf(prefix) !== -1) {
        return { ns: prefix, path: key.substring(dotIdx + 1) };
      }
    }
    return { ns: 'common', path: key };
  }

  function translate(key, options) {
    options = options || {};
    var count = options.count;
    var defaultValue = options.defaultValue;

    var parsed = parseKey(key);
    var ns = parsed.ns;
    var path = parsed.path;

    if (currentLang === 'pseudo') {
      var baseText = (global.i18next && global.i18next.isInitialized)
        ? (global.i18next.t(ns + ':' + path, Object.assign({}, options, { lng: 'it' })) || global.i18next.t(key, Object.assign({}, options, { lng: 'it' })))
        : (defaultValue || key);
      return toPseudo(baseText);
    }

    if (global.i18next && global.i18next.isInitialized) {
      var res = global.i18next.t(ns + ':' + path, options);
      if (res && res !== path && res !== (ns + ':' + path)) return res;
      res = global.i18next.t(key, options);
      if (res && res !== path && res !== key && res !== (ns + ':' + path)) return res;
    }

    // Fallback directly to in-memory bundles if i18next is pending or key missing
    var bundle = (loadedBundles[currentLang] && loadedBundles[currentLang][ns]) ||
                 (loadedBundles[DEFAULT_LANG] && loadedBundles[DEFAULT_LANG][ns]);
    if (bundle) {
      var keys = path.split('.');
      var curr = bundle;
      for (var i = 0; i < keys.length; i++) {
        if (curr && typeof curr === 'object' && keys[i] in curr) {
          curr = curr[keys[i]];
        } else {
          curr = null;
          break;
        }
      }
      if (typeof curr === 'string') {
        // Basic interpolation if any
        return curr.replace(/\{\{\s*(\w+)\s*\}\}/g, function (_, k) {
          return options[k] !== undefined ? options[k] : '{{' + k + '}}';
        });
      }
    }

    return defaultValue !== undefined ? defaultValue : key;
  }

  function updateDomTranslations(root) {
    root = root || document;

    // 1. Text content
    var textElements = root.querySelectorAll('[data-i18n]');
    for (var i = 0; i < textElements.length; i++) {
      var el = textElements[i];
      var key = el.getAttribute('data-i18n');
      if (key) {
        var translated = translate(key);
        if (translated) {
          el.textContent = translated;
        }
      }
    }

    // 2. Placeholders
    var placeholderElements = root.querySelectorAll('[data-i18n-placeholder]');
    for (var j = 0; j < placeholderElements.length; j++) {
      var pEl = placeholderElements[j];
      var pKey = pEl.getAttribute('data-i18n-placeholder');
      if (pKey) {
        var pTrans = translate(pKey);
        if (pTrans) pEl.setAttribute('placeholder', pTrans);
      }
    }

    // 3. Titles / Tooltips
    var titleElements = root.querySelectorAll('[data-i18n-title]');
    for (var k = 0; k < titleElements.length; k++) {
      var tEl = titleElements[k];
      var tKey = tEl.getAttribute('data-i18n-title');
      if (tKey) {
        var tTrans = translate(tKey);
        if (tTrans) tEl.setAttribute('title', tTrans);
      }
    }

    // 4. Aria-labels
    var ariaElements = root.querySelectorAll('[data-i18n-aria]');
    for (var m = 0; m < ariaElements.length; m++) {
      var aEl = ariaElements[m];
      var aKey = aEl.getAttribute('data-i18n-aria');
      if (aKey) {
        var aTrans = translate(aKey);
        if (aTrans) aEl.setAttribute('aria-label', aTrans);
      }
    }
  }

  function setLanguage(lang) {
    if (SUPPORTED_LANGS.indexOf(lang) === -1 && lang !== 'pseudo') {
      console.warn('[MelpisI18n] Unsupported language: ' + lang);
      return Promise.reject(new Error('Unsupported language'));
    }

    currentLang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {}
    setCookie(COOKIE_NAME, lang, 365);

    document.documentElement.lang = (lang === 'pseudo') ? 'it' : lang;

    var namespaces = ['common', 'dashboard', 'inbox', 'settings', 'errors', 'pricing', 'auth'];
    return loadAllNamespaces(lang, namespaces).then(function () {
      if (global.i18next && global.i18next.isInitialized) {
        return global.i18next.changeLanguage((lang === 'pseudo') ? 'it' : lang);
      }
    }).then(function () {
      updateDomTranslations();
      ['sidebar-lang-select', 'settings-lang-select'].forEach(function (id) {
        var selectEl = typeof document !== 'undefined' ? document.getElementById(id) : null;
        if (selectEl && selectEl.value !== lang) selectEl.value = lang;
      });
      // Dispatch custom event so app.js can re-render dynamic tables/charts
      var evt = new CustomEvent('melpis:lang-changed', {
        detail: {
          language: lang,
          locale: LOCALE_MAP[lang] || LOCALE_MAP[DEFAULT_LANG]
        }
      });
      window.dispatchEvent(evt);
      return lang;
    });
  }

  function init(options) {
    options = options || {};
    var namespaces = options.namespaces || ['common', 'dashboard', 'inbox', 'settings', 'errors', 'pricing', 'auth'];
    var initialLang = detectLanguage();

    currentLang = initialLang;
    if (typeof document !== 'undefined') {
      document.documentElement.lang = (initialLang === 'pseudo') ? 'it' : initialLang;
      // Bind both language controls before fetching bundles so a quick choice
      // during initial loading is never lost.
      ['sidebar-lang-select', 'settings-lang-select'].forEach(function (id) {
        var selectEl = document.getElementById(id);
        if (!selectEl) return;
        selectEl.value = initialLang;
        if (!selectEl.dataset.i18nBound) {
          selectEl.dataset.i18nBound = 'true';
          selectEl.addEventListener('change', function () {
            setLanguage(this.value).catch(function (err) {
              console.warn('[MelpisI18n] Language change failed', err);
            });
          });
        }
      });
    }

    // Load initial bundles
    return loadAllNamespaces(initialLang, namespaces)
      .then(function () {
        var effectiveLang = currentLang;
        if (!loadedBundles[effectiveLang === 'pseudo' ? 'it' : effectiveLang]) {
          return loadAllNamespaces(effectiveLang, namespaces).then(function () { return effectiveLang; });
        }
        return effectiveLang;
      })
      .then(function (effectiveLang) {
        if (effectiveLang !== DEFAULT_LANG && effectiveLang !== 'pseudo') {
          // Always preload default language for instantaneous fallback
          loadAllNamespaces(DEFAULT_LANG, namespaces);
        }

        if (global.i18next) {
          var resources = {};
          var targetLang = (effectiveLang === 'pseudo') ? 'it' : effectiveLang;
          resources[targetLang] = loadedBundles[targetLang] || {};
          if (loadedBundles[DEFAULT_LANG]) {
            resources[DEFAULT_LANG] = loadedBundles[DEFAULT_LANG];
          }

          return global.i18next.init({
            lng: targetLang,
            fallbackLng: DEFAULT_LANG,
            debug: false,
            ns: namespaces,
            defaultNS: 'common',
            resources: resources,
            interpolation: {
              escapeValue: false
            }
          });
        }
      })
      .then(function () {
        isInitialized = true;
        updateDomTranslations();
        if (typeof document !== 'undefined') {
          ['sidebar-lang-select', 'settings-lang-select'].forEach(function (id) {
            var selectEl = document.getElementById(id);
            if (selectEl) selectEl.value = currentLang;
          });
        }
        return currentLang;
      });
  }

  /* ── Native Intl Formatting Helpers ── */
  function getLocale() {
    return LOCALE_MAP[currentLang] || LOCALE_MAP[DEFAULT_LANG];
  }

  function formatDate(date, options) {
    if (!date) return '';
    var d = (date instanceof Date) ? date : new Date(date);
    if (isNaN(d.getTime())) return '';
    options = options || { day: '2-digit', month: '2-digit', year: 'numeric' };
    return new Intl.DateTimeFormat(getLocale(), options).format(d);
  }

  function formatTime(date, options) {
    if (!date) return '';
    var d = (date instanceof Date) ? date : new Date(date);
    if (isNaN(d.getTime())) return '';
    options = options || { hour: '2-digit', minute: '2-digit' };
    return new Intl.DateTimeFormat(getLocale(), options).format(d);
  }

  function formatDateTime(date, options) {
    if (!date) return '';
    var d = (date instanceof Date) ? date : new Date(date);
    if (isNaN(d.getTime())) return '';
    options = options || {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    };
    return new Intl.DateTimeFormat(getLocale(), options).format(d);
  }

  function formatCurrency(amount, currency) {
    currency = currency || 'EUR';
    var num = (typeof amount === 'number') ? amount : parseFloat(amount) || 0;
    return new Intl.NumberFormat(getLocale(), {
      style: 'currency',
      currency: currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(num);
  }

  function formatNumber(num, options) {
    var val = (typeof num === 'number') ? num : parseFloat(num) || 0;
    return new Intl.NumberFormat(getLocale(), options).format(val);
  }

  // Export to global window
  global.MelpisI18n = {
    init: init,
    t: translate,
    setLanguage: setLanguage,
    getLanguage: function () { return currentLang; },
    getLocale: getLocale,
    updateDom: updateDomTranslations,
    formatDate: formatDate,
    formatTime: formatTime,
    formatDateTime: formatDateTime,
    formatCurrency: formatCurrency,
    formatNumber: formatNumber,
    SUPPORTED_LANGS: SUPPORTED_LANGS,
    DEFAULT_LANG: DEFAULT_LANG
  };

  // Shortcut alias
  global.t = translate;

  // Auto-initialize when running in browser
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        init();
      });
    } else {
      init();
    }
  }

})(typeof window !== 'undefined' ? window : this);
