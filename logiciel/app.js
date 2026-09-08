/* Frontend logic — communique avec le backend Python via pywebview.api.* */

const state = {
  knownFolders: {},        // label -> path
  customFolders: [],
  typeFilter: "tous",
  lastQuery: "",
  hasScanned: false,
  scanning: false,
};

function api() { return window.pywebview && window.pywebview.api; }

// -------------------- Attente que le pont pywebview soit prêt --------------------
function whenReady(cb) {
  if (window.pywebview) { cb(); return; }
  window.addEventListener("pywebviewready", cb, { once: true });
}

whenReady(init);

async function init() {
  bindNav();
  bindSettingsToggle();
  bindSearch();
  bindFilters();
  bindAddFolder();
  bindAnalyze();

  const folders = await api().get_known_folders();
  state.knownFolders = folders;
  renderFolderChecks();
}

// -------------------- Navigation --------------------
function bindNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-content").forEach((el) => (el.hidden = true));
      const map = { recherche: "tabRecherche", doublons: "tabDoublons", ranger: "tabRanger", nettoyage: "tabNettoyage" };
      const el = document.getElementById(map[tab]);
      el.hidden = false;
      if (tab !== "recherche" && !el.dataset.built) {
        buildLockedTab(tab, el);
        el.dataset.built = "1";
      }
    });
  });
}

const LOCKED_TABS = {
  doublons: {
    title: "Libérez de l'espace en un clic.",
    bullets: [
      "3 751 doublons potentiels détectés",
      "Comparaison par contenu (pas seulement le nom)",
      "Suppression groupée avec validation",
    ],
  },
  ranger: {
    title: "Un classement automatique, sans effort.",
    bullets: [
      "1 858 fichiers mal nommés ou mal classés",
      "Suggestions de rangement par dossier",
      "Renommage intelligent en un clic",
    ],
  },
  nettoyage: {
    title: "Libérez 3,7 Go d'espace disque.",
    bullets: [
      "Fichiers temporaires et caches oubliés",
      "Doublons volumineux repérés",
      "Rien n'est supprimé sans accord",
    ],
  },
};

function buildLockedTab(key, el) {
  const info = LOCKED_TABS[key];
  el.innerHTML = `
    <h2>${info.title}</h2>
    <ul>${info.bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
    <button class="btn btn-pro">Passer à Retrio Pro</button>
  `;
}

// -------------------- Réglages / dossiers --------------------
function bindSettingsToggle() {
  const toggle = document.getElementById("settingsToggle");
  const panel = document.getElementById("settingsPanel");
  toggle.addEventListener("click", () => {
    const collapsed = toggle.classList.toggle("collapsed");
    panel.hidden = collapsed;
  });
}

function renderFolderChecks() {
  const wrap = document.getElementById("folderChecks");
  wrap.innerHTML = "";
  Object.keys(state.knownFolders).forEach((label) => {
    const id = "chk_" + label.replace(/[^a-zA-Z0-9]/g, "_");
    const checked = label === "Documents" || label === "Téléchargements";
    const row = document.createElement("div");
    row.className = "folder-check";
    row.innerHTML = `<input type="checkbox" id="${id}" ${checked ? "checked" : ""}><label for="${id}">${escapeHtml(label)}</label>`;
    wrap.appendChild(row);
  });
}

function bindAddFolder() {
  document.getElementById("addFolderBtn").addEventListener("click", async () => {
    const path = await api().pick_folder();
    if (path) {
      state.customFolders.push(path);
      document.getElementById("customFoldersLabel").textContent =
        `${state.customFolders.length} dossier(s) personnalisé(s) ajouté(s)`;
    }
  });
}

function selectedRoots() {
  const roots = [];
  Object.keys(state.knownFolders).forEach((label) => {
    const id = "chk_" + label.replace(/[^a-zA-Z0-9]/g, "_");
    const cb = document.getElementById(id);
    if (cb && cb.checked) roots.push(state.knownFolders[label]);
  });
  return [...new Set([...roots, ...state.customFolders])];
}

// -------------------- Analyse --------------------
function bindAnalyze() {
  document.getElementById("analyzeBtn").addEventListener("click", async () => {
    if (state.scanning) return;
    const roots = selectedRoots();
    if (roots.length === 0) {
      setStatus("Sélectionnez au moins un dossier avant de lancer l'analyse.");
      return;
    }
    state.scanning = true;
    const btn = document.getElementById("analyzeBtn");
    btn.disabled = true;
    btn.textContent = "Analyse en cours…";
    document.getElementById("progressTrack").hidden = false;
    setStatus("Analyse en cours (lecture du contenu des documents)…");
    await api().start_scan(roots);
  });
}

// Appelé depuis Python (window.evaluate_js) pendant le scan
window.onScanProgress = function (nFiles, currentPath) {
  const shown = currentPath.length < 60 ? currentPath : "…" + currentPath.slice(-57);
  setStatus(`${nFiles} fichiers analysés — ${shown}`);
};

// Appelé depuis Python à la fin du scan, avec le résumé JSON
window.onScanDone = function (resultJson) {
  const result = JSON.parse(resultJson);
  state.scanning = false;
  state.hasScanned = true;

  document.getElementById("progressTrack").hidden = true;
  const btn = document.getElementById("analyzeBtn");
  btn.disabled = false;
  btn.textContent = "▶  Relancer l'analyse";

  setStatus(
    `Analyse terminée : ${result.total_files} fichiers, ${result.total_size_human} — ` +
    `${result.content_indexed_count} fichiers indexés en contenu.`
  );

  document.getElementById("statFiles").textContent = result.total_files;
  document.getElementById("statPdf").textContent = result.counts.pdf || 0;
  document.getElementById("statImages").textContent = result.counts.images || 0;
  document.getElementById("statSize").textContent = result.total_size_human;

  setFilterLabel("tous", `Tous (${result.total_files})`);
  setFilterLabel("pdf", `PDF (${result.counts.pdf || 0})`);
  setFilterLabel("image", `Images (${result.counts.images || 0})`);
  setFilterLabel("doc", `Documents (${result.counts.documents || 0})`);

  // Replie le panneau réglages une fois l'analyse faite
  const toggle = document.getElementById("settingsToggle");
  if (!toggle.classList.contains("collapsed")) toggle.click();

  const q = document.getElementById("searchInput").value.trim();
  if (q) runSearch(q);
  else runSearch("");
};

function setStatus(text) {
  document.getElementById("statusText").textContent = text;
}
function setFilterLabel(key, label) {
  const chip = document.querySelector(`.chip-filter[data-key="${key}"]`);
  if (chip) chip.textContent = label;
}

// -------------------- Recherche --------------------
function bindSearch() {
  const input = document.getElementById("searchInput");
  document.getElementById("searchBtn").addEventListener("click", () => runSearch(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch(input.value);
  });
  document.querySelectorAll(".chip-suggest").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.q;
      runSearch(chip.dataset.q);
    });
  });
}

function bindFilters() {
  document.querySelectorAll(".chip-filter").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip-filter").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.typeFilter = chip.dataset.key;
      runSearch(document.getElementById("searchInput").value);
    });
  });
}

async function runSearch(query) {
  state.lastQuery = query || "";
  if (!state.hasScanned) {
    document.getElementById("resultsCount").textContent = "Lancez d'abord une analyse pour pouvoir rechercher.";
    renderResults([], query);
    return;
  }
  const resultJson = await api().search(query || "", state.typeFilter);
  const { matches, count_label } = JSON.parse(resultJson);
  document.getElementById("resultsCount").textContent = count_label;
  renderResults(matches, query);
}

function renderResults(matches, query) {
  const list = document.getElementById("resultsList");
  list.innerHTML = "";
  if (!matches || matches.length === 0) {
    const msg = query && query.trim() ? `Aucun résultat pour « ${escapeHtml(query)} ».` : "Lancez une recherche pour voir vos fichiers.";
    list.innerHTML = `<div class="empty-state">${msg}</div>`;
    return;
  }
  matches.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "result-row";
    row.innerHTML = `
      <div class="result-badge" style="background:${entry.badge_color}">${escapeHtml(entry.badge_label)}</div>
      <div class="result-body">
        <div class="result-title-row">
          <span class="result-name">${escapeHtml(entry.name)}</span>
          ${entry.badly_named ? '<span class="result-badly-named">nom peu explicite</span>' : ""}
        </div>
        ${entry.snippet ? `<div class="result-snippet">« ${escapeHtml(entry.snippet)} »</div>` : ""}
        <div class="result-meta">${escapeHtml(entry.dir)} · ${escapeHtml(entry.size_human)}</div>
        <div class="result-actions">
          <button class="btn-mini" data-act="open">Ouvrir</button>
          <button class="btn-mini" data-act="folder">Dossier</button>
          <button class="btn-mini" data-act="copy">Copier le chemin</button>
        </div>
      </div>
    `;
    row.querySelector('[data-act="open"]').addEventListener("click", () => api().open_path(entry.path));
    row.querySelector('[data-act="folder"]').addEventListener("click", () => api().open_folder(entry.path));
    row.querySelector('[data-act="copy"]').addEventListener("click", () => api().copy_path(entry.path));
    list.appendChild(row);
  });
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str == null ? "" : String(str);
  return d.innerHTML;
}
