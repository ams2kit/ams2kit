// Chart.js setup shared by the physics curve editors (components/TorqueEditor.vue, GearingEditor.vue):
// vue-chartjs for the charts, chartjs-plugin-dragdata (registers itself on import) for draggable points.
import { Chart, Legend, LinearScale, LineElement, PointElement, Tooltip } from "chart.js";
import "chartjs-plugin-dragdata";

Chart.register(LinearScale, PointElement, LineElement, Tooltip, Legend);
Chart.defaults.color = "#9a9aa3";
Chart.defaults.borderColor = "#34343b";
Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';

// Colours checked with the dataviz palette validator on the dark panel (#1d1d21).
export const C = { mine: "#e8484d", donor: "#3f8fe0", limit: "#d29922", faint: "rgba(154,154,163,.35)" };
export const HP = 1.35962;
export const kw = (nm, rpm) => nm * rpm / 9549.3;

// a nice round axis maximum just above v
export function niceMax(v) {
  const mag = 10 ** Math.floor(Math.log10(Math.max(v, 1e-9))), step = v / mag < 2 ? mag / 5 : mag;
  return Math.ceil(v / step) * step;
}

// linear interpolation in sorted [[x, y], ...]
export function interp(pts, x) {
  if (!pts.length) return null;
  if (x <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++)
    if (x <= pts[i][0]) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i]; return y0 + (y1 - y0) * (x - x0) / (x1 - x0 || 1); }
  return pts.at(-1)[1];
}

// power curve of a torque curve, sampled inside each segment (power is not linear between points)
export function powerPts(pts, steps = 8) {
  const out = [];
  pts.forEach((p, i) => {
    if (i === 0) { out.push([p[0], kw(p[1], p[0])]); return; }
    const [x0, y0] = pts[i - 1];
    for (let s = 1; s <= steps; s++) { const t = s / steps, x = x0 + (p[0] - x0) * t; out.push([x, kw(y0 + (p[1] - y0) * t, x)]); }
  });
  return out;
}

export const xy = pts => pts.map(([x, y]) => ({ x, y }));

// a line series (no points) that cannot be dragged
export const ref = (label, pts, color, extra = {}) => ({
  label, data: xy(pts), borderColor: color, backgroundColor: color, showLine: true, pointRadius: 0, pointHitRadius: 0,
  borderWidth: 2, dragData: false, ...extra,
});

// base options: linear x, no animation (drags redraw every frame)
export function baseOptions({ x, y, onDrag, onDragEnd, tooltip }) {
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "nearest", intersect: true },
    scales: {
      x: { type: "linear", min: 0, ...x, grid: { color: "#2a2a30" }, title: { display: !!x.title, text: x.title } },
      // fixed width so stacked charts (torque over power) share the same x pixels
      y: { type: "linear", min: 0, ...y, grid: { color: "#2a2a30" }, title: { display: !!y.title, text: y.title }, afterFit: s => { s.width = 64; } },
    },
    plugins: {
      legend: { position: "top", align: "end", labels: { boxWidth: 16, boxHeight: 2, filter: i => !i.text.startsWith("_") } },
      tooltip: { filter: i => !i.dataset.label.startsWith("_"), ...tooltip },
      dragData: { dragX: true, dragY: true, showTooltip: true, onDrag, onDragEnd },
    },
  };
}
