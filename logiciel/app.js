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
  document.getElementById('demoBtn').onclick = () => document.getElementById('demoDialog').showModal();
  document.getElementById('minBtn').onclick = () => api().minimize();
  document.getElementById('maxBtn').onclick = () => api().toggle_maximize();
  document.getElementById('closeBtn').onclick = () => api().close_window();
  document.getElementById('folderScope').onchange = () => runSearch(document.getElementById('searchInput').value);
  document.getElementById('yesBtn').onclick = () => document.getElementById('feedbackText').textContent = 'Parfait, vous pouvez ouvrir votre fichier.';
  document.getElementById('noBtn').onclick = () => {document.getElementById('refineHelp').hidden = false; document.getElementById('folderScope').focus();};
  document.getElementById('pickScopeBtn').onclick = async () => {
    const path = await api().pick_folder(); if (!path) return;
    const scope=document.getElementById('folderScope');
    if (![...scope.options].some(o=>o.value===path)) {const o=document.createElement('option');o.value=path;o.textContent=path;scope.appendChild(o);}
    scope.value=path;runSearch(document.getElementById('searchInput').value);
  };
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
      "Détection avancée des doublons : à venir",
      "Comparaison par contenu (pas seulement le nom)",
      "Suppression groupée avec validation",
    ],
  },
  ranger: {
    title: "Un classement automatique, sans effort.",
    bullets: [
      "Analyse du rangement : à venir",
      "Suggestions de rangement par dossier",
      "Renommage intelligent en un clic",
    ],
  },
  nettoyage: {
    title: "Le nettoyage sera disponible plus tard.",
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
      renderCustomFolders();
    }
  });
}

function renderCustomFolders() {
  const wrap=document.getElementById('customFoldersLabel');wrap.innerHTML='';
  state.customFolders=[...new Set(state.customFolders)];
  state.customFolders.forEach(path=>{const button=document.createElement('button');button.className='btn-mini';button.textContent=path+' ×';button.title='Retirer ce dossier de la prochaine analyse';button.onclick=()=>{state.customFolders=state.customFolders.filter(p=>p!==path);renderCustomFolders();};wrap.appendChild(button);});
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
  document.getElementById("stopBtn").addEventListener("click", async () => {
    await api().stop_scan();
    setStatus("Arrêt en cours… Les fichiers déjà lus resteront disponibles.");
  });
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
    document.getElementById("stopBtn").hidden = false;
    document.getElementById("pdfReport").hidden = true;
    try {
      if (!await api().start_scan(roots)) window.onScanError("Une analyse est déjà en cours ou la sélection est invalide.");
    } catch (_) { window.onScanError("Impossible de démarrer l’analyse. Réessayez."); }
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
    `${result.cancelled ? "Analyse arrêtée" : "Analyse terminée"} : ${result.total_files} fichiers, ${result.total_size_human} — ` +
    `${result.content_indexed_count} fichiers indexés en contenu.`
  );

  document.getElementById("stopBtn").hidden = true;
  const report = document.getElementById("pdfReport");
  report.hidden = false;
  report.textContent = `${result.pdf_read || 0} PDF lus, dont ${result.pdf_ocr || 0} par OCR local. ` +
    `${result.pdf_unread || 0} PDF sans contenu lisible ; ${result.pdf_partial || 0} partiellement lus. ` +
    `${result.errors || 0} élément(s) inaccessible(s) ou non disponible(s) localement.`;
  for (const issue of result.pdf_issues || []) {
    const line = document.createElement("div");
    line.textContent = `${issue.name} : ${issue.status}`;
    line.title = [issue.path, ...(issue.details || [])].join("\n");
    report.appendChild(line);
  }
  document.getElementById("statFiles").textContent = result.total_files;
  document.getElementById("statPdf").textContent = result.counts.pdf || 0;
  document.getElementById("statImages").textContent = result.counts.images || 0;
  document.getElementById("statSize").textContent = result.total_size_human;

  setFilterLabel("tous", `Tous (${result.total_files})`);
  setFilterLabel("pdf", `PDF (${result.counts.pdf || 0})`);
  setFilterLabel("image", `Images (${result.counts.images || 0})`);
  setFilterLabel("doc", `Documents (${result.counts.documents || 0})`);

  const scope = document.getElementById('folderScope');
  scope.innerHTML = '<option value="">Tous les dossiers analysés</option>';
  (result.roots || []).forEach(path => {const option=document.createElement('option'); option.value=path; option.textContent=path; scope.appendChild(option);});
  const q = document.getElementById("searchInput").value.trim();
  if (q) runSearch(q);
  else runSearch("");
};

window.onScanError = function(message) {
  state.scanning = false;
  const button = document.getElementById("analyzeBtn");
  button.disabled = false;
  button.textContent = "Relancer l’analyse";
  document.getElementById("stopBtn").hidden = true;
  document.getElementById("progressTrack").hidden = true;
  setStatus(message);
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
  if (query !== state.lastQuery && /\b(photos?|images?)\b/i.test(query || '')) {
    state.typeFilter='image';
    document.querySelectorAll('.chip-filter').forEach(c => c.classList.toggle('active', c.dataset.key === 'image'));
  } else if (query !== state.lastQuery && /\bpdfs?\b/i.test(query || '')) {
    state.typeFilter='pdf';
    document.querySelectorAll('.chip-filter').forEach(c => c.classList.toggle('active', c.dataset.key === 'pdf'));
  }
  state.lastQuery = query || "";
  if (!state.hasScanned) {
    document.getElementById("resultsCount").textContent = "Lancez d'abord une analyse pour pouvoir rechercher.";
    renderResults([], query);
    return;
  }
  const requestId = state.requestId = (state.requestId || 0) + 1;
  const resultJson = await api().search(query || "", state.typeFilter, document.getElementById("folderScope").value);
  if (requestId !== state.requestId) return;
  const { matches, count_label } = JSON.parse(resultJson);
  document.getElementById("resultsCount").textContent = count_label;
  renderResults(matches, query);
}

function renderResults(matches, query) {
  const list = document.getElementById("resultsList");
  list.innerHTML = "";
  document.getElementById('feedback').hidden = !query || !state.hasScanned;
  document.getElementById('refineHelp').hidden = !!matches.length;
  if (!matches || matches.length === 0) {
    const msg = query && query.trim() ? `Aucun résultat pour « ${escapeHtml(query)} ».` : "Lancez une recherche pour voir vos fichiers.";
    list.innerHTML = `<div class="empty-state">${msg}<p>Essayez un fournisseur ou moins de mots. Vérifiez que le dossier du PDF est sélectionné, puis relancez l’analyse. Le bilan PDF signale les documents non lisibles.</p></div>`;
    return;
  }
  document.getElementById('feedback').hidden = !query;
  document.getElementById('refineHelp').hidden = !!matches.length;
  document.getElementById('feedbackText').textContent = 'Ces résultats vous conviennent-ils ?';
  matches.forEach((entry, index) => {
    const row = document.createElement("div");
    row.className = "result-row" + (index === 0 && query.trim() ? " best-match" : "");
    row.innerHTML = `
      <div class="result-badge" style="background:${entry.badge_color}">${escapeHtml(entry.badge_label)}</div>
      <div class="result-body">
        ${index === 0 && query.trim() ? '<div class="best-label">★ Meilleure correspondance parmi les résultats</div>' : ""}<div class="result-title-row">
          <span class="result-name">${escapeHtml(entry.name)}</span>
          ${entry.badly_named ? '<span class="result-badly-named">nom peu explicite</span>' : ""}
        </div>
        ${entry.snippet ? `<div class="result-snippet">« ${escapeHtml(entry.snippet)} »</div>` : ""}
        <div class="result-meta">${escapeHtml(entry.read_status || "")}${entry.page ? ` · Page ${entry.page}` : ""}${entry.method === "OCR" ? " · Texte reconnu par OCR" : ""}</div>
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
