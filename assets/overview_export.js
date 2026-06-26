(function () {
  function getControlValue(chartKey, suffix, fallback) {
    const control = document.getElementById(`overview-${chartKey}-${suffix}`);
    if (!control) {
      return fallback;
    }

    const value = Number(control.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function getSelectValue(chartKey, suffix, fallback) {
    const control = document.getElementById(`overview-${chartKey}-${suffix}`);
    return control && control.value ? control.value : fallback;
  }

  function savePlot(button) {
    const chartKey = button.dataset.overviewExportChart;
    const graphId = button.dataset.overviewExportGraph;
    const filename = button.dataset.overviewExportFilename || "haplosearch_plot";
    const graph = graphId && document.getElementById(graphId);
    const plot = graph && graph.querySelector(".js-plotly-plot");

    if (!chartKey || !plot || !window.Plotly) {
      return;
    }

    const imageType = getSelectValue(chartKey, "image-type", "png");
    const resolution = getControlValue(chartKey, "image-res", 300);
    const widthInches = getControlValue(chartKey, "image-width", 10);
    const heightInches = getControlValue(chartKey, "image-height", 6);
    const cssPixelsPerInch = 96;

    window.Plotly.downloadImage(plot, {
      format: imageType,
      filename: filename,
      width: Math.max(1, Math.round(widthInches * cssPixelsPerInch)),
      height: Math.max(1, Math.round(heightInches * cssPixelsPerInch)),
      scale: imageType === "svg" ? 1 : Math.max(1, resolution / cssPixelsPerInch),
    });
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-overview-export-chart]");
    if (!button) {
      return;
    }

    event.preventDefault();
    savePlot(button);
  });
})();
