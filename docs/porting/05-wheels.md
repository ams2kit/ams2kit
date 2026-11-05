# Wheels

## Positions

- The fit places the model's wheels on the donor .blend's `WHEEL_*` markers, which follow the Specs
  wheelbase and tracks.
- The game draws wheels at the render file's hub positions, not at the physics wheel centres. The build
  moves the hubs for a new wheelbase and track. Some donors' physics frame is offset from the visual frame
  (Camaro SS: physics wheel height 0.2185 vs hub 0.35), so markers use the visual frame.
- `wheel_objects` names the model's four wheel objects. Wheels that share one mesh are made single-user
  before cutting (otherwise all four rims came out empty).

## Rims

- `rim_materials` lists the model materials that make up the rim; the rest of the wheel object (tyre,
  brake parts) is dropped from the rim.
- Rim radius: by default the donor tyre's inner radius plus a 5 mm flange overlap (`rim_fit: "tyre"`).
- Rims go into the donor's per-corner rim slots, including the spinning-blur variants.
- For textured rims (two-tone, machined faces), clone the donor rim material and set
  `rim_custom_material`:

```json
"rim_custom_material": "RIMS"
```
```toml
[materials.RIMS]
base = "VW_POLO_GTS_RIM"
base_color = "model/textures/atlas_basecolor.png"
roughness = "model/textures/atlas_roughness.png"
metallic = "model/textures/atlas_metallic.png"
```

## Tyres

- Tyres are skinned meshes: they can be kept, resized or deleted, not replaced by the model's tyres.
  Set the tyre size in Specs (`[chassis] tyre_size`); `resize_tyre_meshes` scales the donor's tyre meshes
  to it (doc [13](../13-tyres.md)).
- `tyre_materials` helps find wheel centres when the model's tyres are separate.

## Brake discs and calipers

- Model brake objects can be sent to the donor's caliper slots with `part_slots`. A single rear-caliper
  object for both sides needs `split_sides` first:

```json
"split_sides": ["Ext_Brake_Rear#Caliper"],
"part_slots": {
  "Ext_Brake_FL#Caliper": "vw_virtus_gts_caliper_lf_loda",
  "Ext_Brake_FR#Caliper": "vw_virtus_gts_caliper_rf_loda",
  "Ext_Brake_Rear#Caliper@L": "vw_virtus_gts_caliper_lr_loda",
  "Ext_Brake_Rear#Caliper@R": "vw_virtus_gts_caliper_rr_loda"
}
```

- Keep the donor's discs (they have the game's glow and wear setup); exclude the model's rotors with
  `exterior_exclude` (`"Ext_Brake_*#Brake_Rotor"`).
- Far LODs of calipers are not derived yet.
