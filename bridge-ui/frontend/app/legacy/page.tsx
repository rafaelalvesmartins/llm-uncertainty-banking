// Legacy dashboard preserved at /legacy.
//
// The unified console now serves "/" (see next.config.js rewrite). The legacy
// app component still lives in app/page.tsx; this route re-exports it so the
// older feature breadth (and its e2e suite) stays reachable while the console
// converges. Remove this route once the legacy panels are fully retired.
export { default } from "../page";
