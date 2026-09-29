/* Apply the existing Melpis theme preference before the dashboard stylesheet paints. */
(() => {
  try {
    const preference = localStorage.getItem("melpis_theme") || "dark";
    const systemIsDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = preference === "light" || (preference === "system" && !systemIsDark)
      ? "light"
      : "dark";
  } catch {
    document.documentElement.dataset.theme = "dark";
  }
})();
