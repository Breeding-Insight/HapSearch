// Alignment tab: clicking an allele name (a row label of the alignment) opens
// that allele in the Microhaplotypes tab. Plotly reports no clicks on axis
// labels, so this listens for them directly. The figure carries the full
// allele names in layout.meta.allele_names, indexed like the row tick values
// (see create_msa_figure in pages/marker_explorer.py).
document.addEventListener("click", function (event) {
  var label = event.target.closest && event.target.closest("#msa-graph .ytick");
  if (!label || !window.dash_clientside || !window.dash_clientside.set_props) {
    return;
  }
  var graph = label.closest(".js-plotly-plot");
  var names = graph && graph.layout && graph.layout.meta && graph.layout.meta.allele_names;
  var tick = label.__data__;
  if (!names || !tick || typeof tick.x !== "number") {
    return;
  }
  var name = names[Math.round(tick.x)];
  if (name) {
    window.dash_clientside.set_props("navigate-to-haplotype-store", {
      data: { haplotype_name: name },
    });
  }
});
