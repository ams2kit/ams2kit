// Specs page fields: [cfg path, label, type, options, help]. Types are drawn by components/SpecField.vue.
export const SPEC_FIELDS = [
  ["Identity", [
    ["car.display_name", "Display name"], ["car.short_name", "Short name"], ["car.manufacturer", "Manufacturer"], ["car.model", "Model"],
    ["car.year", "Year", "number"], ["car.class", "Class", "class"], ["car.country", "Country"], ["car.region", "Region", "select", ["EU", "NA", "SA", "AS", "OC", "AF"]],
    ["car.engine_placement", "Engine placement (menu)", "select", ["", "Front", "Mid-Front", "Mid", "Mid-Rear", "Rear"], "Empty keeps the donor's."],
    ["car.description", "Description", "textarea"]]],
  ["Powertrain", [
    ["powertrain.type", "Type", "select", ["ev", "ice"], "EV: single speed with a constant-power motor curve. ICE: your torque curve and gears."],
    ["powertrain.power_kw", "Power (kW)", "number"], ["powertrain.torque_nm", "Torque (Nm)", "number", null, "Shown in the menu."],
    ["powertrain.rev_limit", "Rev limit (rpm)", "number"], ["powertrain.top_speed_kmh", "Top speed (km/h)", "number", null, "EV: the gearing is set so the rev limit gives this speed."],
    ["powertrain.base_speed_fraction", "EV base speed (share of rev limit)", "number", null, "Constant torque up to here, constant power above. 0.45 is typical."],
    ["powertrain.torque_curve", "ICE torque curve", "pairs", null, "One rpm,Nm pair per line."],
    ["powertrain.gears", "ICE gear ratios", "list", null, "Comma-separated, 1st to top gear. Must match the donor's gear count."],
    ["powertrain.final_drive", "ICE final drive", "number"],
    ["powertrain.driveline", "Driveline", "driveline", null, "Which wheels are driven and how (any layout the game has). Empty keeps the donor's."],
    ["powertrain.drivetrain", "Drivetrain (menu label)", "select", ["AWD", "RWD", "FWD"], "Follows the driveline above when one is chosen."],
    ["powertrain.engine_layout", "Engine label (menu)", "engine", null, "The game has no electric label; pick the closest."],
    ["powertrain.displacement_l", "Displacement (L)", "number"]]],
  ["Chassis", [
    ["chassis.mass_kg", "Mass (kg)", "number", null, "0 keeps the donor's."], ["chassis.cg_height_m", "CG height (m)", "number", null, "0 keeps the donor's."],
    ["chassis.wheelbase_m", "Wheelbase (m)", "number", null, "0 keeps the donor's."], ["chassis.track_front_m", "Front track (m)", "number"],
    ["chassis.track_rear_m", "Rear track (m)", "number"], ["chassis.wheel_radius_m", "Rolling radius (m)", "number", null, "Used for the EV gearing; 0 = donor's."],
    ["chassis.rear_weight", "Rear weight share (menu)", "number"], ["stats.zero_to_100_s", "0-100 km/h (menu, s)", "number"]]],
];

// Menu "Engine" labels by stats index (text\vehicledetails.tdb; mapped from base cars, docs/05).
export const ENGINE_LABELS = [[1, "V6"], [2, "V8"], [3, "V10"], [4, "V12"], [18, "V4"], [5, "Straight 4"], [6, "Straight 5"], [7, "Straight 6"],
  [10, "Flat 4"], [11, "Flat 6"], [16, "Flat 8"], [17, "Flat 12"], [13, "W12"], [12, "W16"], [8, "Rotary 2"], [9, "Rotary 3"],
  [14, "Single cylinder"], [15, "Twin cylinder"]];
