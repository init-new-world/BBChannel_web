import { t } from "./i18n.js";

export function createPresetDropEditor({ getEditor, source, request, onChange, onError }) {
  const section = document.querySelector("#preset-drop-options");
  const controls = document.querySelector("#preset-drop-controls");
  const picker = document.querySelector("#preset-drop-image");
  const refresh = document.querySelector("#refresh-drop-templates");
  const preview = document.querySelector("#preset-drop-preview");
  const status = document.querySelector("#preset-drop-status");
  const previewStatus = document.querySelector("#preset-drop-preview-status");

  function readConfig() {
    const config = JSON.parse(source.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error(t("Invalid script JSON."));
    return config;
  }

  async function loadCatalog(editor, catalog, reload) {
    try {
      if (reload) await request("/api/template-index/refresh", { method: "POST" });
      const query = typeof catalog.configured === "string" ? `?${new URLSearchParams({ configured: catalog.configured })}` : "";
      const payload = await request(`/api/drop-templates${query}`);
      if (!Array.isArray(payload.templates) || payload.templates.some((path) => typeof path !== "string" || !path.startsWith("drop/"))
          || (payload.resolved_path !== null && !payload.templates.includes(payload.resolved_path))) {
        throw new Error(t("Invalid drop catalog."));
      }
      catalog.paths = [...new Set(payload.templates)];
      catalog.resolved = payload.resolved_path;
      catalog.state = "ready";
    } catch (error) {
      catalog.state = "error";
      catalog.error = error.message || t("Drop catalog unavailable.");
    }
    if (getEditor() === editor && editor.dropCatalog === catalog) render();
  }

  function renderPreview(editor, path) {
    const current = preview.firstElementChild;
    if (current?.dataset.path === path) return;
    preview.replaceChildren();
    preview.hidden = !path;
    previewStatus.textContent = "";
    if (!path) return;
    const image = document.createElement("img");
    image.alt = "";
    image.width = 88;
    image.height = 96;
    image.dataset.path = path;
    image.src = `/api/drop-templates/image?${new URLSearchParams({ path })}`;
    image.addEventListener("error", () => {
      if (getEditor() === editor && preview.firstElementChild === image) {
        image.hidden = true;
        previewStatus.textContent = t("Preview unavailable");
      }
    });
    preview.append(image);
  }

  function render(reload = false) {
    const editor = getEditor();
    section.hidden = editor?.kind !== "settings";
    controls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
    if (editor?.kind !== "settings") return;
    if (!editor.dropsInitialized) {
      section.open = false;
      editor.dropsInitialized = true;
    }
    let config;
    try {
      config = readConfig();
    } catch {
      controls.disabled = true;
      status.textContent = t("Invalid script JSON.");
      return;
    }
    const configured = typeof config.dropImage === "string" ? config.dropImage : null;
    let catalog = editor.dropCatalog;
    if (!catalog || catalog.configured !== configured || reload) {
      catalog = { configured, state: "loading" };
      editor.dropCatalog = catalog;
      void loadCatalog(editor, catalog, reload);
    }
    const option = (value, label) => {
      const node = document.createElement("option");
      node.value = value;
      node.textContent = label;
      return node;
    };
    const paths = catalog.paths || [];
    const resolved = catalog.state === "ready" ? catalog.resolved : null;
    const choices = [option("", t("None")), ...paths.map((path) => option(path, path.slice(5)))];
    if (Object.hasOwn(config, "dropImage") && !resolved) {
      choices.push(option("__current__", t("{name} (current)", { name: JSON.stringify(config.dropImage) })));
    }
    picker.replaceChildren(...choices);
    picker.value = resolved || (Object.hasOwn(config, "dropImage") ? "__current__" : "");
    picker.title = picker.selectedOptions[0]?.textContent || "";
    refresh.disabled = catalog.state === "loading";
    status.textContent = catalog.state === "loading" ? t("Loading drop catalog...")
      : catalog.state === "error" ? catalog.error
        : Object.hasOwn(config, "dropImage") && !resolved ? t("Drop image unavailable or ambiguous.")
          : t("{count} drop templates", { count: paths.length });
    renderPreview(editor, resolved);
  }

  picker.addEventListener("change", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || editor.saving || editor.strategyApplyBusy) return;
    try {
      const config = readConfig();
      const value = picker.value;
      if (!value) delete config.dropImage;
      else if (editor.dropCatalog?.state === "ready" && editor.dropCatalog.paths.includes(value)) config.dropImage = value;
      else return;
      if (editor.dropCatalog?.state === "ready") {
        editor.dropCatalog.configured = value || null;
        editor.dropCatalog.resolved = value || null;
      }
      source.value = JSON.stringify(config, null, 2);
      onChange();
    } catch (error) {
      onError(error.message);
    }
  });
  refresh.addEventListener("click", () => {
    const editor = getEditor();
    if (editor?.kind !== "settings" || controls.disabled || refresh.disabled || editor.saving || editor.strategyApplyBusy) return;
    preview.replaceChildren();
    render(true);
  });
  return { render };
}
