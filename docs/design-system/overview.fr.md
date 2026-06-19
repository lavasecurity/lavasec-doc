---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Design system {#design-system}

> **Public visé :** les équipes design et ingénierie qui travaillent sur l'app iOS Lava Security.
> **Autorité :** quand ce doc et un plan ne sont pas d'accord, **c'est le code qui gagne** — les écarts sont signalés au fil du texte. Le statut reflète ce qui est réellement confirmé dans le code, pas ce qu'un plan espérait. Légende des statuts : **Implémenté** (livré et confirmé dans le code), **En cours** (partiellement en place), **Prévu** (conçu, pas encore construit), **Abandonné** (rejeté ou annulé).

Ce doc couvre la philosophie de design, le vocabulaire de profondeur LavaTier, la mascotte Lava, les conventions de copie et de nommage, l'UX d'onboarding et l'internationalisation. Pour la tuyauterie architecturale derrière ces surfaces (targets, cycle de vie du VPN, le câblage du modèle d'état Lava/protection), voir [le client iOS](../architecture/ios-client.md) ; pour le cadrage produit, voir [l'aperçu produit](../product/overview.md).

---

## 1. Philosophie : un cœur calme, une profondeur qui se mérite {#1-philosophy-calm-core-earned-depth}

Le public de Lava, ce sont des gens ordinaires sans bagage technique — des parents, des personnes âgées — et le design découle de là. La surface du quotidien « fonctionne, tout simplement » et reste calme pour tout le monde ; les détails en plus, le plaisir et le contrôle ne se dévoilent (**se méritent**) que si l'utilisateur va les chercher. Rien ne harcèle, rien n'alarme, et la mécanique technique reste invisible tant qu'on ne la cherche pas.

Ce modèle **« cœur calme, profondeur méritée »** se décline en trois profondeurs produit :

- **Calme** — la protection par défaut, qui marche toute seule et que tout le monde voit en premier.
- **Festif** — la prise de conscience et le plaisir, sur la base du volontariat (séries, déblocages, moments de réussite). Ne harcèle jamais.
- **Technique** — le DNS, les diagnostics et les stats. Invisibles tant que l'utilisateur ne va pas les chercher.

Deux règles transversales de palette et de ton soutiennent cette posture calme :

- **le rouge = danger uniquement.** Le rouge est réservé exclusivement au danger et à l'erreur ; la palette calme est en vert/orange. Comme ça le rouge reste digne de confiance comme vrai signal d'alarme. Le rouge danger est tokenisé sous `LavaStyle.dangerRed`, avec `LavaStyle.errorText` qui en est un alias (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) et qui est utilisé par le texte d'erreur dans les vues. La teinte de protection passe par la table de rôles sémantique `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) plutôt que par du `.green`/`.orange` brut. Il reste quand même quelques appels à `.red` brut (par ex. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — les migrer vers `LavaStyle.dangerRed` est le nettoyage qui reste à faire.
- **Pas de langage sécuritaire anxiogène.** La copie est simple, calme et pratique. Voir [§4 Copie et nommage](#4-copy-naming).

### La couche tokenisée qui existe aujourd'hui **(Implémenté)** {#the-tokenized-layer-that-exists-today-implemented}

Le design system est une vraie couche SwiftUI tokenisée, aux côtés du vocabulaire de profondeur `LavaTier` (§2) :

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la source de vérité des couleurs adaptatives : ~18 couleurs sémantiques (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), chacune produite par une seule fabrique `adaptiveColor(light:dark:)` pour que clair et sombre soient définis ensemble. Le rouge danger est tokenisé ici sous `dangerRed`/`errorText` (lignes 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — les rôles de surface carte/panneau/sélection et les rayons d'angle : `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — l'échelle d'espacement : `xs`/`sm`/`md`/`lg`/`xl` plus `screenHorizontal`/`screenTop`/`screenBottom`.

Le seul écart qui subsiste, c'est cette poignée d'appels à `.red` brut pas encore migrés vers `LavaStyle.dangerRed` (voir §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Implémenté)** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` est le vocabulaire de profondeur léger qui encode « cœur calme, profondeur méritée » directement dans la couche de tokens. C'est un vocabulaire plus quelques valeurs de tokens par défaut — pas un re-thème complet — et il est livré comme un enum à lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, câblé dans des surfaces représentatives plutôt que rajouté après coup à chaque vue.

| Niveau | Profondeur | Sens |
|---|---|---|
| **Floor** | calme | Protection qui marche toute seule pour tout le monde — la surface par défaut. |
| **Window** | festif | Prise de conscience et plaisir, sur la base du volontariat : séries, déblocages, moments de réussite. Ne harcèle jamais. |
| **Workshop** | technique | DNS, Nerd Stats, diagnostics. Invisibles tant qu'on ne les cherche pas. |

`LavaTier` est un enum `calm`/`celebratory`/`technical` qui porte des valeurs de tokens par défaut :

- une **couleur d'accent** (`accent`),
- `allowsDelightMotion` — vrai uniquement pour festif / Window,
- `usesMonospacedMetadata` — vrai uniquement pour technique / Workshop,

exposé via une `EnvironmentKey` plus un modificateur `.lavaTier(_:)` et un modificateur `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Il est câblé dans des surfaces représentatives — par ex. `.lavaTier(.technical)` et `.lavaTier(.celebratory)` dans lavasec-ios: LavaSecApp/SettingsView.swift — plutôt que dans chaque vue. Ce périmètre volontairement restreint garde les trois profondeurs produit lisibles dans le code et portables vers un futur consommateur Android sans avoir à redéduire l'intention.

> **Réserve (tokenisation de l'accent Prévue, Phase 3) :** `LavaColorRole` n'est pas encore créé, donc `LavaTier.accent` se résout toujours en couleurs `LavaStyle` brutes (LavaTokens.swift:~230). Traitez la tokenisation de la couleur d'accent comme une boucle ouverte, pas comme une surface terminée.

---

## 3. La mascotte Lava, le Soft Shield Guardian **(Implémenté)** {#3-the-soft-shield-guardian-mascot-implemented}

Le **Soft Shield Guardian** est la mascotte de Lava — un bouclier arrondi avec un visage simple qui se déforme — qui exprime visuellement l'état de protection sur l'onglet Protection, la Live Activity, la Dynamic Island et l'onboarding. C'est le porteur le plus visible du ton calme.

Le graphe d'états est indépendant de la plateforme, il vit dans `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift) ; le moteur de rendu SwiftUI est lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Les 7 états d'expression {#31-the-7-expression-states}

La mascotte a **exactement 7** états d'expression, régis par un graphe d'états à transitions autorisées (`GuardianMascotState.allowedNextStates`, verrouillé par lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift) :

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Des contraintes du graphe à connaître : la seule sortie de `sleeping` est `waking`, et `grateful` ne revient qu'à `awake`. Les transitions `awake ↔ grateful` ont des images d'interpolation sur mesure — c'est le seul moment de **delight motion** du système (niveau Window).

> **`retrying` vs `concerned` — la distinction de ton la plus importante.** Les deux signalent « pas en parfaite santé », mais ils se lisent très différemment et il ne faut surtout pas les confondre :
> - **`retrying`** est le visage *serein, qui se répare tout seul* : paupières relâchées (~0,80), yeux à l'horizontale, bouche plate, et **aucune inclinaison d'inquiétude**. Le mouvement est porté par le **badge de statut, pas par le visage** — une auto-récupération passagère ne devrait jamais alarmer. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** est une inquiétude *douce, qui demande de l'aide* : sourcils internes relevés (`concernAmount` 1, `mouthCurve` -0.22) qui se lit comme « un coup de main ne me ferait pas de mal », **jamais un regard sévère**. Un vrai problème devrait inviter à aider, pas gronder. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Connectivité → expression (6 → 4) {#32-connectivity-expression-mapping-6-4}

La santé de la protection est évaluée dans `LavaSecCore` comme **6 niveaux de gravité de connectivité** + 2 actions (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift) :

- **Gravités :** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Actions :** `turnOff`, `reconnect`

L'onglet Protection ramène ces 6 gravités à **4 visages** (`guardianState` dans lavasec-ios: LavaSecApp/GuardView.swift:122). Le visage est volontairement un signal *plus grossier et plus calme* que le badge de statut — le badge porte le détail, le visage reste simple :

| Condition | État de la mascotte |
|---|---|
| En pause temporaire | `paused` |
| connecté + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connecté + `recovering` / `networkUnavailable` | `retrying` |
| connecté + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| sinon | `sleeping` |

> **Réconciliation de la teinte.** La granularité de la teinte de protection reste alignée sur ce découpage d'expressions, pour que teinte et visage ne se contredisent jamais. La correspondance des expressions et la table de rôles sémantique `ProtectionTintRole` sont toutes deux livrées aujourd'hui (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, utilisée par `AppViewModel.protectionTintRole`). Seule la tokenisation par rôle de couleur `LavaColorRole`, qui ferait correspondre les rôles à des couleurs entièrement tokenisées, reste **Prévue** (Phase 3 du plan DS).

### 3.3 Habillages (looks) **(Implémenté)** {#33-skins-looks-implemented}

La mascotte est livrée avec **7 « looks » de bouclier sélectionnables**, persistés sous `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Chacun a sa propre gamme de couleurs et une couleur de glyphe Dynamic Island assortie :

`original`, `fireOpal` (valeur brute `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valeur brute `strawberryObsidian`), `emerald`, `kiwiCreme`.

Les deux anciennes valeurs brutes sont volontaires — ne les « corrigez » pas ; ça casserait les sélections déjà enregistrées des utilisateurs.

### 3.4 Masquage pour la vie privée **(Implémenté)** {#34-privacy-redaction-implemented}

La mascotte respecte le masquage pour la vie privée : l'expression peut être masquée quand la surface est censurée pour confidentialité, tandis que le **bouclier lui-même reste visible** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La présence de la protection rassure ; c'est l'état émotionnel précis qui se cache.

### 3.5 Pas dans cet arbre **(Prévu)** {#35-not-in-this-tree-planned}

Un easter-egg de mini-jeu sur l'onglet Protection (tap = animation de gratitude ; appui long de 10 s = un jeu où on attrape les mauvais domaines) est en **P3 / backlog**. Il ajouterait des expressions de mascotte en plus (`confused` / `dazed` / `inZone` / `powerSurge`) vues sur une branche de fonctionnalité — celles-ci ne sont **pas** dans l'app target. Selon les faits canoniques, la mascotte a exactement **7** états ; ne documentez pas les expressions du jeu comme livrées.

---

## 4. Copie et nommage {#4-copy-naming}

### 4.1 Voix et ton {#41-voice-tone}

Simple, calme, pratique. Évitez le langage sécuritaire anxiogène. Soyez honnête sur le périmètre : Lava fait du **filtrage local DNS/liste de blocage**, ce n'est pas une garantie que chaque domaine ou URL malveillant est bloqué, et la protection n'est **jamais** décrite comme active automatiquement dès que l'onboarding se termine — **l'onglet Protection fait foi** pour savoir si la protection est actuellement active.

### 4.2 Étiquettes de transport DNS {#42-dns-transport-labels}

Les annotations de transport suivent une convention compacte stricte (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 et lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, verrouillée par `DNSResolverPresetTests.swift`) :

| Transport | Étiquette | Remarques |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basé sur URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sans slash)** | par ex. « Quad9 (DoH3) ». Annoté **uniquement quand une négociation h3 est réellement observée** — préféré, jamais promis ; sinon retombe sur `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS en clair | `IP` | |
| résolveur de l'appareil | *(aucune annotation)* | |

La règle la plus souvent cassée ici, c'est le **`DoH3` sans slash** — écrivez `DoH3`, jamais `DoH/3` ni `DoH3 (h3)`, et ne l'appliquez jamais à la légère. Ces étiquettes de transport sont émises par `DoHTransport`/`DNSResolverPreset` ; gardez-les verbatim dans chaque locale, mais notez qu'elles ne sont *pas* des entrées Do-Not-Translate du glossaire (voir §4.3).

### 4.3 Termes à ne pas traduire {#43-do-not-translate-terms}

Les termes de marque et de protocole sont figés verbatim dans **toutes** les locales. La liste Do-Not-Translate du glossaire de localisation fait autorité, et elle fige : **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Parmi les transports DNS, seul **DoH** est une entrée Do-Not-Translate du glossaire ; `DoH3`, `DoT` et `DoQ` sont des étiquettes de transport (voir §4.2), pas des termes du glossaire. Ils s'écrivent quand même verbatim, mais ne citez pas le glossaire comme source.

### 4.4 Cadrage de la sécurité {#44-safety-framing}

Le paiement ne contourne jamais le **garde-fou de sécurité** non franchissable et validé par hash. Énoncez la priorité de façon cohérente : **garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autorisation par défaut.**

---

## 5. UX d'onboarding **(Implémenté)** {#5-onboarding-ux-implemented}

L'onboarding du premier lancement est un flux multi-pages — **6 pages** (`OnboardingPage` : `lava → guardIntro → features → vpn → notifications → done`) — implémenté dans lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Il réutilise le `SoftShieldGuardian` pour le moment où la mascotte apparaît.

Les 6 pages :

1. **Internet, c'est de la lave** (`lava`) — le danger présenté comme une métaphore ; action principale « Rencontrer Lava ».
2. **Lava veille ici** (`guardIntro`) — le moment où la mascotte apparaît.
3. **Présentation des fonctionnalités** (`features`) — ce que fait Lava ; « Configurer la protection ».
4. **Installer le VPN local de Lava** (`vpn`) — explique pourquoi iOS dit « VPN » pour un tunnel de paquets DNS-only.
5. **Activer les notifications** (`notifications`) — la demande d'autorisation, présentée au bon moment plutôt que d'entrée.
6. **Configuration terminée** (`done`) — « Ouvrir Protection », avec une configuration supplémentaire en option.

Les décisions de design intégrées au flux :

- **« Utiliser les réglages par défaut » est l'action principale, « Personnaliser » la secondaire.** Un chemin par défaut sans friction pour les utilisateurs non techniques ; le contrôle se mérite, il n'est pas imposé.
- **Le danger présenté comme une métaphore, pas comme de la peur** (« Internet, c'est de la lave »), en cohérence avec le ton calme.
- **Le flux explique pourquoi iOS dit « VPN »** — un tunnel de paquets est le seul moyen de filtrer le DNS à l'échelle du système ; ce n'est pas du routage de trafic.
- **Ne prétend jamais que la protection est active automatiquement à la fin** — l'onglet Protection fait foi.
- Retour par chevron uniquement, sur une mise en page d'étape partagée.

Les réglages par défaut que le flux installe au premier lancement : résolveur **Device DNS** (`DNSResolverPreset.device`), **repli sur le DNS de l'appareil ACTIVÉ**, journalisation activée (compteurs + historique + activité), et « Continuer sans compte ».

> **Divergence sur la liste de blocage par défaut (le code gagne).** La copie du plan d'onboarding indique HaGeZi Multi Light comme liste de blocage par défaut, mais le défaut du code livré est **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, défini dans lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). La vraie barrière de niveau, c'est le **quota de règles de filtrage (Gratuit 500K / Plus 2M)**, *pas* un nombre de listes. Suivi en interne. Pour le modèle de niveaux et la config par défaut recommandée, voir [le catalogue de fonctionnalités](../product/features.md).

---

## 6. Internationalisation **(En cours)** {#6-internationalization-in-progress}

Lava se localise en **6 locales** : **en** (source) + **ja, zh-Hant, zh-Hans, de, fr**, via les catalogues de chaînes Xcode.

- **La couture de localisation, c'est `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, adossé à `LavaStrings.localized` → `NSLocalizedString` avec un fallback anglais ; lavasec-ios: LavaSecApp/LavaStrings.swift). **Toute la copie des composants** doit passer par là — pas de chaînes littérales nues dans les vues.
- **zh-Hant** utilise une formulation adaptée à Taïwan au premier passage.
- Les métadonnées de l'App Store existent pour les 6 locales.
- Ordre de priorité pour la traduction : ja, zh-Hant, zh-Hans, de, fr.

Les fondations sont en place mais la relecture humaine complète de la traduction reste à faire avant la sortie, donc le statut global est **En cours**.

> **Nettoyage de la frontière de présentation (Prévu, Phase 4).** `LavaSecCore`/`Shared` devraient porter de la *sémantique* (enums de gravité/action, rôles d'icône), pas des chaînes anglaises. La présentation de la teinte de gravité a déjà été remontée dans le `ProtectionTintRole` sémantique. Ce qui reste, c'est que les `displayName` des résolveurs sont encore des chaînes anglaises codées en dur (« Google », « Cloudflare », « Quad9 », « Device DNS ») dans lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Phase 4 les remonte dans une carte de présentation côté app, par OS — la bonne approche à la fois pour l'i18n et la portabilité Android.

La mécanique de l'i18n (le glossaire de localisation, le schéma des fichiers de localisation et la checklist de relecture de traduction) vit dans les docs i18n internes, pas dans cet ensemble public.

---

## 7. Artefacts de référence {#7-reference-artifacts}

Références de design HTML (non livrées, internes) : le storyboard du flux d'onboarding, une étude du look de la mascotte en kiwi-creme, et des options visuelles pour le bouton principal en panneau.

La fondation du DS est en place : le groupe `LavaDesignSystem/`, les tokens `LavaSpacing`/rayons/`dangerRed`, la sémantique de profondeur `LavaTier` et la couche de rôles `LavaIcon` sont tous livrés (lavasec-ios: LavaSecApp/LavaDesignSystem/). Ce qui reste **Prévu** dans le plan de portabilité/fondation, c'est la tokenisation de l'accent `LavaColorRole` (Phase 3), la carte de présentation par OS pour les chaînes anglaises côté core (Phase 4), un JSON de tokens neutre et multiplateforme, et les coutures de portabilité Android plus larges.
