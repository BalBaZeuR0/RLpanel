import { registerPage, start } from "./app.js";
import { renderCompare } from "./pages/compare.js";
import { renderRun } from "./pages/run.js";

registerPage("run", renderRun);
registerPage("compare", renderCompare);
start();
