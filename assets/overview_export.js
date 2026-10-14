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

  // Set a React-controlled input so Dash sees the change too.
  function setInputValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // When a Save menu opens, default Width and Height to the chart's size on
  // screen, so the image matches what is shown (layouts such as the sharing
  // chart's square cells change shape at other sizes). They can still be edited.
  function fillOnScreenSize(toggle) {
    const menu = toggle.closest(".dropdown");
    const saveButton = menu && menu.querySelector("[data-overview-export-chart]");
    if (!saveButton) {
      return;
    }
    const chartKey = saveButton.dataset.overviewExportChart;
    const graph = document.getElementById(saveButton.dataset.overviewExportGraph);
    const plot = graph && graph.querySelector(".js-plotly-plot");
    if (!plot || !plot.clientWidth || !plot.clientHeight) {
      return;
    }
    const cssPixelsPerInch = 96;
    const sizes = { "image-width": plot.clientWidth, "image-height": plot.clientHeight };
    Object.entries(sizes).forEach(function ([suffix, pixels]) {
      const input = document.getElementById(`overview-${chartKey}-${suffix}`);
      if (input) {
        setInputValue(input, (pixels / cssPixelsPerInch).toFixed(1));
      }
    });
  }

  document.addEventListener("click", function (event) {
    const toggle = event.target.closest(".dropdown-toggle");
    if (toggle) {
      // The menu's contents render as it opens.
      setTimeout(function () { fillOnScreenSize(toggle); }, 0);
      return;
    }

    const button = event.target.closest("[data-overview-export-chart]");
    if (!button) {
      return;
    }

    event.preventDefault();
    savePlot(button);
  });
})();
