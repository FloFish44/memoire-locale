# Mémoire locale — logiciel (bêta)

Application Windows qui analyse les dossiers de votre choix (Documents,
Images, Vidéos, Musique, Téléchargements, disques C:/D:...) et vous permet
de retrouver un fichier même si son nom ne veut rien dire.

**100 % local** : écrite en Python avec uniquement la bibliothèque standard
(module `tkinter`, inclus avec Python). Aucune dépendance à installer, aucun
envoi de données sur Internet.

## Lancer l'application (avec Python déjà installé)

1. Installez [Python 3.11+](https://www.python.org/downloads/) si ce n'est
   pas déjà fait (cochez « Add python.exe to PATH » pendant l'installation).
2. Double-cliquez sur `LANCER.bat` — ou depuis une invite de commandes :

   ```bat
   python memoire_locale.py
   ```

## Créer un fichier .exe autonome (pour vos clients, sans Python)

Le script `build_exe.bat` installe [PyInstaller](https://pyinstaller.org/)
(uniquement le temps de la compilation) puis génère un exécutable unique.

1. Double-cliquez sur `build_exe.bat` sur une machine Windows.
2. L'exécutable est généré dans `dist\Memoire_locale.exe`.
3. C'est ce fichier `.exe` qu'il faut proposer au téléchargement sur le site
   (il n'a besoin de rien d'autre pour fonctionner).

> Cette étape doit être faite sur une machine Windows (PyInstaller compile
> pour le système sur lequel il tourne). Elle n'a pas pu être faite depuis
> l'environnement de génération de ce projet, qui n'est pas Windows.

## Fonctionnalités de cette première version

- Sélection des dossiers à analyser (Documents, Images, Vidéos, Musique,
  Téléchargements, disques C:/D:, + tout dossier personnalisé).
- Bouton **Analyse** : parcourt les dossiers sélectionnés et affiche des
  statistiques compréhensibles (nombre de PDF, photos, vidéos, fichiers
  audio, doublons potentiels, fichiers au nom peu explicite, espace occupé).
- Barre de recherche avec exemples cliquables : retrouve les fichiers dont
  le nom ou le dossier correspond aux mots tapés (avec quelques synonymes :
  « facture », « photo », « devis »...).
- Pour chaque résultat : ouvrir le fichier, ouvrir son dossier, copier son
  chemin.
- L'analyse tourne dans un thread séparé : la fenêtre ne se fige jamais,
  même sur de très gros dossiers.

## Prochaines étapes (voir docs/mission-produit.md)

- Recherche en langage naturel plus poussée (au-delà des mots-clés).
- Renommage intelligent et classement automatique.
- Rappels et garanties liés aux documents retrouvés.
