/* Vérif Fournisseur — SaaS de démonstration.
 *
 * Parcours : on dépose une facture -> le CRM la lit (extraction déterministe) -> le CRM appelle le serveur MCP
 * (protocole MCP, outil traiter_factures_crm) -> le MCP vérifie et écrit son verdict -> un humain décide.
 *
 * - Aucune clé dans ce fichier : l'utilisateur la saisit, elle est gardée dans l'onglet (sessionStorage).
 *   Mode présentation (CRM_MODE_PRESENTATION=1, navigateur local) : le CRM accepte la page sans clé.
 * - Page « Pitch » : les diapositives de l'oral (8 min), avec deux démos en direct branchées sur le vrai MCP.
 * - Aucune règle de décision ici : verdicts, alertes et messages viennent du MCP ; les actions possibles du CRM.
 *   L'interface ne fait qu'afficher (et relier chaque code d'alerte au champ de la facture qu'il concerne).
 * - Tout est affiché en texte (textContent) : une facture piégée ne peut rien injecter dans la page.
 * - Montants : chaînes du serveur ; les totaux sont calculés en centimes entiers (BigInt), jamais en float.
 */
"use strict";

const CLE_STOCKAGE = "crm_cle_api";
const AUTO_STOCKAGE = "crm_analyse_auto";
const INTERVALLE_SUIVI_MS = 1500;
const VITESSES = [1, 2, 4];
const DUREES = { facture: 600, controle: 280, verdict: 700, pause: 1200 };
const STATUTS_VERDICT = ["bloquee", "a_verifier_humain", "verifiee", "impossible_de_verifier"];
const STATUTS_RETENUS = ["bloquee", "a_verifier_humain", "impossible_de_verifier"];

const VERDICTS = {
  bloquee: { titre: "Paiement bloqué", court: "Bloquée", forme: "carre", phrase: "Au moins un fait rend ce paiement anormal." },
  a_verifier_humain: { titre: "Contrôle humain", court: "Contrôle humain", forme: "triangle", phrase: "Un signal exige qu'une personne vérifie avant tout paiement." },
  verifiee: { titre: "Aucune alerte", court: "Aucune alerte", forme: "rond", phrase: "Rien d'anormal dans les sources : un humain peut payer." },
  impossible_de_verifier: { titre: "Impossible de vérifier", court: "Invérifiable", forme: "losange", phrase: "Une source officielle n'a pas répondu : le MCP ne conclut pas." },
  recue: { titre: "En attente", court: "Reçue", forme: "pointilles", phrase: "Pas encore analysée par le MCP." },
  payee: { titre: "Payée", court: "Payée", forme: "anneau", phrase: "Payée par un humain (simulé)." },
};
const SOUS_MONTANT = {
  bloquee: "retenus : le paiement ne part pas", a_verifier_humain: "retenus jusqu'au contrôle humain",
  impossible_de_verifier: "retenus : rien n'est conclu", verifiee: "payable après décision humaine",
};
const RESULTATS = { OK: { libelle: "OK", symbole: "✓" }, ALERTE: { libelle: "Alerte", symbole: "!" },
  INDISPONIBLE: { libelle: "Indisponible", symbole: "?" }, NON_DEMANDE: { libelle: "Non demandé", symbole: "–" } };
const NIVEAUX = { BLOQUANT: "Bloquant", A_VERIFIER: "À vérifier", INFO: "Info" };
const FORMES_NIVEAU = { BLOQUANT: "carre", A_VERIFIER: "triangle", INFO: "rond" };
const CONTROLES = {
  identifiants: "Identifiants : SIRET, TVA, IBAN", identite_entreprise: "L'entreprise existe et est active",
  nom_facture: "Le nom correspond au SIRET", procedures_bodacc: "Procédures collectives",
  gel_des_avoirs: "Sanctions : gel des avoirs", tva_vies: "TVA intracommunautaire", adresse_facture: "L'adresse existe",
  montant_eur: "Montant en euros", referentiel_crm: "Référentiel fournisseur du CRM",
};
// Libellé lisible et champ de la facture concerné par chaque code d'alerte (affichage seulement)
const CODES = {
  IBAN_DIFFERENT_DU_REFERENTIEL: ["L'IBAN n'est pas celui du référentiel", "iban"], IBAN_ETRANGER: ["IBAN domicilié à l'étranger", "iban"],
  IBAN_INVALIDE: ["IBAN invalide (clé fausse)", "iban"], SIRET_INVALIDE: ["SIRET invalide (clé fausse)", "siret"],
  SIRET_DIFFERENT_DU_REFERENTIEL: ["SIRET différent du référentiel", "siret"], ENTREPRISE_NON_TROUVEE: ["Entreprise introuvable", "siret"],
  ETABLISSEMENT_FERME: ["Établissement fermé", "siret"], ETABLISSEMENT_NON_RETROUVE: ["Établissement introuvable", "siret"],
  TVA_INCOHERENTE: ["Numéro de TVA d'une autre entreprise", "tva"], TVA_NON_ENREGISTREE_VIES: ["TVA non active dans VIES", "tva"],
  TVA_NON_CONFIRMEE: ["TVA non confirmée", "tva"], NOM_DIFFERENT: ["Le nom ne correspond pas au SIRET", "nom_emetteur"],
  NOM_APPROCHANT: ["Nom approchant (imitation ?)", "nom_emetteur"], GEL_DES_AVOIRS: ["Inscrit au registre des gels des avoirs", "nom_emetteur"],
  GEL_DES_AVOIRS_PARTIEL: ["Nom proche d'une entité sanctionnée", "nom_emetteur"], LIQUIDATION_JUDICIAIRE: ["Entreprise en liquidation judiciaire", "nom_emetteur"],
  PROCEDURE_COLLECTIVE: ["Procédure collective en cours", "nom_emetteur"], ENTREPRISE_CESSEE: ["Entreprise fermée", "nom_emetteur"],
  ENTREPRISE_RECENTE: ["Société créée très récemment", "nom_emetteur"], RADIATION_PUBLIEE: ["Radiation publiée au BODACC", "nom_emetteur"],
  FOURNISSEUR_INCONNU: ["Fournisseur absent du référentiel", "nom_emetteur"], ADRESSE_INTROUVABLE: ["Adresse introuvable", "adresse_emetteur"],
  ADRESSE_DIFFERENTE: ["Adresse dans une autre commune", "adresse_emetteur"], ADRESSE_NON_VERIFIEE: ["Adresse non vérifiée", "adresse_emetteur"],
  MONTANT_ANORMAL: ["Montant anormal par rapport à l'historique", "montant"], DOUBLE_VALIDATION: ["Montant au-dessus du seuil de double validation", "montant"],
  DOUBLON_FACTURE: ["Facture déjà reçue (même numéro)", "numero"], FACTURE_INCOMPLETE: ["Facture incomplète", null],
};
const ACTIONS = {
  initialisation: "Démo réinitialisée", depot: "Dépôt d'une facture", analyse_demandee: "Le CRM appelle le MCP",
  verification: "Verdict écrit par le MCP", reponse_mcp: "Réponse du MCP", validation_humaine: "Validation humaine",
  paiement_simule: "Paiement (simulé)", changement_iban: "Changement d'IBAN",
};
const FILTRES_JOURNAL = { tout: "Tout", mcp: "MCP", humain: "Humain", depot: "Dépôts", systeme: "Système" };
const CHAMPS_FORMULAIRE = [
  ["numero", "N° de facture", "text", false], ["date_emission", "Date", "date", false],
  ["nom_emetteur", "Fournisseur", "text", true], ["siret", "SIRET", "text", false], ["tva", "TVA", "text", false],
  ["iban", "IBAN", "text", true], ["adresse_emetteur", "Adresse", "text", true], ["montant", "Montant TTC", "text", false],
  ["devise", "Devise", "select", false], ["objet", "Objet", "textarea", true],
];

const etat = {
  cle: null, role: null, page: "analyser",
  factures: new Map(), fournisseurs: new Map(), scenarios: new Map(), exemples: [],
  journal: [], dernierId: 0, verdicts: new Map(), enAnalyse: new Set(), echecs: new Map(),
  file: [], lecture: false, interrompre: false, vitesse: 0, focus: null, apercu: null, filtreJournal: "tout",
  minuteurSuivi: null, nouvelles: new Set(),
};
const mouvementReduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ outils

const $ = (id) => document.getElementById(id);
const connu = (table, cle) => Object.prototype.hasOwnProperty.call(table, cle);

/** Crée un élément. Les enfants texte deviennent des nœuds texte : jamais de HTML interprété. */
function el(tag, attributs = {}, ...enfants) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attributs)) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") n.className = v;
    else if (k === "style") Object.assign(n.style, v);   // propriété CSSOM : autorisée par la CSP
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const e of enfants.flat()) {
    if (e === null || e === undefined || e === false) continue;
    n.append(e instanceof Node ? e : document.createTextNode(String(e)));
  }
  return n;
}
const verdict = (s) => (connu(VERDICTS, s) ? VERDICTS[s] : VERDICTS.recue);
const classe = (s) => (connu(VERDICTS, s) ? `c-${s}` : "c-attente");
const icone = (forme, extra = "") => el("span", { class: `icone forme-${forme} ${extra}`.trim(), "aria-hidden": "true" });
const badgeVerdict = (s) => el("span", { class: `badge ${classe(s)}` }, icone(verdict(s).forme), verdict(s).court);
const badgeAnalyse = () => el("span", { class: "badge c-indigo" }, el("span", { class: "tourne", "aria-hidden": "true" }), "Analyse MCP…");

function formaterMontant(montant, devise) {
  if (montant === null || montant === undefined || montant === "") return "—";
  const [entier, decimales] = String(montant).split(".");
  const groupes = entier.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const symbole = devise === "EUR" ? "€" : devise === "USD" ? "$" : devise || "";
  return `${groupes}${decimales !== undefined ? "," + decimales : ""}${symbole ? " " + symbole : ""}`;
}
function centimes(m) {
  const r = /^(\d+)(?:\.(\d{1,2}))?$/.exec(String(m ?? ""));
  return r ? BigInt(r[1]) * 100n + BigInt((r[2] || "0").padEnd(2, "0")) : null;
}
function versChaine(c) { const s = c.toString().padStart(3, "0"); return `${s.slice(0, -2)}.${s.slice(-2)}`; }
function centimesEur(f) { if (!f) return null; if (f.montant_eur) return centimes(f.montant_eur); return f.devise === "EUR" ? centimes(f.montant) : null; }
function heure(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function duree(ms) { return ms >= 1000 ? `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s` : `${ms} ms`; }

let minuteurMessage = null;
function afficherMessage(texte, type = "ok") {
  const z = $("message");
  z.textContent = texte; z.className = `message ${type}`; z.hidden = false;
  clearTimeout(minuteurMessage);
  if (type === "ok") minuteurMessage = setTimeout(() => { z.hidden = true; }, 5000);
}
function lireSession(cle) { try { return sessionStorage.getItem(cle); } catch { return null; } }
function ecrireSession(cle, v) { try { if (v === null) sessionStorage.removeItem(cle); else sessionStorage.setItem(cle, v); } catch { /* indisponible */ } }

class ErreurApi extends Error { constructor(statut, message) { super(message); this.statut = statut; } }

async function appelApi(methode, chemin, { json, formulaire } = {}) {
  const entetes = { "X-Presentation": "1" };            // en-tête personnalisé : le CRM refuse les autres sites
  if (etat.cle) entetes["X-API-Key"] = etat.cle;
  let corps;
  if (json !== undefined) { entetes["Content-Type"] = "application/json"; corps = JSON.stringify(json); }
  if (formulaire) corps = formulaire;
  let reponse;
  try { reponse = await fetch(chemin, { method: methode, headers: entetes, body: corps, cache: "no-store" }); }
  catch { throw new ErreurApi(0, "Le CRM ne répond pas. Est-il lancé (uvicorn crm.app:app --port 8000) ?"); }
  let donnees = null;
  try { donnees = await reponse.json(); } catch { /* sans JSON */ }
  if (!reponse.ok) {
    let detail = donnees && donnees.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).slice(-1)[0] || "champ"} : ${d.msg}`).join(" ; ");
    if (reponse.status === 401) deconnecter(etat.cle ? "Clé refusée par le CRM. Saisissez-la à nouveau." : null);
    throw new ErreurApi(reponse.status, `Refusé par le CRM (HTTP ${reponse.status}) — ${detail || "erreur"}`);
  }
  return donnees;
}

let reveil = null;
function pause(ms) {
  if (etat.interrompre || mouvementReduit) return Promise.resolve();
  return new Promise((r) => {
    const t = setTimeout(() => { reveil = null; r(); }, ms / VITESSES[etat.vitesse]);
    reveil = () => { clearTimeout(t); reveil = null; r(); };
  });
}

// ------------------------------------------------------------------ connexion et navigation

async function connecter(cle) {
  etat.cle = cle;
  const session = await appelApi("GET", "/api/session");
  etat.role = session.role;
  ecrireSession(CLE_STOCKAGE, cle || null);
  const presentation = !cle && session.presentation;
  document.body.classList.toggle("presentation", presentation);
  $("utilisateur-role").textContent = presentation ? "Mode présentation · accès local" : "Clé admin";
  $("champ-cle").value = "";
  document.body.classList.add("connecte");
  $("ecran-connexion").hidden = true;
  $("onglets").hidden = false;
  $("zone-session").hidden = false;
  $("bouton-reinitialiser").disabled = !session.peut_agir;
  $("case-auto").checked = lireSession(AUTO_STOCKAGE) === "1";
  await chargerTout();
  allerA(location.hash.slice(1) || "pitch");
  demarrerSuivi();
}

function deconnecter(message) {
  arreterSuivi();
  interrompre();
  Object.assign(etat, { cle: null, role: null, journal: [], file: [], verdicts: new Map(), enAnalyse: new Set(), focus: null, apercu: null });
  ecrireSession(CLE_STOCKAGE, null);
  quitterEnregistrement();
  document.body.classList.remove("connecte");
  document.querySelectorAll(".page").forEach((p) => { p.hidden = true; });
  $("onglets").hidden = true;
  $("zone-session").hidden = true;
  $("ecran-connexion").hidden = false;
  if (message) afficherMessage(message, "erreur");
}

const TITRES_PAGES = {
  pitch: ["Pitch", "Les diapositives de l'oral."],
  analyser: ["Analyser une facture", "Déposez une facture : le serveur MCP la vérifie dans 6 sources officielles et dans votre référentiel."],
  jeu: ["Jeu de test", "14 arnaques réelles de la fraude fournisseur et 2 factures saines, en PDF fictifs. Glissez une carte dans la zone de dépôt, déposez-la d'un clic, ou lancez la démo complète."],
  fournisseurs: ["Référentiel fournisseurs", "Ce que le MCP compare à chaque facture : SIRET, IBAN enregistré, historique. En cas de doute, on contre-appelle au numéro du référentiel, jamais à celui de la facture."],
  journal: ["Journal d'audit", "Chaque dépôt, appel au MCP, verdict et décision humaine, horodatés. Le verdict est écrit par le MCP lui-même ; l'IA ne peut ni payer ni valider."],
};

function allerA(page) {
  if (!["pitch", "analyser", "jeu", "fournisseurs", "journal"].includes(page)) page = "pitch";
  etat.page = page;
  $("titre-page").textContent = TITRES_PAGES[page][0];
  $("sous-titre-page").textContent = TITRES_PAGES[page][1];
  document.querySelectorAll(".page").forEach((p) => { p.hidden = p.dataset.page !== page; });
  document.querySelectorAll("#onglets a").forEach((a) => {
    if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  document.body.classList.toggle("page-pitch", page === "pitch");
  if (page === "pitch") afficherDiapo(pitch.index);
  if (page === "jeu") afficherExemples();
  if (page === "fournisseurs") afficherFournisseurs();
  if (page === "journal") afficherJournal();
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------ données

function depuisInitialisation(journal) {
  let debut = 0;
  journal.forEach((e, i) => { if (e.action === "initialisation") debut = i; });
  return journal.slice(debut);
}
const resultat = (e) => {
  const d = e.detail && typeof e.detail === "object" ? e.detail : {};
  return { statut: e.statut, codes: Array.isArray(d.codes) ? d.codes : [], mode: d.mode, statut_mcp: d.statut_mcp };
};
const enBoite = (f) => f.source !== "historique";

async function rafraichirFactures() {
  const factures = await appelApi("GET", "/api/factures");
  etat.factures = new Map(factures.map((f) => [f.id, f]));
}

async function chargerTout() {
  const [scenarios, factures, journal, fournisseurs, exemples] = await Promise.all([
    appelApi("GET", "/api/scenarios"), appelApi("GET", "/api/factures"), appelApi("GET", "/api/journal"),
    appelApi("GET", "/api/fournisseurs"), appelApi("GET", "/api/exemples")]);
  etat.scenarios = new Map(scenarios.map((s) => [s.facture_id, s]));
  etat.factures = new Map(factures.map((f) => [f.id, f]));
  etat.fournisseurs = new Map(fournisseurs.map((f) => [f.id, f]));
  etat.exemples = exemples;
  etat.journal = depuisInitialisation(journal);
  etat.dernierId = journal.reduce((m, e) => Math.max(m, e.id), 0);
  etat.verdicts = new Map(); etat.enAnalyse = new Set(); etat.echecs = new Map();
  for (const e of etat.journal) noterEvenement(e);
  const derniere = [...etat.journal].reverse().find((e) => e.action === "verification" || e.action === "depot");
  etat.focus = derniere ? derniere.facture_id : null;
  afficherMode([...etat.journal].reverse().find((e) => e.action === "verification"));
  afficherKpis(false); afficherBoite(); afficherScene();
  if (etat.page !== "analyser") allerA(etat.page);
}

/** Met à jour l'état (verdicts, analyses en cours, échecs) à partir d'une entrée du journal. */
function noterEvenement(e) {
  if (e.action === "analyse_demandee") {
    if (e.facture_id) { etat.enAnalyse.add(e.facture_id); etat.echecs.delete(e.facture_id); }
    else for (const f of etat.factures.values()) if (f.statut === "recue") etat.enAnalyse.add(f.id);
  } else if (e.action === "verification") {
    etat.verdicts.set(e.facture_id, resultat(e));
    etat.enAnalyse.delete(e.facture_id);
  } else if (e.action === "reponse_mcp") {
    const d = e.detail || {};
    const echec = d.resultat === "ECHEC_APPEL_MCP" || d.resultat === "SOURCE_INDISPONIBLE";
    if (e.facture_id) {
      if (echec) etat.echecs.set(e.facture_id, d.raison || d.resultat);
      if (echec || d.resultat === "REFUS") etat.enAnalyse.delete(e.facture_id);
    } else {
      for (const id of [...etat.enAnalyse]) if (!etat.factures.get(id) || etat.factures.get(id).statut !== "recue") etat.enAnalyse.delete(id);
      if (echec) for (const id of [...etat.enAnalyse]) { etat.echecs.set(id, d.raison || d.resultat); etat.enAnalyse.delete(id); }
    }
  }
}

function afficherMode(entree) {
  const z = $("mode-verif");
  const mode = entree && entree.detail && entree.detail.mode;
  z.hidden = !mode;
  z.textContent = mode === "reel" ? "Mode réel · 6 API publiques" : mode === "simulation" ? "Mode simulation" : "";
}

// ------------------------------------------------------------------ suivi en direct

function demarrerSuivi() {
  arreterSuivi();
  etat.minuteurSuivi = setInterval(async () => {
    if (document.hidden || !etat.role) return;
    try { await suivre(); $("indicateur-direct").classList.remove("arret"); }
    catch { $("indicateur-direct").classList.add("arret"); }
  }, INTERVALLE_SUIVI_MS);
}
function arreterSuivi() { clearInterval(etat.minuteurSuivi); etat.minuteurSuivi = null; }

async function suivre() {
  const nouvelles = await appelApi("GET", `/api/journal?depuis=${etat.dernierId}`);
  if (!nouvelles.length) return;
  etat.dernierId = nouvelles.reduce((m, e) => Math.max(m, e.id), etat.dernierId);
  if (nouvelles.some((e) => e.action === "initialisation")) {
    interrompre(); etat.file = []; await attendreFinLecture();
    await chargerTout();
    return;
  }
  if (nouvelles.some((e) => ["depot", "verification", "validation_humaine", "paiement_simule", "reponse_mcp"].includes(e.action))) {
    await rafraichirFactures();
  }
  let rafraichirScene = false;
  for (const e of nouvelles) {
    etat.journal.push(e);
    if (e.action === "verification") { etat.file.push(e); continue; }        // le verdict sera joué en animation
    noterEvenement(e);
    if (e.action === "depot") etat.nouvelles.add(e.facture_id);
    if (e.action === "analyse_demandee" && e.facture_id && !etat.lecture) etat.focus = e.facture_id;
    if (e.facture_id === etat.focus || (e.action === "analyse_demandee" && !e.facture_id)) rafraichirScene = true;
  }
  afficherBoite();
  if (rafraichirScene && !etat.lecture) afficherScene();
  if (etat.page === "journal") afficherJournal();
  if (etat.page === "fournisseurs") afficherFournisseurs();
  lancerLecture();
}

// ------------------------------------------------------------------ lecture animée des verdicts

async function lancerLecture() {
  if (etat.lecture || !etat.file.length) return;
  etat.lecture = true; majCommandes();
  while (etat.file.length) await jouer(etat.file.shift());
  etat.lecture = false; etat.interrompre = false; majCommandes();
  afficherBoite(); afficherScene();
}
function attendreFinLecture() { return new Promise((r) => { const v = () => (etat.lecture ? setTimeout(v, 50) : r()); v(); }); }
function interrompre() { if (!etat.lecture) return; etat.interrompre = true; if (reveil) reveil(); }

function rejouer() {
  if (etat.lecture) { interrompre(); return; }
  const verifs = etat.journal.filter((e) => e.action === "verification");
  if (!verifs.length) { afficherMessage("Rien à rejouer : le MCP n'a encore analysé aucune facture.", "erreur"); return; }
  etat.verdicts = new Map();
  afficherKpis(false); afficherBoite();
  etat.file = verifs.slice();
  lancerLecture();
}

async function jouer(e) {
  const f = etat.factures.get(e.facture_id);
  afficherMode(e);
  if (!f) { noterEvenement(e); return; }
  if (etat.page !== "analyser") { noterEvenement(e); afficherKpis(false); return; }   // scène cachée : pas d'animation
  etat.focus = f.id;
  etat.enAnalyse.add(f.id);                 // pendant l'animation, la facture est montrée « en analyse »
  afficherBoite();
  const scene = construireScene(f, { anime: true, entree: e });
  await pause(DUREES.facture);
  for (const ligne of scene.lignes) {
    ligne.element.classList.add("actif");
    await pause(DUREES.controle * 0.55);
    ligne.element.classList.remove("actif");
    ligne.element.classList.add("fait", `c-${ligne.resultat}`);
    await pause(DUREES.controle * 0.45);
  }
  noterEvenement(e);
  scene.reveler();
  afficherKpis(true); afficherBoite();
  await pause(DUREES.verdict + DUREES.pause);
}

function majCommandes() {
  const b = document.getElementById("bouton-rejouer");
  if (b) b.textContent = etat.lecture ? "Passer l'animation" : "Rejouer";
  document.querySelectorAll(".element-boite").forEach((x) => { x.disabled = etat.lecture; });
}

// ------------------------------------------------------------------ chiffres clés

function afficherKpis(anime) {
  const compte = { bloquee: 0, a_verifier_humain: 0, verifiee: 0, impossible_de_verifier: 0 };
  let retenu = 0n, analysees = 0;
  const deposees = [...etat.factures.values()].filter(enBoite).length;
  for (const [id, r] of etat.verdicts) {
    const f = etat.factures.get(id);
    if (!f || !enBoite(f)) continue;
    analysees += 1;
    if (connu(compte, r.statut)) compte[r.statut] += 1;
    if (STATUTS_RETENUS.includes(r.statut)) retenu += centimesEur(f) ?? 0n;
  }
  const avant = new Map([...$("kpis").querySelectorAll(".kpi")].map((k) => [k.dataset.cle, k.querySelector(".valeur")?.textContent]));
  const tuile = (cle, couleur, forme, valeur, libelle) => {
    const t = el("div", { class: `kpi ${couleur}`, "data-cle": cle }, icone(forme), el("span", { class: "valeur" }, valeur), el("span", { class: "libelle" }, libelle));
    if (anime && avant.get(cle) !== undefined && avant.get(cle) !== String(valeur)) t.classList.add("monte");
    return t;
  };
  const tuiles = [
    tuile("analysees", "c-indigo", "grille", `${analysees}/${deposees}`, "Factures analysées par le MCP"),
    tuile("bloquee", "c-bloquee", "carre", compte.bloquee, "Paiements bloqués"),
    tuile("humain", "c-a_verifier_humain", "triangle", compte.a_verifier_humain, "Envoyées à un humain"),
    tuile("verifiee", "c-verifiee", "rond", compte.verifiee, "Sans alerte"),
  ];
  if (compte.impossible_de_verifier) tuiles.push(tuile("impossible", "c-impossible_de_verifier", "losange", compte.impossible_de_verifier, "Impossibles à vérifier"));
  const argent = el("div", { class: "kpi argent", "data-cle": "argent" },
    el("span", { class: "valeur" }, formaterMontant(versChaine(retenu), "EUR")),
    el("span", { class: "libelle" }, "Montant retenu par le MCP"),
    el("span", { class: "precision" }, "le paiement ne part pas sans décision humaine"));
  if (anime && avant.get("argent") !== argent.querySelector(".valeur").textContent) argent.classList.add("monte");
  $("kpis").replaceChildren(...tuiles, argent);
}

// ------------------------------------------------------------------ boîte de réception

function statutAffiche(f) {
  // tant que le verdict n'a pas été joué à l'écran, la facture reste « en analyse » (pas de résultat dévoilé avant l'animation)
  if (etat.enAnalyse.has(f.id) || etat.file.some((x) => x.facture_id === f.id)) return "analyse";
  const r = etat.verdicts.get(f.id);
  if (f.statut === "payee") return "payee";
  return r ? r.statut : f.statut;
}

function afficherBoite() {
  const factures = [...etat.factures.values()].filter(enBoite).sort((a, b) => (b.id > a.id ? 1 : -1));
  $("compteur-boite").textContent = String(factures.length);
  const recues = factures.filter((f) => f.statut === "recue" && !etat.enAnalyse.has(f.id)).length;
  const bouton = $("bouton-analyser-tout");
  bouton.disabled = !recues || etat.role !== "admin";
  bouton.textContent = recues ? `Analyser les ${recues} facture${recues > 1 ? "s" : ""} reçue${recues > 1 ? "s" : ""} avec le MCP` : "Aucune facture en attente";
  const elements = factures.map((f) => {
    const s = statutAffiche(f);
    const scen = f.scenario && etat.scenarios.get(f.scenario);
    return el("li", {}, el("button", {
      type: "button", class: `element-boite ${s === "analyse" ? "c-indigo" : classe(s)}${etat.nouvelles.has(f.id) ? " nouveau" : ""}`,
      "aria-current": f.id === etat.focus ? "true" : null, disabled: etat.lecture, onclick: () => montrer(f.id),
    },
      el("span", { class: "nom" }, f.nom_emetteur || "Émetteur inconnu"),
      el("span", { class: "somme" }, formaterMontant(f.montant, f.devise)),
      el("span", { class: "sous" }, `${f.id} · ${f.numero}${scen ? " · " + scen.titre : ""}`),
      s === "analyse" ? badgeAnalyse() : badgeVerdict(s)));
  });
  etat.nouvelles.clear();
  $("liste-boite").replaceChildren(...(elements.length ? elements
    : [el("li", { class: "vide" }, "Aucune facture. Déposez-en une, ou lancez la démo depuis le jeu de test.")]));
}

function montrer(id) {
  if (etat.lecture || !etat.factures.has(id)) return;
  etat.focus = id;
  afficherBoite(); afficherScene();
  if (window.innerWidth <= 1150) $("scene").scrollIntoView({ behavior: mouvementReduit ? "auto" : "smooth", block: "start" });
}

// ------------------------------------------------------------------ dépôt et aperçu

async function deposerFichier(fichier) {
  if (!fichier) return;
  const zone = $("zone-depot");
  zone.classList.add("lecture");
  try {
    const formulaire = new FormData();
    formulaire.append("fichier", fichier, fichier.name);
    const lu = await appelApi("POST", "/api/factures/depot", { formulaire });
    etat.apercu = lu;
    if ($("case-auto").checked && !lu.manquants.length) await creerEtAnalyser(lu.champs, lu.fichier);
    else afficherApercu();
  } catch (e) {
    afficherMessage(e.message, "erreur");
  } finally {
    zone.classList.remove("lecture");
  }
}

async function deposerExemple(id, { analyser = true } = {}) {
  const ex = etat.exemples.find((x) => x.id === id);
  if (!ex) return null;
  const r = await fetch(ex.url, { cache: "no-store" });
  if (!r.ok) throw new ErreurApi(r.status, "Facture d'exemple introuvable.");
  const fichier = new File([await r.blob()], ex.nom_fichier, { type: "application/pdf" });
  const formulaire = new FormData();
  formulaire.append("fichier", fichier, fichier.name);
  const lu = await appelApi("POST", "/api/factures/depot", { formulaire });
  return creerEtAnalyser(lu.champs, lu.fichier, { analyser });
}

async function creerEtAnalyser(champs, fichier, { analyser = true } = {}) {
  const corps = {};
  for (const [cle, val] of Object.entries(champs)) if (val !== null && val !== "") corps[cle] = val;
  if (fichier) { corps.nom_fichier = fichier.nom; corps.empreinte_fichier = fichier.empreinte; }
  const f = await appelApi("POST", "/api/factures", { json: corps });
  etat.factures.set(f.id, f);
  etat.apercu = null; afficherApercu();
  if (analyser) {
    etat.enAnalyse.add(f.id);
    await appelApi("POST", `/api/factures/${encodeURIComponent(f.id)}/analyse`);
  }
  if (!etat.lecture) etat.focus = f.id;
  etat.nouvelles.add(f.id);
  afficherKpis(false); afficherBoite();
  if (!etat.lecture) afficherScene();
  return f;
}

function afficherApercu() {
  const zone = $("apercu");
  const a = etat.apercu;
  zone.hidden = !a;
  if (!a) { zone.replaceChildren(); return; }
  const champs = a.champs || {};
  const elements = CHAMPS_FORMULAIRE.map(([cle, libelle, type, large]) => {
    const id = `apercu-${cle}`;
    let saisie;
    if (type === "select") {
      saisie = el("select", { id, name: cle }, ["EUR", "USD", "GBP", "CHF"].map((d) => el("option", { value: d, selected: champs[cle] === d }, d)));
    } else if (type === "textarea") {
      saisie = el("textarea", { id, name: cle, maxlength: "500" }); saisie.value = champs[cle] || "";
    } else {
      saisie = el("input", { id, name: cle, type, maxlength: "200", autocomplete: "off", spellcheck: "false" }); saisie.value = champs[cle] || "";
    }
    return el("div", { class: `champ${large ? " large" : ""}${(a.manquants || []).includes(cle) ? " manquant" : ""}` }, el("label", { for: id }, libelle), saisie);
  });
  const formulaire = el("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      const donnees = Object.fromEntries(new FormData(e.target).entries());
      const manquants = ["numero", "nom_emetteur", "montant"].filter((k) => !String(donnees[k] || "").trim());
      if (manquants.length) { afficherMessage("Complétez au moins le numéro, le fournisseur et le montant.", "erreur"); return; }
      const bouton = e.submitter; if (bouton) bouton.disabled = true;
      try { await creerEtAnalyser(donnees, a.fichier); }
      catch (err) { afficherMessage(err.message, "erreur"); if (bouton) bouton.disabled = false; }
    },
  }, el("div", { class: "grille-champs" }, elements),
  el("div", { class: "boutons" },
    el("button", { type: "submit" }, "Analyser avec le MCP"),
    el("button", { type: "button", class: "secondaire", onclick: () => { etat.apercu = null; afficherApercu(); } }, "Annuler")));
  zone.replaceChildren(
    el("h2", {}, a.fichier ? "Ce que le CRM a lu" : "Saisie d'une facture"),
    el("div", { class: "fichier" }, a.fichier
      ? `${a.fichier.nom} · ${Math.max(1, Math.round(a.fichier.taille / 1024))} Ko · lecture déterministe, sans IA. Corrigez si besoin.`
      : "Saisissez les informations écrites sur la facture."),
    formulaire);
  zone.scrollIntoView({ behavior: mouvementReduit ? "auto" : "smooth", block: "nearest" });
}

// ------------------------------------------------------------------ scène

function afficherScene() {
  const f = etat.focus && etat.factures.get(etat.focus);
  if (!f) { afficherSceneVide(); return; }
  construireScene(f, { anime: false });
}

function afficherSceneVide() {
  $("scene").replaceChildren(el("div", { class: "scene-vide" }, el("div", {},
    el("div", { class: "formes" }, icone("rond", "c-verifiee"), icone("triangle", "c-a_verifier_humain"), icone("carre", "c-bloquee")),
    el("h2", {}, "Déposez une facture pour voir le MCP au travail"),
    el("p", {}, "Le serveur MCP la contrôle dans 6 sources officielles et dans votre référentiel. Chaque contrôle s'allume ici, puis le verdict tombe, avec ses raisons."),
    el("ol", { class: "parcours-vide" },
      el("li", {}, el("b", {}, "1. Déposer"), "PDF, TXT ou JSON. Le CRM lit la facture, sans IA."),
      el("li", {}, el("b", {}, "2. Le MCP vérifie"), "SIRET, TVA, IBAN, sanctions, procédures, adresse, référentiel."),
      el("li", {}, el("b", {}, "3. Un humain décide"), "Le paiement reste verrouillé tant que le verdict ne le permet pas.")))));
}

function tracePour(f) {
  const premier = etat.journal.find((e) => e.facture_id === f.id);
  if (!premier) return [];
  const propres = etat.journal.filter((e) => e.facture_id === f.id);
  const fin = propres.length ? propres[propres.length - 1].id : premier.id;
  const verif = [...propres].reverse().find((e) => e.action === "verification");
  return etat.journal.filter((e) => e.facture_id === f.id
    || (!e.facture_id && ["analyse_demandee", "reponse_mcp"].includes(e.action) && e.id > premier.id && e.id <= Math.max(fin, verif ? verif.id + 50 : fin)
        && (e.action === "analyse_demandee" ? !verif || e.id < verif.id : true)));
}

function elementTrace(e, f, anime) {
  const d = e.detail && typeof e.detail === "object" ? e.detail : {};
  let quoi = ACTIONS[e.action] || e.action, meta = `${heure(e.horodatage)} · ${e.acteur}`, code = null, couleur = `c-${e.action}`;
  if (e.action === "depot") {
    const four = d.fournisseur_id && etat.fournisseurs.get(d.fournisseur_id);
    quoi = d.fichier ? `Dépôt de « ${d.fichier} »` : "Facture saisie";
    meta += four ? ` · rattachée à ${four.nom} (par ${d.rattachement === "siret" ? "SIRET" : "nom"})` : " · fournisseur absent du référentiel";
  } else if (e.action === "analyse_demandee") {
    code = `tools/call  ${d.outil || "traiter_factures_crm"}  ${JSON.stringify(d.arguments || {})}`;
    meta += ` · ${d.transport || "protocole MCP"}`;
  } else if (e.action === "verification") {
    quoi = `Le MCP écrit son verdict : ${d.statut_mcp || e.statut}`;
    code = `POST /api/factures/${f.id}/verification   (clé du MCP : écrire un résultat, rien d'autre)`;
    meta += ` · ${(d.codes || []).length} alerte(s) · empreinte ${(d.empreinte || "").slice(0, 12)}…`;
    couleur = classe(e.statut);
  } else if (e.action === "reponse_mcp") {
    const echec = d.resultat === "ECHEC_APPEL_MCP";
    quoi = echec ? `Échec de l'appel au MCP (${d.raison || "erreur"})` : `Réponse du MCP en ${duree(d.duree_ms || 0)}`;
    meta += ` · ${d.resultat || ""}${d.nombre_traitees > 1 ? ` · ${d.nombre_traitees} factures` : ""}`;
    couleur = echec ? "c-echec" : "c-reponse_mcp";
  } else if (e.action === "validation_humaine") {
    quoi = `Validation humaine par ${d.valideur || "un humain"}`; meta += d.commentaire ? ` · « ${d.commentaire} »` : "";
  } else if (e.action === "paiement_simule") {
    quoi = `Paiement simulé de ${formaterMontant(d.montant, d.devise)} par un humain`;
  }
  return el("li", { class: `${couleur}${anime ? " apparait" : ""}` }, el("span", { class: "point", "aria-hidden": "true" }),
    el("div", {}, el("div", { class: "quoi" }, quoi), el("div", { class: "meta" }, meta), code ? el("code", {}, code) : null));
}

/** Construit la scène d'une facture. En mode animé, contrôles et verdict sont révélés ensuite par jouer(). */
function construireScene(f, { anime, entree }) {
  const r = anime ? resultat(entree) : etat.verdicts.get(f.id) || null;
  const enAttente = !anime && etat.enAnalyse.has(f.id);
  const echec = !anime && !r && etat.echecs.get(f.id);
  const statut = r ? r.statut : f.statut;
  const v = f.derniere_verification;
  const scen = f.scenario && etat.scenarios.get(f.scenario);
  const fournisseur = f.fournisseur_id && etat.fournisseurs.get(f.fournisseur_id);
  const controles = v && Array.isArray(v.controles) && v.controles.length ? v.controles
    : Object.keys(CONTROLES).map((c) => ({ controle: c, source: "", resultat: "NON_DEMANDE" }));

  // étapes du parcours
  const etapes = ["Dépôt", "Lecture", "Appel MCP", "Contrôles", "Verdict", "Décision"].map((nom, i) =>
    el("li", { class: "etape" }, el("span", { class: "pastille" }, String(i + 1)), el("span", {}, nom)));
  const regler = (fait, actif, rate = -1, decision = null) => etapes.forEach((e, i) => {
    e.className = `etape${i < fait ? " fait" : ""}${i === actif ? " actif" : ""}${i === rate ? " echec" : ""}`;
    if (i < fait) e.querySelector(".pastille").textContent = "✓";
    if (i === 5 && decision) e.lastChild.textContent = decision;
  });
  const etapesDecision = () => {
    if (f.statut === "payee") return regler(6, -1, -1, "Payée");
    if (["bloquee", "impossible_de_verifier"].includes(f.statut)) return regler(5, -1, 5, "Verrouillé");
    return regler(5, 5, -1, f.statut === "verifiee" ? "Payable" : "À valider");
  };

  // la facture
  const dd = (nom, val) => el("dd", { "data-champ": nom }, val || "—");
  const facture = el("article", { class: `facture ${r ? classe(statut) : "c-attente"}${anime ? " entre" : ""}` },
    el("div", { class: "tete" }, el("b", {}, "FACTURE"), el("span", { "data-champ": "numero" }, f.numero)),
    el("div", { class: "emetteur", "data-champ": "nom_emetteur" }, f.nom_emetteur || "Émetteur inconnu"),
    el("div", { class: "montant", "data-champ": "montant" }, formaterMontant(f.montant, f.devise)),
    el("dl", {}, el("dt", {}, "SIRET"), dd("siret", f.siret), el("dt", {}, "TVA"), dd("tva", f.tva),
      el("dt", {}, "IBAN"), dd("iban", f.iban), el("dt", {}, "Adresse"), dd("adresse_emetteur", f.adresse_emetteur)),
    el("div", { class: "objet", "data-champ": "objet" }, el("small", {}, "Texte de la facture, lu comme une donnée"), f.objet || "—"),
    el("div", { class: "provenance" },
      el("span", {}, f.fichier && f.fichier.nom ? `Fichier : ${f.fichier.nom}` : f.source === "jeu_de_test" ? "Importée du jeu de test" : "Saisie manuelle"),
      el("span", {}, fournisseur ? `Référentiel : ${fournisseur.nom}` : "Absent du référentiel")));

  // les contrôles
  const lignes = controles.map((c) => {
    const res = connu(RESULTATS, c.resultat) ? c.resultat : "NON_DEMANDE";
    const element = el("li", { class: `controle${!anime && r ? ` fait c-${res}` : ""}` },
      el("span", { class: "noeud", "aria-hidden": "true" }, RESULTATS[res].symbole),
      el("span", { class: "nom" }, CONTROLES[c.controle] || c.controle,
        c.source ? el("span", { class: "source" }, c.source) : null, c.raison ? el("span", { class: "raison" }, c.raison) : null),
      el("span", { class: `resultat badge c-${res}` }, RESULTATS[res].libelle));
    return { element, resultat: res };
  });

  // le verdict
  const zoneVerdict = el("div", { class: "verdict" });
  const verdictAttente = (texte) => zoneVerdict.replaceChildren(
    el("div", { class: "attente-formes" }, icone("rond", "c-gris"), icone("carre", "c-gris"), icone("rond", "c-gris")), el("div", {}, texte));
  const verdictFinal = () => {
    const info = verdict(statut);
    zoneVerdict.className = `verdict rendu ${classe(statut)}`;
    zoneVerdict.replaceChildren(icone(info.forme, "grande-forme"), el("div", { class: "titre-verdict" }, info.titre),
      el("div", { class: "phrase" }, info.phrase),
      el("div", { class: "somme" }, formaterMontant(f.montant, f.devise), el("small", {}, SOUS_MONTANT[statut] || "")));
  };

  // pourquoi ce verdict
  const alertes = r && v && Array.isArray(v.alertes) ? v.alertes : [];
  const ordre = { BLOQUANT: 0, A_VERIFIER: 1, INFO: 2 };
  const raisons = el("ul", { class: "raisons" });
  const pourquoi = el("div", { class: "panneau" }, el("h3", {}, "Pourquoi ce verdict"));
  const remplirPourquoi = (animer) => {
    const triees = alertes.slice().sort((a, b) => (ordre[a.niveau] ?? 3) - (ordre[b.niveau] ?? 3));
    raisons.replaceChildren(...(triees.length ? triees.map((a, i) => {
      const niveau = connu(NIVEAUX, a.niveau) ? a.niveau : "INFO";
      return el("li", { class: `c-${niveau}${animer ? " apparait" : ""}`, style: animer ? { animationDelay: `${i * 110}ms` } : null },
        el("div", { class: "entete-raison" }, el("span", { class: `badge c-${niveau}` }, icone(FORMES_NIVEAU[niveau]), NIVEAUX[niveau]),
          el("b", {}, connu(CODES, a.code) ? CODES[a.code][0] : a.code)), a.message);
    }) : [el("li", { class: "c-OK" }, el("div", { class: "entete-raison" }, el("b", {}, "Aucune alerte")),
      "Rien d'anormal dans les sources consultées. Le titulaire de l'IBAN n'est pas vérifiable : un contre-appel reste la règle pour un nouveau RIB.")]));
    pourquoi.replaceChildren(el("h3", {}, "Pourquoi ce verdict"), el("p", { class: "regle" }, (v && v.message) || verdict(statut).phrase), raisons);
    // les champs de la facture en cause sont entourés (couleur du niveau de l'alerte)
    for (const a of triees) {
      const champ = connu(CODES, a.code) ? CODES[a.code][1] : null;
      if (!champ || a.niveau === "INFO") continue;
      facture.querySelectorAll(`[data-champ="${CSS.escape(champ)}"]`).forEach((n) => {
        if (!n.classList.contains("piege")) n.classList.add("piege", `c-${a.niveau}`);
      });
    }
  };

  // trace MCP
  const trace = el("ol", { class: "trace" }, tracePour(f).filter((e) => !anime || e.id < entree.id || e.action !== "reponse_mcp")
    .filter((e) => !anime || e.action !== "verification" || e.id < entree.id).map((e) => elementTrace(e, f, false)));
  const panneauTrace = el("div", { class: "panneau" }, el("h3", {}, "Trace de l'appel MCP"), trace);

  // décision humaine
  const decision = el("div", { class: "panneau decision" });
  const remplirDecision = () => {
    const admin = etat.role === "admin";
    const contenu = [el("h3", {}, "Décision humaine")];
    const verrou = (couleur, texte) => el("div", { class: `verrou ${couleur}` }, el("span", { class: "cadenas", "aria-hidden": "true" }), texte);
    const tel = fournisseur && fournisseur.telephone_reference;
    if (enAttente) contenu.push(verrou("c-indigo", "Le MCP analyse la facture : rien n'est payable en attendant."));
    else if (echec) {
      contenu.push(verrou("c-rouge", "L'appel au MCP a échoué : rien n'est conclu, la facture reste impayable."));
      if (admin) contenu.push(el("div", { class: "boutons" }, el("button", { type: "button", onclick: () => lancerAnalyse(f.id) }, "Relancer l'analyse")));
    } else if (!r && f.statut === "recue") {
      contenu.push(verrou("c-gris", "En attente de l'analyse du MCP."));
      if (admin) contenu.push(el("div", { class: "boutons" }, el("button", { type: "button", onclick: () => lancerAnalyse(f.id) }, "Analyser avec le MCP")));
    } else if (f.statut === "bloquee") {
      contenu.push(verrou("c-bloquee", `Paiement verrouillé : le CRM refuse de payer (HTTP 409).${tel ? ` Contre-appeler le fournisseur au ${tel}, numéro du référentiel.` : ""}`));
    } else if (f.statut === "impossible_de_verifier") {
      contenu.push(verrou("c-impossible_de_verifier", "Rien n'est conclu : relancer l'analyse quand les sources répondent."));
      if (admin) contenu.push(el("div", { class: "boutons" }, el("button", { type: "button", onclick: () => lancerAnalyse(f.id) }, "Relancer l'analyse")));
    } else if (f.statut === "a_verifier_humain") {
      if (!admin) contenu.push(verrou("c-a_verifier_humain", "Validation réservée à la clé administrateur."));
      else {
        const qui = el("input", { id: "champ-valideur", required: true, minlength: "2", maxlength: "80", placeholder: "ex. Directrice financière" });
        const pourquoiTexte = el("textarea", { id: "champ-commentaire", required: true, minlength: "10", maxlength: "500",
          placeholder: tel ? `ex. Contre-appel au ${tel} : commande confirmée.` : "ex. Contre-appel effectué : commande confirmée." });
        contenu.push(el("form", { onsubmit: async (e) => {
          e.preventDefault();
          if (qui.value.trim().length < 2 || pourquoiTexte.value.trim().length < 10) { afficherMessage("Indiquez qui valide et un commentaire d'au moins 10 caractères.", "erreur"); return; }
          await actionHumaine(e.submitter, () => appelApi("POST", `/api/factures/${encodeURIComponent(f.id)}/validation-humaine`,
            { json: { valideur: qui.value.trim(), commentaire: pourquoiTexte.value.trim() } }), `Facture ${f.id} validée : elle peut être payée.`);
        } }, el("label", { for: "champ-valideur" }, "Qui valide ?"), qui, el("label", { for: "champ-commentaire" }, "Contre-appel / commentaire"), pourquoiTexte,
        el("div", { class: "boutons" }, el("button", { type: "submit", class: "ambre" }, "Valider après contrôle"))));
      }
    } else if (f.statut === "verifiee") {
      contenu.push(verrou("c-verifiee", "Aucune alerte : un humain peut décider de payer."));
      if (admin) contenu.push(el("div", { class: "boutons" }, el("button", { type: "button", class: "vert", onclick: (e) => actionHumaine(e.currentTarget,
        () => appelApi("POST", `/api/factures/${encodeURIComponent(f.id)}/paiement`), `Facture ${f.id} payée (paiement simulé).`) },
        `Payer ${formaterMontant(f.montant, f.devise)} (simulé)`)));
    } else if (f.statut === "payee") {
      contenu.push(verrou("c-payee", "Payée par un humain (paiement simulé). Le MCP n'a jamais ce droit."));
    }
    decision.replaceChildren(...contenu);
  };

  // jeu de test
  const panneauTest = scen ? el("div", { class: "panneau" }) : null;
  const remplirTest = (revele) => {
    if (!panneauTest) return;
    const conforme = revele && r ? scen.statut_attendu === r.statut : null;
    panneauTest.replaceChildren(el("h3", {}, "Jeu de test"), el("p", { class: "piege-texte" }, `${scen.titre} — ${scen.piege}`),
      el("div", { class: "conformite" },
        el("div", { class: "ligne" }, el("span", {}, "Résultat attendu"), badgeVerdict(scen.statut_attendu)),
        revele && r ? el("div", { class: "ligne" }, el("span", {}, "Verdict du MCP"), badgeVerdict(r.statut)) : null,
        conforme === null ? null : el("div", { class: `sceau ${conforme ? "c-vert" : "c-rouge"}` },
          el("span", { class: "coche", "aria-hidden": "true" }, conforme ? "✓" : "✗"),
          conforme ? "Conforme : le garde-fou a réagi comme prévu" : "Écart avec le résultat attendu")));
  };

  // assemblage
  const surtitre = el("div", { class: "surtitre" }, anime ? "Analyse en cours par le MCP…" : enAttente ? "Le MCP analyse…" : r ? "Analyse du MCP" : "Facture reçue");
  const outils = el("div", { class: "outils" },
    scen ? el("span", { class: "etiquette c-indigo" }, icone("grille"), `Jeu de test : ${scen.titre}`) : null,
    el("button", { type: "button", id: "bouton-rejouer", class: "secondaire petit", onclick: rejouer }, etat.lecture ? "Passer l'animation" : "Rejouer"),
    el("button", { type: "button", id: "bouton-vitesse", class: "secondaire petit", onclick: changerVitesse }, `Vitesse ×${VITESSES[etat.vitesse]}`));
  $("scene").replaceChildren(
    el("div", { class: "scene-entete" }, el("div", {}, surtitre, el("h2", {}, `${f.id} · ${f.nom_emetteur || "Émetteur inconnu"}`)), outils),
    el("ol", { class: "etapes", "aria-label": "Étapes" }, etapes),
    el("div", { class: "scene-corps" }, facture, el("ol", { class: "controles", "aria-label": "Contrôles du MCP" }, lignes.map((l) => l.element)), zoneVerdict),
    el("div", { class: "scene-pied" }, pourquoi, panneauTrace, decision, panneauTest));

  if (anime) {
    regler(3, 3); verdictAttente("Le MCP vérifie…");
    raisons.replaceChildren(el("li", { class: "c-INFO" }, el("b", {}, "…"), " Le MCP interroge les sources officielles et le référentiel."));
    pourquoi.append(raisons); remplirTest(false);
    decision.replaceChildren(el("h3", {}, "Décision humaine"), el("div", { class: "verrou c-indigo" }, el("span", { class: "cadenas", "aria-hidden": "true" }), "Verrouillée pendant l'analyse."));
  } else if (r) {
    verdictFinal(); remplirPourquoi(false); remplirDecision(); remplirTest(true); etapesDecision();
  } else if (enAttente) {
    regler(2, 2); verdictAttente("Le CRM a appelé le MCP…");
    pourquoi.append(el("p", { class: "regle" }, "Le serveur MCP lit la facture dans le CRM et interroge les sources."), el("span", { class: "tourne" }));
    remplirDecision(); remplirTest(false);
  } else if (echec) {
    regler(2, -1, 2); zoneVerdict.className = "verdict echec"; zoneVerdict.replaceChildren(el("div", { class: "titre-verdict" }, "Pas de verdict"), el("div", { class: "phrase" }, "L'appel au MCP a échoué : rien n'est conclu."));
    pourquoi.append(el("p", { class: "regle" }, `Échec : ${echec}. Fail-closed : sans verdict, la facture reste impayable.`));
    remplirDecision(); remplirTest(false);
  } else {
    regler(2, -1); verdictAttente("Pas encore analysée");
    pourquoi.append(el("p", { class: "regle" }, "Lancez l'analyse : le MCP rendra un verdict et ses raisons."));
    remplirDecision(); remplirTest(false);
  }
  return {
    lignes,
    reveler: () => {
      verdictFinal(); remplirPourquoi(true); remplirTest(true);
      facture.classList.remove("entre", "c-attente"); facture.classList.add(classe(statut));
      surtitre.textContent = "Analyse du MCP";
      trace.append(elementTrace(entree, f, true));
      const reponse = etat.journal.find((x) => x.action === "reponse_mcp" && x.id > entree.id && (x.facture_id === f.id || !x.facture_id));
      if (reponse) trace.append(elementTrace(reponse, f, true));
      regler(5, 5);
      remplirDecision(); etapesDecision();
    },
  };
}

async function lancerAnalyse(id) {
  try {
    etat.enAnalyse.add(id); etat.echecs.delete(id);
    afficherBoite(); afficherScene();
    await appelApi("POST", `/api/factures/${encodeURIComponent(id)}/analyse`);
  } catch (e) { etat.enAnalyse.delete(id); afficherMessage(e.message, "erreur"); afficherScene(); }
}

async function actionHumaine(bouton, appel, succes) {
  if (bouton) bouton.disabled = true;
  try { await appel(); afficherMessage(succes, "ok"); await rafraichirFactures(); afficherBoite(); afficherScene(); }
  catch (e) { afficherMessage(e.message, "erreur"); if (bouton) bouton.disabled = false; }
}

// ------------------------------------------------------------------ page Jeu de test

function afficherExemples() {
  const presents = new Set([...etat.factures.values()].filter(enBoite).map((f) => f.scenario).filter(Boolean));
  $("exemples").replaceChildren(...etat.exemples.map((x) => el("article", {
    class: `exemple ${classe(x.statut_attendu)}`, draggable: "true",
    ondragstart: (e) => { e.dataTransfer.setData("application/x-verif-exemple", x.id); e.dataTransfer.effectAllowed = "copy"; },
  },
    el("div", { class: "ligne-haut" }, el("span", { class: "id" }, `${x.id} · ${x.numero}`), badgeVerdict(x.statut_attendu)),
    el("div", { class: "titre" }, x.titre),
    el("div", { class: "piege" }, x.piege),
    el("div", { class: "infos" }, el("span", {}, x.nom_emetteur), el("b", {}, formaterMontant(x.montant, x.devise))),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "petit", disabled: etat.role !== "admin", onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { await deposerExemple(x.id); allerA("analyser"); }
        catch (err) { afficherMessage(err.message, "erreur"); e.currentTarget.disabled = false; }
      } }, presents.has(x.id) ? "Redéposer" : "Déposer et analyser"),
      el("a", { class: "bouton secondaire petit", href: x.url, download: x.nom_fichier }, "PDF")))));
}

let minuteurDemo = null;
async function demoComplete() {
  const bouton = $("bouton-demo-complete");
  if (!bouton.classList.contains("confirmer")) {
    bouton.classList.add("confirmer"); bouton.textContent = "Confirmer : vider la boîte et lancer ?";
    minuteurDemo = setTimeout(() => { bouton.classList.remove("confirmer"); bouton.textContent = "Démo complète : déposer les 16 et analyser"; }, 4000);
    return;
  }
  clearTimeout(minuteurDemo);
  bouton.classList.remove("confirmer"); bouton.disabled = true; bouton.textContent = "Dépôt des factures…";
  try { await executerDemoComplete(); }
  catch (e) { afficherMessage(e.message, "erreur"); }
  finally { bouton.disabled = false; bouton.textContent = "Démo complète : déposer les 16 et analyser"; }
}

async function viderBoite() {
  interrompre(); etat.file = []; await attendreFinLecture();
  await appelApi("POST", "/api/demo/reinitialiser?jeu_de_test=false");
  etat.apercu = null; afficherApercu();
  await chargerTout();
}

async function executerDemoComplete() {
  await viderBoite();
  allerA("analyser");
  for (const x of etat.exemples) await deposerExemple(x.id, { analyser: false });
  await appelApi("POST", "/api/analyses");
  afficherMessage("Les 16 factures sont déposées : le MCP les analyse.", "ok");
}

// ------------------------------------------------------------------ pages Fournisseurs et Journal

async function afficherFournisseurs() {
  try {
    const liste = await appelApi("GET", "/api/fournisseurs");
    etat.fournisseurs = new Map(liste.map((f) => [f.id, f]));
    const tableau = $("tableau-fournisseurs");
    tableau.classList.add("cartes");
    tableau.replaceChildren(
      el("thead", {}, el("tr", {}, ["Fournisseur", "SIRET", "TVA", "IBAN de référence", "Contre-appel", "Factures"].map((t) => el("th", {}, t)))),
      el("tbody", {}, liste.map((f) => el("tr", {},
        el("td", { "data-libelle": "Fournisseur" }, el("span", {}, el("b", {}, f.nom), el("div", { class: "aide" }, f.adresse || ""))),
        el("td", { class: "mono", "data-libelle": "SIRET" }, f.siret), el("td", { class: "mono", "data-libelle": "TVA" }, f.tva || "—"),
        el("td", { class: "mono", "data-libelle": "IBAN de référence" }, f.iban_reference),
        el("td", { "data-libelle": "Contre-appel" }, f.telephone_reference || "—"),
        el("td", { class: "nombre", "data-libelle": "Factures" }, `${f.factures_payees} payées / ${f.nombre_factures}`)))));
  } catch (e) { afficherMessage(e.message, "erreur"); }
}

function categorie(e) {
  if (e.acteur === "mcp" || ["analyse_demandee", "reponse_mcp", "verification"].includes(e.action)) return "mcp";
  if (["validation_humaine", "paiement_simule", "changement_iban"].includes(e.action)) return "humain";
  if (e.action === "depot") return "depot";
  return "systeme";
}

function afficherJournal() {
  $("filtres-journal").replaceChildren(...Object.entries(FILTRES_JOURNAL).map(([cle, libelle]) => el("button", {
    type: "button", class: "filtre", "aria-pressed": etat.filtreJournal === cle ? "true" : "false",
    onclick: () => { etat.filtreJournal = cle; afficherJournal(); } }, libelle)));
  const entrees = etat.journal.filter((e) => etat.filtreJournal === "tout" || categorie(e) === etat.filtreJournal).slice().reverse();
  $("liste-journal").replaceChildren(...(entrees.length ? entrees.map((e) => {
    const d = e.detail && typeof e.detail === "object" ? e.detail : {};
    let detail = "";
    if (e.action === "verification") detail = `${d.statut_mcp || ""} · ${(d.codes || []).join(", ") || "aucune alerte"}`;
    else if (e.action === "analyse_demandee") detail = `tools/call ${d.outil || ""} ${JSON.stringify(d.arguments || {})}`;
    else if (e.action === "reponse_mcp") detail = `${d.resultat || ""} en ${duree(d.duree_ms || 0)}${d.raison ? " · " + d.raison : ""}`;
    else if (e.action === "depot") detail = d.fichier ? `Fichier ${d.fichier}` : "Saisie manuelle";
    else if (e.action === "validation_humaine") detail = `${d.valideur || ""} : « ${d.commentaire || ""} »`;
    else if (e.action === "paiement_simule") detail = formaterMontant(d.montant, d.devise);
    const couleur = e.action === "verification" ? classe(e.statut) : `c-${e.action}`;
    return el("li", { class: couleur }, el("span", { class: "point", "aria-hidden": "true" }), el("span", { class: "heure" }, heure(e.horodatage)),
      el("div", {}, el("div", { class: "quoi" }, `${ACTIONS[e.action] || e.action}${e.facture_id ? " · " + e.facture_id : ""}`), el("div", { class: "detail" }, detail)),
      el("span", { class: "acteur" }, e.acteur));
  }) : [el("li", { class: "vide" }, "Aucune entrée.")]));
}

// ------------------------------------------------------------------ commandes

let minuteurReinit = null;
async function reinitialiser() {
  const bouton = $("bouton-reinitialiser");
  if (!bouton.classList.contains("confirmer")) {
    bouton.classList.add("confirmer"); bouton.textContent = "Confirmer ?";
    minuteurReinit = setTimeout(() => { bouton.classList.remove("confirmer"); bouton.textContent = "Réinitialiser"; }, 4000);
    return;
  }
  clearTimeout(minuteurReinit);
  bouton.classList.remove("confirmer"); bouton.textContent = "Réinitialiser"; bouton.disabled = true;
  try {
    interrompre(); etat.file = []; await attendreFinLecture();
    await appelApi("POST", "/api/demo/reinitialiser?jeu_de_test=false");
    etat.apercu = null; afficherApercu();
    await chargerTout();
    afficherMessage("Boîte de réception vidée : déposez une facture ou lancez la démo complète.", "ok");
  } catch (e) { afficherMessage(e.message, "erreur"); }
  finally { bouton.disabled = etat.role !== "admin"; }
}

function changerVitesse() {
  etat.vitesse = (etat.vitesse + 1) % VITESSES.length;
  const b = document.getElementById("bouton-vitesse");
  if (b) b.textContent = `Vitesse ×${VITESSES[etat.vitesse]}`;
}

async function basculerEnregistrement() {
  if (document.body.classList.contains("enregistrement")) { quitterEnregistrement(); return; }
  document.body.classList.add("enregistrement");
  $("message").hidden = true;
  try { await document.documentElement.requestFullscreen?.(); } catch { /* plein écran refusé : vue sans boutons quand même */ }
}
function quitterEnregistrement() {
  document.body.classList.remove("enregistrement");
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
}

function brancherDepot() {
  const zone = $("zone-depot");
  const actif = (e) => { e.preventDefault(); zone.classList.add("survol"); };
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, actif));
  ["dragleave", "dragend"].forEach((t) => zone.addEventListener(t, () => zone.classList.remove("survol")));
  zone.addEventListener("drop", async (e) => {
    e.preventDefault(); zone.classList.remove("survol");
    const exemple = e.dataTransfer.getData("application/x-verif-exemple");
    if (exemple) { try { await deposerExemple(exemple); } catch (err) { afficherMessage(err.message, "erreur"); } return; }
    const fichier = e.dataTransfer.files && e.dataTransfer.files[0];
    if (fichier) await deposerFichier(fichier);
  });
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === zone) $("champ-fichier").click(); });
  $("bouton-parcourir").addEventListener("click", () => $("champ-fichier").click());
  $("champ-fichier").addEventListener("change", async (e) => { await deposerFichier(e.target.files[0]); e.target.value = ""; });
  $("bouton-saisie").addEventListener("click", () => {
    etat.apercu = { champs: { devise: "EUR" }, manquants: [], fichier: null }; afficherApercu();
  });
  $("case-auto").addEventListener("change", (e) => ecrireSession(AUTO_STOCKAGE, e.target.checked ? "1" : "0"));
}

// ------------------------------------------------------------------ pitch : diapositives

const DUREE_PITCH_S = 8 * 60;
const pitch = { index: 0, debut: null, minuteur: null };
const diapos = () => [...document.querySelectorAll("#diapos .diapo")];

function afficherDiapo(i) {
  const liste = diapos();
  if (!liste.length) return;
  pitch.index = Math.max(0, Math.min(liste.length - 1, i));
  liste.forEach((d, n) => { d.classList.toggle("active", n === pitch.index); d.setAttribute("aria-hidden", n === pitch.index ? "false" : "true"); });
  const d = liste[pitch.index];
  $("diapo-compteur").textContent = `${pitch.index + 1} / ${liste.length}`;
  $("diapo-titre").textContent = d.dataset.titre || "";
  $("diapo-temps").textContent = d.dataset.temps || "";
  $("diapo-progression").style.width = `${((pitch.index + 1) / liste.length) * 100}%`;
  const notes = d.querySelector(".notes");
  $("zone-notes").textContent = notes ? notes.textContent.trim() : "";
  $("diapo-prec").disabled = pitch.index === 0;
  $("diapo-suiv").disabled = pitch.index === liste.length - 1;
  ecrireSession("crm_diapo", String(pitch.index));
}
function changerDiapo(delta) {
  if (delta > 0 && !pitch.debut) basculerChrono();
  afficherDiapo(pitch.index + delta);
}
function majChrono() {
  const s = pitch.debut ? Math.floor((Date.now() - pitch.debut) / 1000) : 0;
  const b = $("pitch-chrono");
  b.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} / 8:00`;
  b.classList.toggle("depasse", s > DUREE_PITCH_S);
}
function basculerChrono() {
  clearInterval(pitch.minuteur);
  if (pitch.debut) { pitch.debut = null; pitch.minuteur = null; }
  else { pitch.debut = Date.now(); pitch.minuteur = setInterval(majChrono, 1000); }
  majChrono();
}
function basculerNotes() {
  const z = $("zone-notes");
  z.hidden = !z.hidden;
  $("pitch-notes").setAttribute("aria-pressed", z.hidden ? "false" : "true");
}

async function lancerDemoPitch(bouton) {
  const cible = bouton.dataset.demo;
  bouton.disabled = true;
  try {
    if (cible === "tout") await executerDemoComplete();
    else { await viderBoite(); allerA("analyser"); await deposerExemple(cible); }
  } catch (e) { afficherMessage(e.message, "erreur"); }
  finally { bouton.disabled = false; }
}

// ------------------------------------------------------------------ pitch : l'agent d'achat (commerce agentique)

const agent = { offres: [], produit: "", minuteur: null, debut: 0 };
const ORDRE_NIVEAUX = { BLOQUANT: 0, A_VERIFIER: 1, INFO: 2 };

function raisonsOffre(f) {
  const v = f && f.derniere_verification;
  const alertes = v && Array.isArray(v.alertes) ? v.alertes : [];
  return alertes.filter((a) => a.niveau !== "INFO")
    .sort((a, b) => (ORDRE_NIVEAUX[a.niveau] ?? 3) - (ORDRE_NIVEAUX[b.niveau] ?? 3))
    .slice(0, 3).map((a) => ({ niveau: connu(NIVEAUX, a.niveau) ? a.niveau : "INFO", texte: connu(CODES, a.code) ? CODES[a.code][0] : a.code }));
}
const statutOffre = (o) => (o.facture ? o.facture.statut : "recue");
const parPrix = (a, b) => { const x = centimes(a.montant) ?? 0n, y = centimes(b.montant) ?? 0n; return x < y ? -1 : x > y ? 1 : 0; };

function afficherOffres() {
  const offres = agent.offres.slice().sort(parPrix);
  $("agent-offres").replaceChildren(...offres.map((o, i) => {
    const s = statutOffre(o);
    const enCours = s === "recue";
    const raisons = enCours ? [] : raisonsOffre(o.facture);
    return el("article", { class: `offre ${enCours ? "c-indigo" : classe(s)}` },
      el("div", { class: "offre-haut" }, el("span", { class: "offre-boutique" }, o.boutique), i === 0 ? el("span", { class: "offre-rang" }, "le moins cher") : null),
      el("div", { class: "offre-prix" }, formaterMontant(o.montant, "EUR")),
      el("div", { class: "offre-argument" }, o.argument),
      el("div", { class: "offre-vendeur" }, o.nom_emetteur),
      enCours ? badgeAnalyse() : badgeVerdict(s),
      el("ul", { class: "offre-raisons" }, enCours
        ? [el("li", { class: "c-INFO" }, "SIRET, TVA, IBAN, sanctions, procédures, ancienneté…")]
        : raisons.length ? raisons.map((r) => el("li", { class: `c-${r.niveau}` }, icone(FORMES_NIVEAU[r.niveau]), r.texte))
          : [el("li", { class: "c-OK" }, icone("rond"), "Aucune alerte dans les sources officielles")]),
      enCours ? null : el("button", { type: "button", class: "lien-detail", onclick: () => voirDetail(o.facture_id) }, "Voir l'analyse du MCP →"));
  }));
}

function voirDetail(id) {
  if (!etat.factures.has(id)) return;
  etat.focus = id;
  allerA("analyser");
  afficherBoite(); afficherScene();
}

function afficherDecisionAgent() {
  const offres = agent.offres.slice().sort(parPrix);
  const sures = offres.filter((o) => statutOffre(o) === "verifiee");
  const moinsCher = offres[0];
  const z = $("agent-decision");
  const contenu = [];
  if (sures.length) {
    const choix = sures[0];
    const paye = choix.facture && choix.facture.statut === "payee";
    contenu.push(el("div", { class: "decision-choix c-verifiee" }, icone("rond"),
      el("span", {}, el("b", {}, `L'agent propose : ${choix.boutique}, ${formaterMontant(choix.montant, "EUR")}.`),
        paye ? " Achat confirmé par l'utilisateur (paiement simulé)." : " Le paiement attend votre confirmation."),
      paye ? null : el("button", { type: "button", class: "vert petit", onclick: (e) => confirmerAchat(e.currentTarget, choix) }, "Confirmer l'achat (simulé)")));
  } else {
    contenu.push(el("div", { class: "decision-choix c-a_verifier_humain" }, icone("triangle"), el("b", {}, "Aucune offre sans alerte : l'agent demande à l'humain.")));
  }
  if (moinsCher && statutOffre(moinsCher) !== "verifiee") {
    contenu.push(el("p", { class: "decision-sans" },
      `Sans MCP, l'agent aurait pris l'offre la moins chère : ${formaterMontant(moinsCher.montant, "EUR")} envoyés à ${moinsCher.boutique}, ` +
      `verdict « ${verdict(statutOffre(moinsCher)).titre.toLowerCase()} ».`));
  }
  z.replaceChildren(...contenu);
  z.hidden = false;
}

async function confirmerAchat(bouton, offre) {
  bouton.disabled = true;
  try {
    await appelApi("POST", `/api/factures/${encodeURIComponent(offre.facture_id)}/paiement`);
    offre.facture = await appelApi("GET", `/api/factures/${encodeURIComponent(offre.facture_id)}`);
    afficherOffres(); afficherDecisionAgent();
  } catch (e) { afficherMessage(e.message, "erreur"); bouton.disabled = false; }
}

async function lancerAgent() {
  const b = $("bouton-agent");
  b.disabled = true; b.textContent = "L'agent fait vérifier les vendeurs…";
  $("agent-decision").hidden = true;
  try {
    const r = await appelApi("POST", "/api/demo/agent-achat");
    agent.offres = r.offres; agent.produit = r.produit; agent.debut = Date.now();
    $("agent-message").textContent = `3 offres trouvées pour « ${r.produit} ». Avant de payer, j'appelle l'outil MCP traiter_factures_crm pour chaque vendeur.`;
    afficherOffres(); suivreAgent();
  } catch (e) { afficherMessage(e.message, "erreur"); b.disabled = false; b.textContent = "Lancer l'agent d'achat"; }
}

function suivreAgent() {
  clearInterval(agent.minuteur);
  agent.minuteur = setInterval(async () => {
    try {
      const factures = await Promise.all(agent.offres.map((o) => appelApi("GET", `/api/factures/${encodeURIComponent(o.facture_id)}`)));
      factures.forEach((f, i) => { agent.offres[i].facture = f; });
      afficherOffres();
      const fini = factures.every((f) => f.statut !== "recue");
      if (fini || Date.now() - agent.debut > 90000) {
        clearInterval(agent.minuteur); agent.minuteur = null;
        if (fini) afficherDecisionAgent(); else afficherMessage("Le MCP n'a pas répondu à temps : rien n'est conclu, rien n'est payé.", "erreur");
        const b = $("bouton-agent"); b.disabled = false; b.textContent = "Relancer l'agent";
      }
    } catch { /* nouvel essai au prochain tour */ }
  }, 900);
}

function brancherPitch() {
  $("diapo-prec").addEventListener("click", () => changerDiapo(-1));
  $("diapo-suiv").addEventListener("click", () => changerDiapo(1));
  $("pitch-chrono").addEventListener("click", basculerChrono);
  $("pitch-notes").addEventListener("click", basculerNotes);
  $("pitch-plein-ecran").addEventListener("click", basculerEnregistrement);
  $("bouton-retour-pitch").addEventListener("click", () => { location.hash = "pitch"; allerA("pitch"); });
  $("bouton-agent").addEventListener("click", lancerAgent);
  document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => lancerDemoPitch(b)));
  const demande = Number(new URLSearchParams(location.search).get("diapo"));     // lien direct : /?diapo=9#pitch
  const memorise = Number(lireSession("crm_diapo"));
  pitch.index = Number.isInteger(demande) && demande > 0 ? demande - 1 : Number.isInteger(memorise) ? memorise : 0;
  majChrono();
  document.addEventListener("keydown", (e) => {
    if (etat.page !== "pitch" || !document.body.classList.contains("connecte")) return;
    if (e.altKey || e.ctrlKey || e.metaKey || (e.target.closest && e.target.closest("input, textarea, select"))) return;
    const touche = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (["ArrowRight", "PageDown", " "].includes(touche)) { e.preventDefault(); changerDiapo(1); }
    else if (["ArrowLeft", "PageUp"].includes(touche)) { e.preventDefault(); changerDiapo(-1); }
    else if (touche === "Home") afficherDiapo(0);
    else if (touche === "End") afficherDiapo(diapos().length - 1);
    else if (touche === "f") basculerEnregistrement();
    else if (touche === "n") basculerNotes();
  });
}

// ------------------------------------------------------------------ démarrage

document.addEventListener("DOMContentLoaded", () => {
  $("formulaire-connexion").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cle = $("champ-cle").value.trim();
    if (!cle) return;
    try { await connecter(cle); $("message").hidden = true; }
    catch (err) { if (err.statut !== 401) afficherMessage(err.message, "erreur"); }
  });
  $("bouton-deconnexion").addEventListener("click", () => deconnecter());
  $("bouton-reinitialiser").addEventListener("click", reinitialiser);
  $("bouton-enregistrement").addEventListener("click", basculerEnregistrement);
  $("bouton-analyser-tout").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { await appelApi("POST", "/api/analyses"); for (const f of etat.factures.values()) if (f.statut === "recue") etat.enAnalyse.add(f.id); afficherBoite(); afficherScene(); }
    catch (err) { afficherMessage(err.message, "erreur"); }
  });
  $("bouton-demo-complete").addEventListener("click", demoComplete);
  brancherDepot();
  brancherPitch();
  window.addEventListener("hashchange", () => { if (etat.role) allerA(location.hash.slice(1)); });
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) document.body.classList.remove("enregistrement"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") quitterEnregistrement(); });
  // clé mémorisée dans l'onglet, sinon mode présentation (sans clé) ; à défaut, l'écran de connexion reste affiché
  connecter(lireSession(CLE_STOCKAGE) || null).catch((e) => { if (e.statut !== 401) afficherMessage(e.message, "erreur"); });
});
