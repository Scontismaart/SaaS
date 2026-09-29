(function () {
  'use strict';

  class BrandLogo extends HTMLElement {
    connectedCallback() {
      this.render();
    }

    render() {
      const variant = this.getAttribute('variant') || 'horizontal';
      const requestedTheme = this.getAttribute('theme') || 'dark';
      const theme = requestedTheme === 'auto'
        ? (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
        : requestedTheme;
      const size = this.getAttribute('size') || 'md';
      const symbol = this.getAttribute('symbol') || 'metallic';
      const label = this.getAttribute('label') || 'Melpis';
      const src = symbol === 'white'
        ? '/brand/melpis-symbol-mono-white.svg'
        : symbol === 'black'
          ? '/brand/melpis-symbol-mono-black.svg'
          : theme === 'light'
            ? '/brand/melpis-symbol-light.svg'
            : '/brand/melpis-symbol-dark.svg';

      this.className = `brand-logo brand-logo--${variant} brand-logo--${size} brand-logo--${theme}`;
      this.setAttribute('role', 'img');
      this.setAttribute('aria-label', label);
      this.replaceChildren();

      const mark = document.createElement('img');
      mark.className = 'brand-logo__symbol';
      mark.src = src;
      mark.alt = '';
      mark.setAttribute('aria-hidden', 'true');
      mark.width = 40;
      mark.height = 30;
      this.append(mark);

      if (variant !== 'symbol') {
        const wordmark = document.createElement('span');
        wordmark.className = 'brand-logo__wordmark';
        wordmark.textContent = 'melpis';
        this.append(wordmark);
      }
    }
  }

  if (!customElements.get('brand-logo')) customElements.define('brand-logo', BrandLogo);

  new MutationObserver(() => {
    document.querySelectorAll('brand-logo[theme="auto"]').forEach((logo) => logo.render());
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
})();
