/**
 * Public API surface. Every component imports from here, never from /src/mock.
 * Replacing this folder's internals with real `fetch` calls is the entire
 * backend integration — components stay untouched.
 */
export * from "./students";
export * from "./mentors";
export * from "./hod";
export * from "./admin";
export * from "./allocation";
export * from "./companion";
export * from "./session";
