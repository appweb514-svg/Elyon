# Disposition d'affichage (layout)

MVP : zones statiques avec position/taille en pourcentage, stocké sur
`Screen.layout_json` et inclus tel quel dans le manifeste (player ignore
si absent → compatibilité).

## Modèle

`Screen.layout_json` : `Text` nullable. Schémas Pydantic :

```python
class ScreenLayoutZone(BaseModel):
    x: float  # 0..100 (%)
    y: float
    w: float
    h: float
    media_id: str | None = None
    playlist_id: str | None = None

class ScreenLayout(BaseModel):
    mode: str  # fullscreen|grid_2x2|split_h|split_v|custom
    zones: list[ScreenLayoutZone]
```

API : `ScreenCreate.layout?`, `ScreenPatch.layout?`, `ScreenOut.layout?`.
`PATCH /screens/{id}` valide le layout (422 si hors bornes).

## Modes prédéfinis

| Mode | Zones par défaut |
|---|---|
| `fullscreen` | 1 zone 0,0 100×100 |
| `split_h` | 2 zones 100×50 empilées |
| `split_v` | 2 zones 50×100 côte à côte |
| `grid_2x2` | 4 zones 50×50 |
| `custom` | zones libres |

Chaque zone référence **un** média ou **une** playlist (pas les deux).

## Dans le manifeste

`services/manifest.py:build_manifest_payload` ajoute :

```json
{ "device_id": "…", "screen_id": "…", "layout": { "mode": "grid_2x2", "zones": [...] }, "blocks": [...], "media": [...] }
```

`layout: null` si non configuré.

## Éditeur

`apps/web/src/components/layout-editor.tsx` : sélecteur de mode,
prévisualisation aspect 16:9, formulaire par zone (x/y/w/h %, média/playlist),
ajout/suppression de zones. Page `devices/[id]/layout` (device → écran) avec
enregistrement + bouton Publier.

## Player

Extension future : zones animées, transitions, z-index, media par zone
avec playlist indépendante. Le format actuel est extensible (ajout de
champs optionnels sans casser le MVP).
