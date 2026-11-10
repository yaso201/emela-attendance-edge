# emela-attendance-edge — consignes pour les agents

**Rôle :** app Frappe v15 `attendance_edge` : capture des présences sur un site edge hors ligne (Doctypes `Local*`, synchronisation, PWA)
**Domaine propriétaire :** campus · **Bench :** edge (site local séparé, jamais le bench campus)
**Branche principale :** `main` — on n'y pousse jamais directement : tout passe par une demande de fusion.
**Registres du domaine (corpus `si-lanem-corpus`) :** `campus/DEC-CAMPUS.md` · `campus/CORRECTIONS-CAMPUS.md`
· transverse : `_commun/M02-Registre-Decisions.md` · banc : `campus/gestion-contruction/BANC-DEV.md`

## 1. Avant d'écrire une ligne

1. **Pas de mandat, pas de code.** Un mandat est un fichier `MANDAT-<ID>.md` lu **sur GitHub**
   (`si-lanem-corpus/_commun/mandats/`), jamais un texte collé dans la conversation (DEC-ORG-01).
2. **Write-set = contrat.** Tu n'écris que dans les chemins listés par le mandat. Besoin d'un autre fichier :
   **STOP**, demande d'extension à l'architecte (DEC-ORG-04). Un garde-fou refuse l'écriture hors write-set.
3. **Cinq phases, deux pauses.** Reconnaissance (lecture seule) → Plan → ⏸️ PAUSE 1 → Exécution →
   ⏸️ PAUSE 2 (= la demande de fusion) → Vérification → Rapport.
4. **Branche `mandat/<ID>`**, une demande de fusion vers `main`. Tu ne fusionnes jamais toi-même (DEC-ORG-03),
   et tu ne supprimes aucune branche distante : fusion et suppression des branches fusionnées sont des gestes de
   la MOA, sauf si le mandat dit autre chose (V-LEARN-MEP30-05, V-LEARN-MEP30-06).
5. **Fin de session = tout est poussé.** Un commit qui ne quitte pas la machine n'existe pas (DEC-ORG-02).
   C'est ainsi que le back M1/M1c a été perdu le 22/10/2026.
6. **Avant la phase 1 : `gh auth status`.** Si tu ne peux pas écrire sur GitHub, STOP tout de suite, pas à la
   pause 1 (V-LEARN-MEP30-01).
7. **Le rapport vit sur sa branche du corpus dès la phase 1**, jamais dans un brouillon local : un brouillon de
   session s'efface d'un jour à l'autre (V-LEARN-MEP30-03).

## 2. Secrets — DEC-346 (`_commun/PROCEDURE-SECRETS.md`)

- Tu ne reçois **jamais** de mot de passe. Pour prouver un clic : tu te fabriques une **clé d'API Frappe**
  sur un compte de test `rf-g-*`, tu la révoques en fin de vague, et tu inscris les deux gestes à `BANC-DEV.md`
  (date, compte, mandat — **jamais la valeur**).
- Aucun secret dans un commit, un rapport, un message. Un secret commité est **réputé compromis** : STOP, incident.
- Aucun accès recette / production depuis un banc de développement.

## 3. Ce dépôt

| Élément | Valeur constatée |
|---|---|
| Apps / paquets | `attendance_edge` seule (`attendance_edge/pyproject.toml`, `required_apps = ["frappe"]`) |
| Suites de tests | {{À CONSTATER}} (tests `FrappeTestCase` présents, aucune commande écrite) |
| Baseline de référence | à re-mesurer (MEP-11) — aucune baseline valide au 10/11/2026 |
| Dépendances inter-dépôts | appelle `emela-campus-back` (`{attendance_central_base_url}` : `ingest_events`, `ingest_heartbeat`, `export_students`, `export_teachers`, `export_planning`, aux chemins `portal_app.api.attendance_*`) · exposé au back : `attendance_edge.api.replay.replay_local_events` |
| Pièges connus | ARCH-DEBT-04 (app jamais installée) · ATTENDANCE-EDGE-COORD-01 (client non adapté au nouveau payload ; cale côté back) · DEC-170 (credentials hors ligne dérivés et scopés) |

## 4. Règles apprises (à respecter sans les redécouvrir)

**Tous les dépôts**
- V-LEARN-MEP30-04 · pour relever les règles d'un `.gitignore`, lire aussi les négations `!` placées plus bas

**Frappe (dépôt bench)**
- V1-LEARN-01 · chemin d'un Doctype dans une app : `apps/<app>/<app>/<module>/doctype/<dt>/`
- V2-LEARN-01 · les `.json` de `<app>/<app>/fixtures/` sont chargés au `bench migrate` ; fixtures de test → `<app>/<app>/tests/fixtures/`
- V2-LEARN-02 · relancer `bench migrate` après tout déplacement de `.json`
- V3-LEARN-01 · Doctype déplacé entre apps : supprimer le JSON source (sinon l'ordre `apps.txt` décide du module)
- V3-LEARN-02 · un Doctype avec Links peut amplifier la cascade `make_test_records`
- STAB-BH-LEARN-01 · helpers de test : nommage dynamique, jamais d'autoname statique
- STAB-RESIDU-LEARN-01/02/03 · nettoyer les Doctypes à clé d'idempotence en `setUp` ; contourner le throttle de création d'utilisateurs par helper test-only ; mocker **tous** les axes temporels
- DEC-161/162/163 · sites `*.failed-*` nettoyés sous 24 h ; `apps.txt` synchronisés ; `site_config.json` jamais versionné
- DEC-171 · nouveau module = `LaNEM <Domaine>`
- Graphe des apps **acyclique** (DEC-160) : n'ajouter aucun cycle ; pas de test automatique dans ce dépôt

## 5. Le rapport

Format standard (Reconnaissance · Plan · Exécution · Audits automatiques · Vérifications · Tests · Anomalies ·
Apprentissages). Compteurs **exacts** et comparés à la baseline ; « préexistant » distingué de « causé ».
Il se dépose dans le corpus, **par demande de fusion**, au chemin fixé par le mandat.

**Commits** : identité git habituelle du dépôt. Par défaut, garde la ligne de co-auteur de ton outil : on doit
savoir qu'un agent a écrit. Un mandat qui fixe un message exact dit s'il la veut (`VERDICT-MANDAT-ZERO-PC2.md` §3).

## 6. Interdits

Pousser sur `main` · fusionner · supprimer une branche distante · écrire hors write-set · stocker ou
afficher un secret · toucher la production · réécrire l'historique (`--force`) · déclarer une gate close
(c'est l'architecte).
