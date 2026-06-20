# Emendator — Fabric Conflict Analyzer (Brief projet MVP)

> Document de contexte destiné à Claude Code. Il définit le problème, les partis pris
> d'architecture, les murs connus et le découpage MVP. À traiter comme source de vérité :
> chaque phase est livrable indépendamment et construit sur la précédente.
>
> **Nom du projet : Emendator** — du latin _emendator_, « celui qui ôte les défauts »
> (_emendare_ : retirer les tares). L'app détecte et résout les conflits d'un modpack Fabric.

---

## 1. Problème

Monter de gros modpacks Fabric (200–400 mods) provoque des conflits difficiles à diagnostiquer.
Depuis la 1.13, les registres sont namespacés (`modid:item`) : les collisions d'**IDs numériques**
historiques ont disparu. Les conflits restants sont d'une autre nature :

- **Duplication de contenu** : plusieurs mods ajoutent la même ressource (cuivre, étain…).
- **Conflits de recettes** : recettes de craft qui se chevauchent sur la même grille.
- **Conflits de mixins** : deux mods patchent la même méthode vanilla de façon incompatible
  (échec d'application = crash au chargement). C'est le cas le plus pénible.
- **Dépendances / versions** : incompatibilités, jars en double.

L'outillage existant est **fragmenté et réactif** (post-crash) : Almost Unified (unification de
contenu), YARCF (recettes), Crash Assistant / MCDoctor.ai (analyse de log après crash), launchers
no-code pour _installer_. Personne ne fait l'**analyse pré-lancement agrégée** ni la **bisection
automatisée** des conflits.

## 2. Objectif

Une **application desktop** qui prend un dossier `mods/` Fabric et :

1. produit une **carte de conflits** par analyse statique (rapide, hors-ligne) ;
2. **confirme avec certitude** les conflits de chargement en bootant un vrai serveur Fabric
   headless dans un conteneur isolé ;
3. **isole les paires coupables** par bisection automatisée quand un boot crashe ;
4. **génère les configs de résolution** no-code (unify.json d'Almost Unified, overrides de
   recettes en datapack).

## 3. Parti pris architectural fondamental

**Un conflit n'est pas une propriété d'un jar, c'est une propriété d'un ENSEMBLE.**
Sandboxer chaque jar isolément ne révèle aucun conflit cross-mod : un mixin ne casse que lorsque
les deux mods sont présents et que le loader applique les deux transformateurs sur la même classe.
L'unité de test est donc **le set complet (ou un sous-ensemble) booté ensemble**, jamais un jar seul.

**Stratégie hybride :**

- **Statique** pour trier vite et gratuitement (tags, recettes, cibles mixin déclarées).
- **Runtime headless** pour trancher avec certitude sur les conflits de chargement, et **bisection**
  pour localiser les paires.

Le statique ne lance un boot que sur les cas ambigus → on minimise le nombre de boots (coûteux).

## 4. Stack

| Couche             | Choix                                  | Notes                                                                                                                                                                                         |
| ------------------ | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shell desktop      | **Tauri + React/Vite (TS)**            | Léger ; front TS identique à l'habitude. Surface Rust limitée à la config + commandes de spawn de l'orchestrateur Python. Alternative : Electron (100 % TS+Python) si le Rust devient gênant. |
| Backend local      | **FastAPI (Python)**                   | Même forme que `papers-helper`. Expose l'API que le front consomme ; pilote Docker et le parsing.                                                                                             |
| Analyseur statique | Python (`zipfile` + parsing JSON)      | Dézippe les jars, lit métadonnées / mixins / recipes / tags. Consomme le **profil de version** (§6).                                                                                          |
| Runner runtime     | **Docker** (1 conteneur par boot)      | Image Fabric serveur headless, mods injectés, logs capturés. JDK et artefacts pilotés par le profil de version (§6).                                                                          |
| Parsing de logs    | Réutiliser les patterns MCLA / mclo.gs | Ne pas réinventer la classification d'erreurs.                                                                                                                                                |

**Décision par défaut : Tauri.** C'est aussi un objectif d'apprentissage assumé. Electron reste le
plan de repli si le poids du couplage Rust ⇄ Python sidecar devient un frein.

## 5. Périmètre MVP

**Version cible : `1.21.1`** (bloc 1.21–1.21.1). Choix verrouillé pour le MVP car cohérent avec les
conventions modernes déjà adoptées dans ce doc : Java 21, items en **components**, dossiers datapack
au **singulier** (`recipe/`, `advancement/`), tags `c:`. Toute constante dépendante de la version
passe par le **profil de version** (§6) — jamais de hardcode.

**Dans le périmètre :**

- Loader **Fabric uniquement** (pas Forge/NeoForge au MVP — formats de métadonnées différents).
- Boot **serveur** headless (pas de client headless au MVP).
- Détection : duplication de contenu (tags), collisions de recettes, conflits de mixins au
  chargement, dépendances/versions, jars en double.
- Génération : `unify.json` (Almost Unified), datapack d'override de recettes.

**Hors périmètre (assumé, à documenter dans l'UI) :**

- Mods **client-only** (`environment: client`) : non chargés par un serveur Fabric → conflits
  visuels (rendu, shaders, HUD) non testables au MVP. Lire le champ `environment` et afficher
  « N mods non testables en mode serveur ».
- Conflits **silencieux** : deux mixins qui cohabitent sans crasher mais cassent le comportement.
  Non détectables sans assertions de gameplay (modèle gametest type PackTest). Hors MVP.
- Forge / NeoForge, client headless (Xvfb / GL offscreen), autres blocs de versions : itérations
  futures (s'ajoutent comme profils + adaptateurs, pas comme réécriture).

## 6. Profil de version (contrat — Phases 1 et 2)

Les constantes dépendantes de la version ne sont **jamais codées en dur**. Elles vivent dans un
profil que l'analyseur statique (Phase 1) et le runner (Phase 2) consomment tous les deux. MVP =
profil `1.21.1`.

```jsonc
{
  "profile": "1.21.1",
  "jdk": "21", // image Docker du runner
  "itemFormat": "components", // components | nbt
  "datapackFolders": "singular", // singular | plural
  "recipePath": "data/{mod}/recipe", // pré-1.21 : data/{mod}/recipes
  "tagPath": "data/{mod}/tags/items", // les tags restent au pluriel à toutes les versions
  "tagNamespace": "c", // c (1.21+) | forge (ancien)
  "fabricApi": "<version exacte>", // artefact version-exact requis par le runner
}
```

**Ajouter un bloc plus tard = ajouter un profil, pas réécrire la logique.** Ex. 1.20.1 :
`jdk:17`, `itemFormat:nbt`, `datapackFolders:plural`, `recipePath:data/{mod}/recipes`,
`tagNamespace:forge`.

Repère des blocs (les ruptures qui changent le profil) :

| Bloc              | jdk    | itemFormat     | datapackFolders | État modding                                     |
| ----------------- | ------ | -------------- | --------------- | ------------------------------------------------ |
| 1.18 → 1.20.4     | 17     | nbt            | plural          | Très moddé ; 1.20.1 = base reine                 |
| 1.20.5 → 1.20.6   | 21     | components     | plural          | Transitionnel, peu moddé                         |
| **1.21 → 1.21.1** | **21** | **components** | **singular**    | **Cible MVP**                                    |
| 1.21.2+           | 21     | components     | singular        | Courant, churn de format mineur par version      |
| 26.1+             | 25     | components     | singular        | Récent (fin du préfixe « 1. »), écosystème jeune |

> Rappel : un bloc partage les **constantes de parsing** et l'**image JDK**, pas la
> substituabilité des jars. Le runner a besoin du jar serveur Fabric + Fabric API **exacts** de la
> version précise visée (ex. 1.21.1), même au sein du bloc.

## 7. Catégories de conflits — détection

| Catégorie              | Source statique                                                | Confirmation runtime                                  |
| ---------------------- | -------------------------------------------------------------- | ----------------------------------------------------- |
| Duplication de contenu | `tagPath` → chevauchements de tags                             | — (résolu par config)                                 |
| Collisions de recettes | `recipePath` → mêmes entrées/grille                            | Échec de désérialisation au load                      |
| Conflits de mixins     | `*.mixins.json` → cibles classe/méthode communes (heuristique) | **Export mixin post-transformation** = vérité terrain |
| Dépendances / versions | `fabric.mod.json` (depends, version cible)                     | Erreur de résolution au boot                          |
| Jars en double         | hash / modid dupliqué                                          | Refus de démarrage du loader                          |

**Mixins — passer de l'estimation à l'observation** via les flags JVM au boot :

- `-Dmixin.debug.export=true` → exporte les classes **après transformation** (qui a patché quoi).
- `-Dmixin.debug.verbose=true` et `-Dmixin.checks=true` → détail des applications/conflits.

On construit la carte de chevauchement à partir de ce que le loader a _réellement fait_, pas des
cibles déclarées.

## 8. Le runner runtime (cœur du projet)

Pattern prouvé : un serveur Fabric tourne en headless via
`java -Xmx<N>G -jar fabric-server-launch.jar nogui`. Des images Docker Fabric serveur prêtes
existent (OpenJDK + version MC/loader paramétrables, EULA auto, RCON). La version Java provient du
profil (`jdk`).

**Boucle de boot (orchestrateur Python) :**

1. Préparer un conteneur : image Fabric serveur (jdk du profil) + Fabric API (version exacte) +
   sous-ensemble de mods injecté.
2. Lancer le boot, flags de debug mixin activés, timeout.
3. Le serveur charge : mixins → freeze des registres → datapacks/recettes. On n'a pas besoin
   d'aller plus loin (pas de gameplay) ; couper après le freeze des registres / chargement monde.
4. Capturer `latest.log`, `crash-reports/`, export mixin → **classifier** : OK / crash + cause.

**Sécurité :** exécuter des jars = code arbitraire. Isolation par conteneur (filesystem + réseau
restreints), jamais en direct sur l'hôte.

**Bisection :** quand un set crashe, binary-search → ~log2(N) boots pour isoler la **paire coupable**
(~9 boots pour 400 mods). C'est la feature différenciante : automatiser ce que les devs de pack
font à la main.

**Coût à assumer :** chaque boot d'un gros pack = minutes + RAM importante. La bisection limite le
_nombre_ de boots, pas leur poids unitaire.

## 9. Modèle de données — carte de conflits

Sortie pivot de l'analyseur statique ET du runner (format unifié, consommé par le front et par le
générateur de résolutions). Esquisse :

```jsonc
{
  "profile": "1.21.1", // profil de version utilisé pour cette analyse
  "mods": [
    {
      "id": "examplemod",
      "version": "1.2.0",
      "mcVersion": "1.21.1",
      "environment": "server" /* server | client | "*" */,
      "depends": { "fabric-api": "*" },
      "jar": "examplemod-1.2.0.jar",
    },
  ],
  "conflicts": [
    {
      "type": "tag_overlap", // tag_overlap | recipe_collision | mixin_overlap | dependency | duplicate_jar
      "severity": "info", // info | warning | error
      "detectedBy": "static", // static | runtime
      "members": ["modA", "modB"], // mods impliqués
      "detail": {
        "tag": "c:tin_ingots",
        "items": ["modA:tin_ingot", "modB:tin_ingot"],
      },
      "resolution": {
        "strategy": "almost_unified", // almost_unified | recipe_override | manual | remove_duplicate
        "generated": "config/almostunified/unify.json",
      },
    },
  ],
  "untestable": [
    {
      "id": "shadermod",
      "reason": "environment:client not loaded by server boot",
    },
  ],
}
```

## 10. Découpage MVP (à piloter par Claude Code)

Chaque phase est **shippable** et a un critère d'acceptation clair.

**Phase 0 — Socle**
Scaffolding Tauri + React/Vite (TS) ; FastAPI local ; ingestion d'un dossier `mods/` ;
parsing `fabric.mod.json` → liste des mods + versions + `environment` affichée dans l'UI.
_DoD :_ déposer un dossier, voir la liste des mods et le compte de mods non testables.

**Phase 1 — Analyseur statique**
Charge le **profil de version** (§6, profil `1.21.1` au MVP) — aucune constante de chemin/format
codée en dur. Dézippage des jars ; détection tag*overlap, recipe_collision, mixin_overlap (déclaré),
dependency, duplicate_jar ; production de la **carte de conflits** (§9) ; rendu UI triable.
\_DoD :* sur un set réel 1.21.1, carte de conflits cohérente, 100 % hors-ligne, sous quelques secondes ;
changer de profil ne demanderait aucune modif de logique.

**Phase 2 — Runner headless**
Conteneur Docker Fabric serveur dont le JDK et le Fabric API viennent du profil ; boot d'un set
donné avec flags mixin debug ; capture + classification du log (OK / crash + cause). Pas encore de
bisection.
_DoD :_ bouton « tester ce set » → verdict fiable avec cause extraite du log, sur la cible 1.21.1.

**Phase 3 — Bisection automatisée**
Quand un boot crashe : binary-search orchestré jusqu'à la/les paire(s) coupable(s) ;
report dans la carte de conflits (`detectedBy: runtime`).
_DoD :_ sur un conflit connu injecté, la paire est isolée automatiquement en ~log2(N) boots.

**Phase 4 — Résolution no-code**
Génération `unify.json` (tag*overlap) et datapack d'override (recipe_collision) ; prévisualisation
et export depuis l'UI.
\_DoD :* un conflit de duplication se résout par un fichier généré, sans écrire de code.

## 11. Conventions de travail

- Phases strictement incrémentales ; ne pas démarrer la suivante tant que le DoD n'est pas atteint.
- La **carte de conflits (§9)** est le contrat entre couches ; le **profil de version (§6)** est le
  contrat entre versions. Statique, runtime et générateur de résolutions s'y conforment tous.
- Tests : au minimum un set de fixtures de mods (réels ou factices) ciblés **1.21.1** reproduisant
  chaque catégorie de conflit, pour valider statique + runtime de façon déterministe.
- Boots runtime toujours en conteneur isolé, jamais sur l'hôte.
- Documenter explicitement dans l'UI tout ce qui est hors périmètre (mods client-only, conflits
  silencieux) pour ne pas donner une fausse impression d'exhaustivité.

## 12. Références / art antérieur

- **Almost Unified** — unification de contenu par tag dominant + réécriture de recettes ; cible de
  génération du MVP. Config `config/almostunified/unify.json`, `tagOwnerships`.
- **PackTest** — preuve du pattern serveur Fabric headless en CI (gametests via datapack).
- **Crash Assistant / MCDoctor.ai / MCLA (mclo.gs)** — classification d'erreurs de log à réutiliser.
- **Images Docker Fabric serveur** — base du runner (OpenJDK + loader paramétrable, `nogui`).
- **SpongePowered Mixin** — flags `mixin.debug.export`, `mixin.debug.verbose`, `mixin.checks`.

## 13. Glossaire

- **Mixin** : mécanisme d'injection de bytecode dans des classes vanilla/mod au chargement.
- **Tag** : regroupement d'items/blocs (`c:tin_ingots`) servant aux recettes ; clé de l'unification.
- **Item components** : format des données d'item depuis 1.20.5 (remplace l'ancien NBT).
- **Profil de version** : objet de constantes (jdk, format items, dossiers datapack, namespace de
  tags, Fabric API) qui découple la logique de l'outil de la version de Minecraft visée.
- **Freeze des registres** : moment du chargement où les registres deviennent immuables ; la plupart
  des conflits de chargement se manifestent avant/à ce point.
- **Bisection** : recherche dichotomique sur le set de mods pour isoler une paire coupable.
