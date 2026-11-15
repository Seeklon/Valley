# Hébergement space.in-momentum.fr

Le site statique conserve le parcours Valley et affiche les sorties enregistrées du
modèle dans les intérieurs 3D. Aucun calcul FDS, entraînement ou serveur d’inférence
n’est lancé sur ce VPS. Les scénarios sont chargés à la demande et vérifiés par SHA256.

## Installation

VPS vérifié le 15 novembre 2026 : `vmi3528473.contaboserver.net`, IPv4
`169.58.224.69`. Stack autonome `/opt/momentum-space`, projet Compose
`momentum-space`, conteneur du même nom. Le proxy Traefik partagé existant
`coolify-proxy` dessert le réseau `momentum-personal-edge`. Ne pas le recréer.

- Configurations : `compose.yaml`, `nginx.conf` dans `/opt/momentum-space`.
- Routage : `/data/coolify/proxy/dynamic/momentum-space.yaml`, rechargé à chaud.
- Versions statiques : `/srv/momentum-space/releases/<version>`.
- Version active : lien relatif `/srv/momentum-space/current`.
- L’intégralité de `/srv/momentum-space` est montée en lecture seule : le
  remplacement atomique du lien est visible sans redémarrer le conteneur.
- Aucun port hôte publié ; le service écoute sur 8080 dans le réseau Docker.
- Nginx non-root, limites 1 CPU / 256 Mio, image épinglée par digest.
- JSON compressés à l’avance pour réduire les transferts ; revalidation HTTP
  des ressources et index sans cache persistant côté application.

Le fichier public `/release.json` identifie le modèle et l’index servis.
La version ventilation utilise les poids
`ce0ffc80e51d9be2da94fc50f098fc4ac3c223203d09c8908ea8bbd6f4eff292`
et l’index `7e587516076d6f50abb26dd9cb0119072c64764a26e920a4d8ba179c9bf9246e`.
Les 216 cas sont en microgravité ; Terre et Lune restent en aperçu sans prédiction.

## DNS OVH et HTTPS

Ajouter cette ligne au contenu existant de la zone `in-momentum.fr`, via
« Zone DNS → Actions sur ma zone → Modifier en mode textuel ». Ne pas remplacer
la zone complète. Aucun A, AAAA ou CNAME préexistant pour `space` au contrôle.

```dns
space 300 IN A 169.58.224.69
```

Après résolution publique, utiliser la configuration `traefik.yaml` complète
de ce dossier pour activer le résolveur ACME `letsencrypt` existant.
Avant cela, une configuration provisoire avec `tls: {}` permet la recette de
routage par `curl --resolve`, avec un certificat provisoire non fiable.
Le site n’est publiquement prêt qu’après validation DNS et HTTPS sans `-k`.

```bash
sudo docker compose -f /opt/momentum-space/compose.yaml ps
sudo docker compose -f /opt/momentum-space/compose.yaml exec -T site nginx -t
dig +short space.in-momentum.fr A
curl -fsS https://space.in-momentum.fr/healthz
curl -fsS https://space.in-momentum.fr/release.json
```

## Mise à jour

Importer un export complet validé avec `npm run data:predictions`, exécuter
`npm test` et `npm run build`, puis contrôler le navigateur. Actualiser les
vignettes avec `npm run data:previews` et reconstruire. Ne pas prendre un
checkpoint expérimental ni modifier les seuils du modèle lors de la publication.

Copier `dist/` vers une nouvelle version sous `releases/`, vérifier ses hashes,
et préparer ses fichiers `.gz` avant la bascule. Remplacer le lien `current`
atomiquement ; conserver la version précédente pour revenir en arrière.
Ne jamais lancer une copie qui modifie la version déjà servie.

Pour revenir à une version conservée, remplacer `VERSION` par le nom relu
dans `/srv/momentum-space/releases` :

```bash
sudo ln -s releases/VERSION /srv/momentum-space/current.next
sudo mv -Tf /srv/momentum-space/current.next /srv/momentum-space/current
```

Pour retirer uniquement ce site : supprimer sa configuration dynamique
`momentum-space.yaml`, puis `docker compose -f /opt/momentum-space/compose.yaml down`.
Conserver ses versions et tous les autres fichiers du proxy. Ne pas redémarrer Traefik.

La recette serveur utilise SwiftShader pour les intérieurs WebGL et le parcours
extérieur pré-rendu existant. L’extérieur WebGL forcé reste à valider sur un
navigateur avec GPU matériel.
