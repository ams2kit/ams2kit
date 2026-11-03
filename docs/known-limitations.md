# Work in progress / known limitations

- **Tested on a handful of donors** (Lamborghini Veneno, Chevrolet Camaro SS, Mitsubishi Lancer R,
  VW Virtus GTS, BMW M4 GT3). Other donors may need fixes; open an issue with the Doctor output.
- **Windows and Steam only.** No other platforms or stores.
- **Game updates can break it.** The file formats were worked out by hand.
- **Materials:** your model must use the donor's materials. Own textures/materials are not supported yet
  (needs a `.bmt` writer). Liveries are plain colours only (no designs or decals).
- **Interior and sound** stay the donor's unless you replace the interior meshes; the engine sound is
  always the donor's.
- **No native EV.** Electric cars are emulated through the engine model; the menu has no EV engine label
  ([11](11-electric-drive.md)).
- **Collision shape** is the donor's.
- **Skinned meshes** (tyres, wipers) can only be kept, resized (tyres) or deleted.
- **Damage:** damage morphs of rebuilt meshes are undeformed.
- **Tyre sets:** a car must use one of the game's tyre sets; grip can't be edited per car
  ([13](13-tyres.md)).
- **Custom classes** are not supported; the car goes into an existing class.
- **Automated testing** needs one manual Custom Race with your car first, and clicks fixed 1920x1080
  window coordinates for the menu screenshots.
- **Physics field names** are partly guesses; each field is tagged `proven` / `strong` / `guess` /
  `unknown` ([14](14-physics-fields.md)).
- **Tests** that need game data are skipped unless the game (and, for some, extracted files) is present;
  see [CONTRIBUTING.md](../CONTRIBUTING.md).
- The numbered research notes are working notes, not a tutorial.

Known code issues: [REVIEW.md](../REVIEW.md).
