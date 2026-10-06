// n8n theme starts in dark mode. Users can switch to light/system in the account menu;
// that choice is kept by Unfold in localStorage ("adminTheme"). The marker makes the
// dark default apply once, also for browsers that remembered another theme's default.
try {
    if (localStorage.getItem("ctbThemeDefault") !== "n8n-dark") {
        localStorage.setItem("adminTheme", JSON.stringify("dark"));
        localStorage.setItem("ctbThemeDefault", "n8n-dark");
    }
} catch (e) {
    // Storage blocked (private mode): fall back to the system setting.
}
