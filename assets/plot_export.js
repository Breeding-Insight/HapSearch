// Save menus built by pages/export_controls.py: saves a Plotly chart as an
// image under the file name shown in the menu.
(function () {
  function getControlValue(chartKey, suffix, fallback) {
    const control = document.getElementById(`${chartKey}-${suffix}`);
    if (!control) {
      return fallback;
    }

    const value = Number(control.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function getSelectValue(chartKey, suffix, fallback) {
    const control = document.getElementById(`${chartKey}-${suffix}`);
    return control && control.value ? control.value : fallback;
  }

  // Match clean_filename in pages/export_controls.py: drop a typed extension
  // and characters file systems reject.
  function cleanFilename(name, fallback, extension) {
    let cleaned = (name || "").trim();
    const suffix = `.${extension}`.toLowerCase();
    if (cleaned.toLowerCase().endsWith(suffix)) {
      cleaned = cleaned.slice(0, -suffix.length);
    }
    cleaned = cleaned.replace(/[\\/:*?"<>|\s]+/g, "_").replace(/^[._]+|[._]+$/g, "");
    return cleaned || fallback;
  }

  function savePlot(button) {
    const chartKey = button.dataset.exportChart;
    const graphId = button.dataset.exportGraph;
    const graph = graphId && document.getElementById(graphId);
    const plot = graph && graph.querySelector(".js-plotly-plot");

    if (!chartKey || !plot || !window.Plotly) {
      return;
    }

    const imageType = getSelectValue(chartKey, "image-type", "png");
    const nameInput = document.getElementById(`${chartKey}-image-filename`);
    const filename = cleanFilename(
      nameInput && nameInput.value,
      button.dataset.exportFilename || "haplosearch_plot",
      imageType
    );
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
    const saveButton = menu && menu.querySelector("[data-export-chart]");
    if (!saveButton) {
      return;
    }
    const chartKey = saveButton.dataset.exportChart;
    const graph = document.getElementById(saveButton.dataset.exportGraph);
    const plot = graph && graph.querySelector(".js-plotly-plot");
    if (!plot || !plot.clientWidth || !plot.clientHeight) {
      return;
    }
    const cssPixelsPerInch = 96;
    const sizes = { "image-width": plot.clientWidth, "image-height": plot.clientHeight };
    Object.entries(sizes).forEach(function ([suffix, pixels]) {
      const input = document.getElementById(`${chartKey}-${suffix}`);
      if (input) {
        setInputValue(input, (pixels / cssPixelsPerInch).toFixed(1));
      }
    });
  }

  // Keep the extension shown after the file name in step with the file type.
  document.addEventListener("change", function (event) {
    const select = event.target;
    if (!select.id || !select.id.endsWith("-image-type")) {
      return;
    }
    const chartKey = select.id.slice(0, -"-image-type".length);
    const extension = document.getElementById(`${chartKey}-image-ext`);
    if (extension) {
      extension.textContent = `.${select.value}`;
    }
  });

  document.addEventListener("click", function (event) {
    const toggle = event.target.closest(".dropdown-toggle");
    if (toggle) {
      // The menu's contents render as it opens.
      setTimeout(function () { fillOnScreenSize(toggle); }, 0);
      return;
    }

    const button = event.target.closest("[data-export-chart]");
    if (!button) {
      return;
    }

    event.preventDefault();
    savePlot(button);
  });
})();
