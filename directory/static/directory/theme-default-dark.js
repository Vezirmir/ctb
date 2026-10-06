// Start in dark mode until the user picks light/dark/system in the theme switch.
// Unfold keeps the choice in localStorage under the "adminTheme" key.
try {
    if (localStorage.getItem("adminTheme") === null) {
        localStorage.setItem("adminTheme", JSON.stringify("dark"));
    }
} catch (e) {
    // Storage blocked (private mode): fall back to the system setting.
}
