import { registerPage, start } from "./app.js";
import { renderRun } from "./pages/run.js";

registerPage("run", renderRun);
start();
