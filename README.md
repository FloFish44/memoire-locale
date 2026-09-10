# Retrio
Assistant Windows de recherche documentaire intelligent, simple et entièrement local. Site officiel : [retrio.eu](https://retrio.eu/).

## Version 0.5.0 : parcours guidé et photos

L'interface conserve les polices et la palette de la version web d'origine. Elle ajoute quatre étapes, les réglages toujours accessibles, le Bureau, le filtre par dossier et sous-dossier, la meilleure correspondance en doré et une aide centrale (vidéo à produire). La barre verte comporte les commandes réduire, agrandir et fermer. L'identité Windows Retrio est définie pour la barre des tâches.

Le parcours ignore les sous-dossiers Codex, Claude et caches techniques. Un dossier technique explicitement choisi comme racine peut néanmoins être analysé. Les sélections personnalisées peuvent être retirées avant une nouvelle analyse.

Les images sont classées localement par MobileNet embarqué et leurs étiquettes sont mises en cache dans `%LOCALAPPDATA%\Retrio\index-images.sqlite3`. Cette première version reconnaît des catégories courantes (chats, chiens, oiseaux, véhicules, etc.), surtout le sujet dominant. Elle ne garantit pas de retrouver tous les objets ni toutes les scènes. Les formats non pris en charge et les sujets non identifiés sont signalés dans les résultats. « Image » et « photo » activent le filtre Images ; ces mots ne sont plus exigés dans le contenu. Le bouton « Non, affiner » propose des filtres, sans prétendre entraîner automatiquement un modèle.

Validation : 12 tests automatiques, reconnaissance réelle d'une photo de chat et de chien, contrôle visuel du parcours avec données fictives. Le test `--self-test` vérifie aussi le chargement du moteur visuel embarqué. Les modèles restent fournis dans `logiciel/models` ; voir les informations et la licence dans ce dossier.

## Version 0.4.0 : recherche dans les PDF

Sélectionnez vos dossiers puis cliquez sur Analyse, y compris après une mise à jour ou un redémarrage. Recherchez par exemple « facture EDF » : le contenu des PDF est lu page par page, indépendamment du nom du fichier. Les pages scannées utilisent la reconnaissance de caractères de Windows, localement. Les résultats affichent un extrait et sa page ; le bilan indique les PDF lus, partiels ou illisibles. Le bouton Arrêter interrompt l'analyse.

Le moteur combine mots, synonymes et tolérance aux fautes ; ce n'est pas encore un modèle de compréhension sémantique général. L'OCR nécessite une langue de reconnaissance installée dans Windows. Aucun document n'est envoyé sur Internet. Le cache de texte PDF reste dans `%LOCALAPPDATA%\Retrio\index-pdf.sqlite3` ; la liste générale des fichiers est reconstruite à chaque analyse. Supprimer ce cache efface les textes mémorisés et impose leur relecture.

Limites de lecture par PDF : 100 Mio, 300 pages, 2 millions de caractères et 180 secondes. Les limites atteintes, erreurs et fichiers protégés sont signalés. Les fichiers disponibles uniquement dans le cloud ne sont pas téléchargés automatiquement.

## Développement et validation

Sous Windows, installez `logiciel/requirements.txt`, puis lancez `python logiciel/retrio_web.py`. `logiciel/build_web.bat` produit la version portable. Conservez le dossier `_internal` à côté de l'exécutable.

Pour les tests : installez aussi `reportlab==5.0.1`, puis lancez `python -m unittest discover -s logiciel/tests -v`. Le test OCR utilise des documents fictifs. L'exécutable accepte `--self-test chemin-absolu.json` pour vérifier la lecture d'un PDF scanné avec les dépendances embarquées.
