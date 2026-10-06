// Cursor theme starts in light mode. Users can switch to dark/system in the account menu;
// that choice is kept by Unfold in localStorage ("adminTheme"). The marker makes the
// light default apply once, also for browsers that remembered another theme's default.
try {
    if (localStorage.getItem("ctbThemeDefault") !== "cursor-light") {
        localStorage.setItem("adminTheme", JSON.stringify("light"));
        localStorage.setItem("ctbThemeDefault", "cursor-light");
    }
} catch (e) {
    // Storage blocked (private mode): fall back to the system setting.
}
