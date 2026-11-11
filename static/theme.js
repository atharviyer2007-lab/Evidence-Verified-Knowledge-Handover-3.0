(function () {
  var theme;
  try { theme = localStorage.getItem("theme"); } catch (error) { theme = null; }
  if (!theme) { theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
  document.documentElement.dataset.theme = theme;
})();
