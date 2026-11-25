// Light or dark, chosen by the person and remembered on this device. Pure logic, no app imports (tested with `node --test`).

export type Theme = "dark" | "light";

export const THEME_KEY = "seqnce:theme";
export const DEFAULT_THEME: Theme = "dark";
/** The colour of the phone's status bar: the page background of each theme (see globals.css). */
export const BAR_COLOR: Record<Theme, string> = { dark: "#0b0b10", light: "#f6f6f9" };

export const parseTheme = (raw: unknown): Theme => (raw === "light" || raw === "dark" ? raw : DEFAULT_THEME);

/**
 * Runs in <head> before the first paint, so a light-theme user never sees a dark flash. Plain old JavaScript on purpose.
 * Storage can be unavailable (private mode): the default theme is used then.
 */
export const THEME_SCRIPT = `(function(){var t="${DEFAULT_THEME}";try{var s=localStorage.getItem("${THEME_KEY}");if(s==="light"||s==="dark")t=s}catch(e){}document.documentElement.setAttribute("data-theme",t);if(t==="light"){var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content","${BAR_COLOR.light}")}})()`;
