# Interior & cockpit

## Replacing the interior

The `interior` block of the fit config replaces the donor's interior and cockpit meshes:

```json
"interior": {
  "root": "INTERIOR",
  "steering_root": "INT_STEERING_WHEEL",
  "exclude": ["Int_Airbag*", "Int_Window*"],
  "material_classes": {"Leather Smooth Black": "LEATHER", "Pillars Dark": "PLASTIC", "Stitching Red": "SKIP"},
  "donor_materials": {"LEATHER": "POLO_GTS_LEATHER_BLACK", "PLASTIC": "POLO_DASHBOARD_PLASTIC"},
  "decimate": {"vw_virtus_gts_interior_loda": 0.15},
  "targets": {
    "vw_virtus_gts_interior_loda": "interior",
    "vw_virtus_gts_steeringwheel_loda": "steering",
    "vw_virtus_gts_interior_cpit": {"kind": "interior", "exclude": ["Int_Seats_SCB*"]},
    "vw_virtus_gts_windows_cpit": {"kind": "interior", "objects": ["Int_Seats_SCB*"],
                                   "materials_from": "vw_virtus_gts_interior_cpit"},
    "vw_virtus_gts_steeringwheel_cpit": "steering"
  }
}
```

- Interior classes map to donor interior materials (`donor_materials`); new faces get that material's
  most common texel (a flat colour). Custom materials work here too.
- `*_loda` is the interior seen from outside: decimate it hard (0.15).
- `*_cpit` is the view from the seat. A detailed interior doesn't fit in one mesh: split it over
  `interior_cpit` and the otherwise hidden `windows_cpit` slot with `objects` / `exclude` lists.
- Screens, ambient-light strips, stitching and decals: `SKIP` unless you have a material for them.

## Steering wheel

- `steering_root` names the model's wheel. The fit moves its centre and axis onto the donor wheel's
  (the axis the game rotates it about). On the Jetta that was a 4 cm, 2-4° correction.
- Without the alignment the wheel wobbles when turning.

## Body seen from the seat

- By default the cockpit body (`body_cpit`) is derived from the body LOD A. Parts sent to other slots by
  `part_slots` would have no cockpit copy.
- `cockpit_body` puts full-detail model parts there instead, cut below a height:

```json
"cockpit_body": {
  "vw_virtus_gts_body_cpit": {"objects": ["Ext_Body#Car_Paint", "Ext_Door_*", "Ext_Window_*"], "min_z": 0.75}
}
```

- Donor cockpit-only parts (bonnet, wipers) stay visible from the seat unless hidden.
- Check the driver's view: `render_preview(car.blend, out.png, view="cockpit:x,y,z[,yaw]")` with the
  eye point from the cockpit properties (Virtus 0.334, 1.228, 0.109), then in game from the cockpit
  camera.
